"""Generation providers: LLM / image / video backends (design doc §3.4).

No fake/mock providers ship in the product: local development and testing
run on real local models (Ollama LLM, local diffusion for image/video).
The pipeline's deterministic per-node defaults remain as the final safety
net when an LLM returns unusable JSON.
"""
import base64
import hashlib
import json
import logging
import os
import re
import textwrap
import time
from abc import ABC, abstractmethod

import httpx
from PIL import Image, ImageDraw
from pydantic import ValidationError

from src.core import runtime_settings
from src.core.config import get_settings

logger = logging.getLogger(__name__)

_TIMEOUT = 60.0
_JSON_INSTRUCTION = "Respond with a single JSON object only."
_RETRY_ATTEMPTS = 3
_RETRY_BASE_DELAY = 1.0  # seconds; doubles each attempt


def _with_retry(fn, attempts: int = _RETRY_ATTEMPTS):
    """Call fn() with exponential-backoff retries on transient HTTP errors.

    Only transport-level failures (timeouts, 5xx, connection errors) are
    retried — a definitive 4xx answer means the request itself is wrong.
    """
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            return fn()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code < 500:
                raise
            last_exc = exc
        except (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError) as exc:
            last_exc = exc
        delay = _RETRY_BASE_DELAY * (2**attempt)
        logger.warning(
            "LLM call failed (attempt %d/%d): %s — retrying in %.1fs",
            attempt + 1, attempts, last_exc, delay,
        )
        time.sleep(delay)
    raise last_exc  # type: ignore[misc]


