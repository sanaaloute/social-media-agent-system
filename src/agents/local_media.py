"""Local diffusion providers — image/video generation on the local GPU (§3.4).

These providers run open models on the machine's own GPU (no API keys, no
cloud). Ollama cannot do this on Windows (its experimental image generation
is macOS-only, and it has no video support), so we use HuggingFace
`diffusers` directly:

- Image: SDXL-Turbo by default (~2s/image on an RTX 4090)
- Video: Wan2.1-T2V-1.3B by default (small enough for 16GB with CPU offload)

Heavy dependencies (torch, diffusers) are OPTIONAL and imported lazily:
`pip install -r requirements-local.txt`. Without them the providers raise a
clear RuntimeError telling the user how to enable them — the rest of the
system is unaffected.
"""
import logging
import os

from src.agents.providers import ImageProvider, VideoProvider
from src.core.config import get_settings

logger = logging.getLogger(__name__)

_pipes: dict = {}


def _load_torch():
    try:
        import torch  # noqa: F401
        import diffusers  # noqa: F401
    except ImportError:
        raise RuntimeError(
            "Local diffusion needs optional dependencies — run "
            "`pip install -r requirements-local.txt` (torch + diffusers), "
            "or pick another provider in Settings."
        ) from None
    return torch, diffusers


def _device_and_dtype(torch):
    """cuda (NVIDIA) -> mps (Apple Silicon) -> cpu, best available first."""
    if torch.cuda.is_available():
        return "cuda", torch.float16
    mps = getattr(torch.backends, "mps", None)
    if mps is not None and mps.is_available():
        return "mps", torch.float16
    return "cpu", torch.float32


class LocalDiffusionImage(ImageProvider):
    """Text-to-image on the local GPU via diffusers.

    Per-model presets: SDXL-Turbo (2 steps), Z-Image-Turbo (9 steps, bf16),
    everything else (25 steps). Model id comes from ``local_image_model``.
    """

    def __init__(self) -> None:
        self._model_id = get_settings().local_image_model

    def _pipe(self):
        if "image" not in _pipes:
            torch, diffusers = _load_torch()
            device, dtype = _device_and_dtype(torch)
            model = self._model_id.lower()
            load_kwargs = {"torch_dtype": dtype}
            if "z-image" in model:
                # Z-Image wants bfloat16 and has no fp16 variant checkpoint.
                load_kwargs["torch_dtype"] = torch.bfloat16
            elif device != "cpu":
                load_kwargs["variant"] = "fp16"
            logger.info("loading local image model %s on %s", self._model_id, device)
            pipe = diffusers.AutoPipelineForText2Image.from_pretrained(
                self._model_id,
                **load_kwargs,
            )
            if "z-image" in model:
                # Z-Image-Turbo is ~25GB (DiT + Qwen3 encoder) — naive full-GPU
                # loading OOM-crashes a 16GB card. Offload keeps it workable
                # (slower, but stable). Verified: naive .to("cuda") hard-crashes.
                pipe.enable_model_cpu_offload()
            else:
                pipe.to(device)
            _pipes["image"] = pipe
        return _pipes["image"]

    def generate(self, prompt: str, out_dir: str, count: int = 1) -> list[str]:
        os.makedirs(out_dir, exist_ok=True)
        pipe = self._pipe()
        model = self._model_id.lower()
        if "z-image" in model and "turbo" in model:
            kwargs = {"num_inference_steps": 9, "guidance_scale": 0.0}
        elif "turbo" in model:  # SDXL-Turbo
            kwargs = {"num_inference_steps": 2, "guidance_scale": 0.0}
        else:
            kwargs = {"num_inference_steps": 25, "guidance_scale": 7.5}
        paths = []
        for i in range(count):
            image = pipe(prompt, **kwargs).images[0]
            path = os.path.join(out_dir, f"image_{i + 1}.png")
            image.save(path)
            paths.append(path)
        return paths


class LocalDiffusionVideo(VideoProvider):
    """Text-to-video on the local GPU via diffusers (default Wan2.1-1.3B).

    Wan's native window is 81 frames @16fps (~5s). Longer clips
    (``local_video_seconds``) are produced by SEGMENT CHAINING: consecutive
    windows are generated with continuation wording and concatenated into a
    single mp4. Expect roughly 2-4 minutes of GPU time per 5s segment on a
    16GB card (CPU offload) — a 60s clip is ~12 segments, and visual drift
    accumulates across segments. Fine for dev/testing; use kie.ai (Veo /
    Kling) for production-grade long clips.
    """

    FPS = 16
    FRAMES_PER_SEGMENT = 81  # Wan constraint: num_frames - 1 divisible by 4

    def __init__(self) -> None:
        self._model_id = get_settings().local_video_model

    def _pipe(self):
        if "video" not in _pipes:
            torch, diffusers = _load_torch()
            device, dtype = _device_and_dtype(torch)
            if device == "cpu":
                raise RuntimeError(
                    "Local video generation needs a GPU (CUDA or Apple "
                    "Silicon MPS); use the kie provider on CPU."
                )
            logger.info("loading local video model %s on %s", self._model_id, device)
            pipe = diffusers.WanPipeline.from_pretrained(
                self._model_id, torch_dtype=dtype
            )
            if device == "cuda":
                pipe.enable_model_cpu_offload()  # fits a 16GB card
            else:
                # Apple Silicon unified memory (32GB) holds the whole model.
                pipe.to(device)
            _pipes["video"] = pipe
        return _pipes["video"]

    def _segment_count(self, target_seconds: int) -> int:
        segment_seconds = (self.FRAMES_PER_SEGMENT - 1) // self.FPS  # 5
        return max(1, -(-target_seconds // segment_seconds))  # ceil

    def generate(self, prompt: str, out_dir: str, count: int = 1) -> list[str]:
        os.makedirs(out_dir, exist_ok=True)
        pipe = self._pipe()
        from diffusers.utils import export_to_video

        from src.core import runtime_settings

        target = runtime_settings.get_value("local_video_seconds")
        segments = self._segment_count(target)
        if segments > 1:
            logger.info(
                "local video: target %ds -> %d chained segments (~5s each)",
                target, segments,
            )

        torch, _ = _load_torch()
        paths = []
        for i in range(count):
            all_frames = []
            for s in range(segments):
                seg_prompt = (
                    prompt
                    if s == 0
                    else f"{prompt} — same scene, the action continues"
                )
                generator = torch.Generator().manual_seed(
                    hash((prompt, i, s)) % (2**31)
                )
                frames = pipe(
                    seg_prompt,
                    num_frames=self.FRAMES_PER_SEGMENT,
                    num_inference_steps=20,
                    guidance_scale=5.0,
                    generator=generator,
                ).frames[0]
                if s > 0:
                    frames = frames[1:]  # drop the seam frame between segments
                all_frames.extend(frames)
            path = os.path.join(out_dir, f"video_{i + 1}.mp4")
            export_to_video(all_frames, path, fps=self.FPS)
            paths.append(path)
        return paths
