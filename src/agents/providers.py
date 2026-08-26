"""Generation providers: LLM / image / video backends (design doc §3.4).

`mock` providers are deterministic and keyless, and are the defaults so the
pipeline runs end-to-end with zero credentials. Real providers are plain sync
httpx calls — no langchain-* packages involved.
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

from src.core import runtime_settings
from src.core.config import get_settings

logger = logging.getLogger(__name__)

_TIMEOUT = 60.0
_JSON_INSTRUCTION = "Respond with a single JSON object only."


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


# ── LLM ───────────────────────────────────────────────────────────────


class LLMProvider(ABC):
    """Text completion backend."""

    @abstractmethod
    def complete(self, system: str, prompt: str) -> str:
        """Return a free-text completion."""

    def complete_json(self, system: str, prompt: str) -> dict:
        """Return a JSON object completion; {} on any parse failure."""
        raw = self.complete(system, f"{prompt}\n\n{_JSON_INSTRUCTION}")
        return _extract_json(raw)


class MockLLM(LLMProvider):
    """Deterministic, keyless provider (the default)."""

    def complete(self, system: str, prompt: str) -> str:
        excerpt = " ".join((prompt or "").split()[:12])
        return f"[mock-llm] completion for: {excerpt}"

    def complete_json(self, system: str, prompt: str) -> dict:
        # {} makes nodes fall back to their deterministic defaults.
        return {}


class ClaudeLLM(LLMProvider):
    """Anthropic Messages API."""

    API_URL = "https://api.anthropic.com/v1/messages"
    MODEL = "claude-sonnet-4-20250514"

    def __init__(self) -> None:
        self._api_key = get_settings().anthropic_api_key
        if not self._api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set — add it to .env or use LLM_PROVIDER=mock"
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
                "OPENAI_API_KEY is not set — add it to .env or use LLM_PROVIDER=mock"
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
    """Local Ollama chat API (no key required)."""

    MODEL = "llama3.1"

    def __init__(self) -> None:
        self._base_url = get_settings().ollama_base_url.rstrip("/")

    def complete(self, system: str, prompt: str) -> str:
        resp = httpx.post(
            f"{self._base_url}/api/chat",
            json={
                "model": self.MODEL,
                "stream": False,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
            },
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json().get("message", {}).get("content", "")


# ── Images ────────────────────────────────────────────────────────────


class ImageProvider(ABC):
    """Image generation backend."""

    @abstractmethod
    def generate(self, prompt: str, out_dir: str, count: int = 1) -> list[str]:
        """Generate `count` images into `out_dir`; return the file paths."""


class MockImage(ImageProvider):
    """Renders a deterministic 1080x1080 placeholder PNG with Pillow."""

    def generate(self, prompt: str, out_dir: str, count: int = 1) -> list[str]:
        os.makedirs(out_dir, exist_ok=True)
        digest = hashlib.md5((prompt or "").encode("utf-8")).hexdigest()
        background = (int(digest[0:2], 16), int(digest[2:4], 16), int(digest[4:6], 16))
        paths = []
        for i in range(count):
            img = Image.new("RGB", (1080, 1080), background)
            draw = ImageDraw.Draw(img)
            lines = ["MOCK IMAGE", ""] + textwrap.wrap(prompt or "no prompt", 60)
            y = 60
            for line in lines[:50]:  # default bitmap font ~11px tall
                draw.text((60, y), line, fill=(255, 255, 255))
                y += 16
            path = os.path.join(out_dir, f"image_{i + 1}.png")
            img.save(path, "PNG")
            paths.append(path)
        return paths


class DallEImage(ImageProvider):
    """OpenAI Images API (dall-e-3, b64 payload saved to disk)."""

    API_URL = "https://api.openai.com/v1/images/generations"
    MODEL = "dall-e-3"

    def __init__(self) -> None:
        self._api_key = get_settings().openai_api_key
        if not self._api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is not set — add it to .env or use IMAGE_PROVIDER=mock"
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
                "STABILITY_API_KEY is not set — add it to .env or use IMAGE_PROVIDER=mock"
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


class MockVideo(VideoProvider):
    """Writes a small placeholder .mp4 (a text notice, not a real video)."""

    def generate(self, prompt: str, out_dir: str, count: int = 1) -> list[str]:
        os.makedirs(out_dir, exist_ok=True)
        paths = []
        for i in range(count):
            path = os.path.join(out_dir, f"video_{i + 1}.mp4")
            notice = (
                "MOCK VIDEO PLACEHOLDER — not a playable video file.\n"
                f"prompt: {prompt}\n"
            )
            with open(path, "wb") as fh:
                fh.write(notice.encode("utf-8"))
            paths.append(path)
        return paths


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
                "FAL_KEY is not set — add it to .env or use VIDEO_PROVIDER=mock"
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
                "KLING_API_KEY is not set — add it to .env or use VIDEO_PROVIDER=mock"
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


# ── Factories ─────────────────────────────────────────────────────────

_LLM_PROVIDERS = {
    "mock": MockLLM,
    "claude": ClaudeLLM,
    "openai": OpenAILLM,
    "ollama": OllamaLLM,
}
_IMAGE_PROVIDERS = {
    "mock": MockImage,
    "dalle": DallEImage,
    "stable_diffusion": StableDiffusionImage,
}
_VIDEO_PROVIDERS = {
    "mock": MockVideo,
    "falai": FalAIVideo,
    "kling": KlingVideo,
}

# Instances are cached per provider name so a runtime settings change
# (settings page) takes effect on the next pipeline run.
_llm_providers_cache: dict[str, LLMProvider] = {}
_image_providers_cache: dict[str, ImageProvider] = {}
_video_providers_cache: dict[str, VideoProvider] = {}


def get_llm_provider() -> LLMProvider:
    """Return the shared LLM provider selected by the runtime setting."""
    name = runtime_settings.get_value("llm_provider")
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