def _extract_json(text: str) -> dict:
    """Tolerantly pull the first {...} block out of an LLM response."""
    match = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not match:
        return {}
    try:
        data = json.loads(match.group(0))
    except (json.JSONDecodeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def merge_llm_schema(schema_cls, defaults: dict, llm_data: dict):
    """Merge LLM output over deterministic defaults with per-field fallback.

    Real LLMs occasionally return a wrong type for one field (a dict where a
    string belongs, a list where a scalar belongs). Rather than failing the
    whole pipeline run, revert just the offending fields to their defaults
    and keep every well-typed LLM value (§3.3).
    """
    data = dict(defaults)
    data.update(
        {k: v for k, v in (llm_data or {}).items() if k in schema_cls.model_fields}
    )
    for _ in range(len(schema_cls.model_fields) + 1):
        try:
            return schema_cls.model_validate(data)
        except ValidationError as exc:
            locs = {err.get("loc", (None,))[0] for err in exc.errors()}
            locs.discard(None)
            if not locs:
                break
            for loc in locs:
                if loc in defaults:
                    data[loc] = defaults[loc]
                else:
                    data.pop(loc, None)
    return schema_cls.model_validate(defaults)


# ── LLM ───────────────────────────────────────────────────────────────


class LLMProvider(ABC):
    """Text completion backend."""

    @abstractmethod
    def complete(self, system: str, prompt: str) -> str:
        """Return a free-text completion."""

    def complete_json(self, system: str, prompt: str) -> dict:
        """Return a JSON object completion; {} on any parse failure.

        Transient transport errors are retried with backoff; provider
        outages are handled one level up by FallbackLLM.
        """
        raw = _with_retry(
            lambda: self.complete(system, f"{prompt}\n\n{_JSON_INSTRUCTION}")
        )
        return _extract_json(raw)


class ClaudeLLM(LLMProvider):
    """Anthropic Messages API."""

    API_URL = "https://api.anthropic.com/v1/messages"
    MODEL = "claude-sonnet-4-20250514"

    def __init__(self) -> None:
        self._api_key = get_settings().anthropic_api_key
        if not self._api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set — add it to .env or use LLM_PROVIDER=ollama"
            )

    def complete(self, system: str, prompt: str) -> str:
        resp = httpx.post(
            self.API_URL,
            headers={
                "x-api-key": self._api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": self.MODEL,
                "max_tokens": 2048,
                "system": system,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        blocks = resp.json().get("content", [])
        return "".join(b.get("text", "") for b in blocks if b.get("type") == "text")


class OpenAILLM(LLMProvider):
    """OpenAI Chat Completions API."""

    API_URL = "https://api.openai.com/v1/chat/completions"
    MODEL = "gpt-4o"

    def __init__(self) -> None:
        self._api_key = get_settings().openai_api_key
        if not self._api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is not set — add it to .env or use LLM_PROVIDER=ollama"
            )

    def complete(self, system: str, prompt: str) -> str:
        resp = httpx.post(
            self.API_URL,
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={
                "model": self.MODEL,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
            },
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


class OllamaLLM(LLMProvider):
    """Local Ollama chat API (no key required; runs on the local GPU)."""

    def __init__(self) -> None:
        self._base_url = get_settings().ollama_base_url.rstrip("/")
        self._model = get_settings().ollama_model

    def _chat(self, system: str, prompt: str, json_mode: bool = False) -> str:
        payload = {
            "model": self._model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        }
        if json_mode:
            payload["format"] = "json"  # Ollama-enforced JSON output
        resp = httpx.post(
            f"{self._base_url}/api/chat", json=payload, timeout=_TIMEOUT
        )
        resp.raise_for_status()
        return resp.json().get("message", {}).get("content", "")

    def complete(self, system: str, prompt: str) -> str:
        return self._chat(system, prompt)

    def complete_json(self, system: str, prompt: str) -> dict:
        raw = _with_retry(
            lambda: self._chat(
                system, f"{prompt}\n\n{_JSON_INSTRUCTION}", json_mode=True
            )
        )
        return _extract_json(raw)


class FallbackLLM(LLMProvider):
    """Primary provider with an ordered fallback chain (§6.2 resilience).

    If the primary raises (outage, missing key), each fallback is tried in
    order. An empty/invalid JSON answer from the primary is NOT treated as
    a failure — it is a legitimate degrade the nodes already handle.
    """

    def __init__(self, primary: LLMProvider, fallbacks: list[LLMProvider]):
        self._primary = primary
        self._fallbacks = fallbacks

    def complete(self, system: str, prompt: str) -> str:
        try:
            return self._primary.complete(system, prompt)
        except Exception as exc:
            logger.warning("primary LLM failed (%s); trying fallbacks", exc)
        for provider in self._fallbacks:
            try:
                return provider.complete(system, prompt)
            except Exception as exc:
                logger.warning("fallback LLM %s failed: %s",
                               type(provider).__name__, exc)
        raise RuntimeError("all LLM providers in the fallback chain failed")

    def complete_json(self, system: str, prompt: str) -> dict:
        try:
            return self._primary.complete_json(system, prompt)
        except Exception as exc:
            logger.warning("primary LLM failed (%s); trying fallbacks", exc)
        for provider in self._fallbacks:
            try:
                return provider.complete_json(system, prompt)
            except Exception as exc:
                logger.warning("fallback LLM %s failed: %s",
                               type(provider).__name__, exc)
        return {}  # nodes fall back to their deterministic defaults


class OpenRouterLLM(LLMProvider):
    """OpenRouter — one OpenAI-compatible gateway to many hosted models."""

    API_URL = "https://openrouter.ai/api/v1/chat/completions"

    def __init__(self) -> None:
        self._api_key = get_settings().openrouter_api_key
        if not self._api_key:
            raise RuntimeError(
                "OPENROUTER_API_KEY is not set — add it to .env "
                "or use LLM_PROVIDER=ollama"
            )
        self._model = get_settings().openrouter_model

    def complete(self, system: str, prompt: str) -> str:
        resp = httpx.post(
            self.API_URL,
            json={
                "model": self._model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
            },
            headers={"Authorization": f"Bearer {self._api_key}"},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        choices = resp.json().get("choices") or []
        return choices[0]["message"]["content"] if choices else ""


# ── Images ────────────────────────────────────────────────────────────


class ImageProvider(ABC):
    """Image generation backend."""

    @abstractmethod
    def generate(self, prompt: str, out_dir: str, count: int = 1) -> list[str]:
        """Generate `count` images into `out_dir`; return the file paths."""


class DallEImage(ImageProvider):
    """OpenAI Images API (dall-e-3, b64 payload saved to disk)."""

    API_URL = "https://api.openai.com/v1/images/generations"
    MODEL = "dall-e-3"

    def __init__(self) -> None:
        self._api_key = get_settings().openai_api_key
        if not self._api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is not set — add it to .env or use IMAGE_PROVIDER=local"
            )

    def generate(self, prompt: str, out_dir: str, count: int = 1) -> list[str]:
        os.makedirs(out_dir, exist_ok=True)
        paths = []
        for i in range(count):  # dall-e-3 accepts n=1 only
            resp = httpx.post(
                self.API_URL,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": self.MODEL,
                    "prompt": prompt,
                    "n": 1,
                    "size": "1024x1024",
                    "response_format": "b64_json",
                },
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
            b64 = resp.json()["data"][0]["b64_json"]
            path = os.path.join(out_dir, f"image_{i + 1}.png")
            with open(path, "wb") as fh:
                fh.write(base64.b64decode(b64))
            paths.append(path)
        return paths


class StableDiffusionImage(ImageProvider):
    """Stability AI v2beta core image API."""

    API_URL = "https://api.stability.ai/v2beta/stable-image/generate/core"

    def __init__(self) -> None:
        self._api_key = get_settings().stability_api_key
        if not self._api_key:
            raise RuntimeError(
                "STABILITY_API_KEY is not set — add it to .env or use IMAGE_PROVIDER=local"
            )

    def generate(self, prompt: str, out_dir: str, count: int = 1) -> list[str]:
        os.makedirs(out_dir, exist_ok=True)
        paths = []
        for i in range(count):
            resp = httpx.post(
                self.API_URL,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Accept": "image/*",
                },
                files={"prompt": (None, prompt), "output_format": (None, "png")},
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
            path = os.path.join(out_dir, f"image_{i + 1}.png")
            with open(path, "wb") as fh:
                fh.write(resp.content)
            paths.append(path)
        return paths


# ── Video ─────────────────────────────────────────────────────────────


class VideoProvider(ABC):
    """Video generation backend."""

    @abstractmethod
    def generate(self, prompt: str, out_dir: str, count: int = 1) -> list[str]:
        """Generate `count` videos into `out_dir`; return the file paths."""


def write_placeholder_mp4(path: str, prompt: str) -> None:
    """Write a small but REAL playable .mp4 title card (16 frames, 8fps).

    Shared helper used by the test-suite video double; kept in the product
    because it needs no extra deps beyond the base requirements.
    """
    import imageio.v2 as imageio
    import numpy as np
    from PIL import Image, ImageDraw

    width, height, frames = 640, 360, 16
    writer = imageio.get_writer(path, fps=8, codec="libx264", quality=6)
    try:
        for frame in range(frames):
            t = frame / frames
            r = int(20 + 60 * t)
            g = int(30 + 40 * (1 - t))
            b = int(90 + 100 * t)
            img = Image.new("RGB", (width, height), (r, g, b))
            draw = ImageDraw.Draw(img)
            draw.text((24, 20), "MOCK VIDEO PLACEHOLDER", fill=(255, 255, 255))
            draw.text(
                (24, 48),
                textwrap.shorten(prompt, width=70) if prompt else "",
                fill=(200, 220, 255),
            )
            writer.append_data(np.asarray(img))
    finally:
        writer.close()


class FalAIVideo(VideoProvider):
    """fal.ai queue API: submit a job, poll its status, download the result."""

    QUEUE_URL = "https://queue.fal.run"
    MODEL = "fal-ai/fast-animatediff/text-to-video"
    MAX_POLLS = 60
    POLL_INTERVAL = 5.0

    def __init__(self) -> None:
        self._api_key = get_settings().fal_key
        if not self._api_key:
            raise RuntimeError(
                "FAL_KEY is not set — add it to .env or use VIDEO_PROVIDER=local"
            )

    def generate(self, prompt: str, out_dir: str, count: int = 1) -> list[str]:
        os.makedirs(out_dir, exist_ok=True)
        headers = {"Authorization": f"Key {self._api_key}"}
        paths = []
        for i in range(count):
            resp = httpx.post(
                f"{self.QUEUE_URL}/{self.MODEL}",
                headers=headers,
                json={"prompt": prompt},
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
            payload = resp.json()
            request_id = payload.get("request_id")
            status_url = payload.get("status_url") or (
                f"{self.QUEUE_URL}/{self.MODEL}/requests/{request_id}/status"
            )
            response_url = payload.get("response_url") or (
                f"{self.QUEUE_URL}/{self.MODEL}/requests/{request_id}"
            )
            video_url = self._poll(status_url, response_url, headers)
            video = httpx.get(video_url, timeout=_TIMEOUT)
            video.raise_for_status()
            path = os.path.join(out_dir, f"video_{i + 1}.mp4")
            with open(path, "wb") as fh:
                fh.write(video.content)
            paths.append(path)
        return paths

    def _poll(self, status_url: str, response_url: str, headers: dict) -> str:
        for _ in range(self.MAX_POLLS):
            resp = httpx.get(status_url, headers=headers, timeout=_TIMEOUT)
            resp.raise_for_status()
            status = resp.json().get("status")
            if status == "COMPLETED":
                result = httpx.get(response_url, headers=headers, timeout=_TIMEOUT)
                result.raise_for_status()
                data = result.json()
                url = (data.get("video") or {}).get("url")
                if not url:
                    raise RuntimeError(
                        f"fal.ai job completed but returned no video URL: {data!r}"
                    )
                return url
            if status in ("FAILED", "CANCELLED"):
                raise RuntimeError(f"fal.ai video generation failed: {resp.json()!r}")
            time.sleep(self.POLL_INTERVAL)
        raise RuntimeError("fal.ai video generation timed out while polling")


class KlingVideo(VideoProvider):
    """Kling text2video API: create a task, poll it, download the result."""

    API_URL = "https://api.klingai.com/v1/videos/text2video"
    MAX_POLLS = 60
    POLL_INTERVAL = 5.0

    def __init__(self) -> None:
        self._api_key = get_settings().kling_api_key
        if not self._api_key:
            raise RuntimeError(
                "KLING_API_KEY is not set — add it to .env or use VIDEO_PROVIDER=local"
            )

    def generate(self, prompt: str, out_dir: str, count: int = 1) -> list[str]:
        os.makedirs(out_dir, exist_ok=True)
        headers = {"Authorization": f"Bearer {self._api_key}"}
        paths = []
        for i in range(count):
            resp = httpx.post(
                self.API_URL,
                headers=headers,
                json={"model_name": "kling-v1", "prompt": prompt},
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
            task_id = resp.json().get("data", {}).get("task_id")
            if not task_id:
                raise RuntimeError(f"Kling returned no task id: {resp.json()!r}")
            video_url = self._poll(task_id, headers)
            video = httpx.get(video_url, timeout=_TIMEOUT)
            video.raise_for_status()
            path = os.path.join(out_dir, f"video_{i + 1}.mp4")
            with open(path, "wb") as fh:
                fh.write(video.content)
            paths.append(path)
        return paths

    def _poll(self, task_id: str, headers: dict) -> str:
        for _ in range(self.MAX_POLLS):
            resp = httpx.get(
                f"{self.API_URL}/{task_id}", headers=headers, timeout=_TIMEOUT
            )
            resp.raise_for_status()
            data = resp.json().get("data", {})
            status = data.get("task_status")
            if status == "succeed":
                videos = (data.get("task_result") or {}).get("videos") or []
                if not videos or not videos[0].get("url"):
                    raise RuntimeError(
                        f"Kling task succeeded but returned no video URL: {data!r}"
                    )
                return videos[0]["url"]
            if status == "failed":
                raise RuntimeError(
                    f"Kling video generation failed: {data.get('task_status_msg')}"
                )
            time.sleep(self.POLL_INTERVAL)
        raise RuntimeError("Kling video generation timed out while polling")


# ── kie.ai (unified media generation: images + video, one API key) ─────
#
# Async job pattern (https://kie.ai docs):
#   POST /api/v1/jobs/createTask {model, input}  -> taskId
#   GET  /api/v1/jobs/recordInfo?taskId=...      -> poll until state success
# Result payloads vary per model family, so result URLs are extracted
# defensively (any http URL ending in a media extension, anywhere in data).

_MEDIA_EXT = (".png", ".jpg", ".jpeg", ".webp", ".mp4", ".mov", ".webm")


def _find_media_urls(obj) -> list[str]:
    """Recursively collect media URLs from a kie.ai recordInfo payload."""
    urls = []
    if isinstance(obj, dict):
        for value in obj.values():
            urls.extend(_find_media_urls(value))
    elif isinstance(obj, list):
        for value in obj:
            urls.extend(_find_media_urls(value))
    elif isinstance(obj, str):
        candidate = obj.split("?")[0].lower()
        if obj.startswith("http") and candidate.endswith(_MEDIA_EXT):
            urls.append(obj)
        elif obj.strip().startswith(("{", "[")):
            try:
                urls.extend(_find_media_urls(json.loads(obj)))
            except ValueError:
                pass
    return urls


class _KieBase:
    BASE_URL = "https://api.kie.ai"
    POLL_INTERVAL = 5.0  # seconds

    def __init__(self) -> None:
        self._api_key = get_settings().kie_api_key
        if not self._api_key:
            raise RuntimeError(
                "KIE_API_KEY is not set — add it to .env or use a local provider"
            )

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._api_key}"}

    def _run_task(self, model: str, input_payload: dict, timeout_sec: float) -> list[str]:
        resp = httpx.post(
            f"{self.BASE_URL}/api/v1/jobs/createTask",
            json={"model": model, "input": input_payload},
            headers=self._headers(),
            timeout=30.0,
        )
        resp.raise_for_status()
        body = resp.json()
        task_id = (body.get("data") or {}).get("taskId")
        if not task_id:
            raise RuntimeError(f"kie.ai createTask rejected: {str(body)[:300]}")

        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            time.sleep(self.POLL_INTERVAL)
            poll = httpx.get(
                f"{self.BASE_URL}/api/v1/jobs/recordInfo",
                params={"taskId": task_id},
                headers=self._headers(),
                timeout=30.0,
            )
            poll.raise_for_status()
            data = poll.json().get("data") or {}
            state = str(data.get("state") or data.get("status") or "").lower()
            if state in ("success", "succeeded", "complete", "completed", "done"):
                urls = _find_media_urls(data)
                if urls:
                    return urls
                raise RuntimeError(
                    f"kie.ai task succeeded but no media URLs found: {str(data)[:300]}"
                )
            if state in ("fail", "failed", "error"):
                raise RuntimeError(f"kie.ai task failed: {str(data)[:300]}")
        raise RuntimeError(f"kie.ai task {task_id} timed out after {timeout_sec:.0f}s")

    def _download(self, url: str, out_dir: str, stem: str, index: int, default_ext: str) -> str:
        resp = httpx.get(url, timeout=120.0, follow_redirects=True)
        resp.raise_for_status()
        ext = os.path.splitext(url.split("?")[0])[1] or default_ext
        path = os.path.join(out_dir, f"{stem}_{index + 1}{ext}")
        with open(path, "wb") as fh:
            fh.write(resp.content)
        return path


class KieImage(_KieBase, ImageProvider):
    """kie.ai image generation (model via KIE_IMAGE_MODEL, e.g. gpt-image-1.5)."""

    def generate(self, prompt: str, out_dir: str, count: int = 1) -> list[str]:
        os.makedirs(out_dir, exist_ok=True)
        model = get_settings().kie_image_model
        urls = self._run_task(model, {"prompt": prompt, "n": count}, timeout_sec=300)
        return [
            self._download(url, out_dir, "image", i, ".png")
            for i, url in enumerate(urls[:count])
        ]


class KieVideo(_KieBase, VideoProvider):
    """kie.ai video generation (model via KIE_VIDEO_MODEL, e.g. veo3.1, kling)."""

    def generate(self, prompt: str, out_dir: str, count: int = 1) -> list[str]:
        os.makedirs(out_dir, exist_ok=True)
        model = get_settings().kie_video_model
        urls = self._run_task(model, {"prompt": prompt}, timeout_sec=600)
        return [
            self._download(url, out_dir, "video", i, ".mp4")
            for i, url in enumerate(urls[:count])
        ]


# ── Factories ─────────────────────────────────────────────────────────


def _lazy_local_image() -> ImageProvider:
    """Deferred import — local_media pulls no heavy deps at module level."""
    from src.agents.local_media import LocalDiffusionImage

    return LocalDiffusionImage()


def _lazy_local_video() -> VideoProvider:
    from src.agents.local_media import LocalDiffusionVideo

    return LocalDiffusionVideo()


_LLM_PROVIDERS = {
    "ollama": OllamaLLM,
    "openrouter": OpenRouterLLM,
    "claude": ClaudeLLM,
    "openai": OpenAILLM,
}
_IMAGE_PROVIDERS = {
    "local": _lazy_local_image,
    "kie": KieImage,
    "dalle": DallEImage,
    "stable_diffusion": StableDiffusionImage,
}
_VIDEO_PROVIDERS = {
    "local": _lazy_local_video,
    "kie": KieVideo,
    "falai": FalAIVideo,
    "kling": KlingVideo,
}

# Instances are cached per provider name so a runtime settings change
# (settings page) takes effect on the next pipeline run.
_llm_providers_cache: dict[str, LLMProvider] = {}
_llm_fallback_wrapped: dict[str, LLMProvider] = {}
_image_providers_cache: dict[str, ImageProvider] = {}
_video_providers_cache: dict[str, VideoProvider] = {}


def get_llm_provider() -> LLMProvider:
    """Return the shared LLM provider selected by the runtime setting.

    When a fallback provider is configured (``llm_fallback_provider``) and
    differs from the primary, the result is wrapped in a FallbackLLM chain.
    """
    name = runtime_settings.get_value("llm_provider")
    primary = _instantiate_llm(name)
    fallback_name = get_settings().llm_fallback_provider
    if fallback_name and fallback_name != name:
        try:
            fallback = _instantiate_llm(fallback_name)
        except Exception as exc:
            logger.warning("LLM fallback %r unusable: %s", fallback_name, exc)
        else:
            if name not in _llm_fallback_wrapped:
                _llm_fallback_wrapped[name] = FallbackLLM(primary, [fallback])
            return _llm_fallback_wrapped[name]
    return primary


def _instantiate_llm(name: str) -> LLMProvider:
    if name not in _LLM_PROVIDERS:
        raise ValueError(
            f"Unknown llm_provider {name!r}; expected one of {sorted(_LLM_PROVIDERS)}"
        )
    if name not in _llm_providers_cache:
        _llm_providers_cache[name] = _LLM_PROVIDERS[name]()
    return _llm_providers_cache[name]


def get_image_provider() -> ImageProvider:
    """Return the shared image provider selected by the runtime setting."""
    name = runtime_settings.get_value("image_provider")
    if name not in _IMAGE_PROVIDERS:
        raise ValueError(
            f"Unknown image_provider {name!r}; expected one of {sorted(_IMAGE_PROVIDERS)}"
        )
    if name not in _image_providers_cache:
        _image_providers_cache[name] = _IMAGE_PROVIDERS[name]()
    return _image_providers_cache[name]


def get_video_provider() -> VideoProvider:
    """Return the shared video provider selected by the runtime setting."""
    name = runtime_settings.get_value("video_provider")
    if name not in _VIDEO_PROVIDERS:
        raise ValueError(
            f"Unknown video_provider {name!r}; expected one of {sorted(_VIDEO_PROVIDERS)}"
        )
    if name not in _video_providers_cache:
        _video_providers_cache[name] = _VIDEO_PROVIDERS[name]()
    return _video_providers_cache[name]
