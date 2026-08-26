"""Local diffusion providers — image/video generation on the local GPU (§3.4).

These providers run open models on the machine's own GPU (no API keys, no
cloud). Ollama cannot do this on Windows (its experimental image generation
is macOS-only, and it has no video support), so we use HuggingFace
`diffusers` directly:

- Image: SDXL-Turbo by default (~2s/image on an RTX 4090)
- Video: Wan2.1-T2V-1.3B by default (small enough for 16GB with CPU offload;
  expect minutes per short clip — dev/testing grade)

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


def _device(torch) -> str:
    return "cuda" if torch.cuda.is_available() else "cpu"


class LocalDiffusionImage(ImageProvider):
    """Text-to-image on the local GPU via diffusers (default SDXL-Turbo)."""

    def __init__(self) -> None:
        self._model_id = get_settings().local_image_model

    def _pipe(self):
        if "image" not in _pipes:
            torch, diffusers = _load_torch()
            device = _device(torch)
            dtype = torch.float16 if device == "cuda" else torch.float32
            logger.info("loading local image model %s on %s", self._model_id, device)
            pipe = diffusers.AutoPipelineForText2Image.from_pretrained(
                self._model_id, torch_dtype=dtype, variant="fp16" if device == "cuda" else None
            )
            pipe.to(device)
            _pipes["image"] = pipe
        return _pipes["image"]

    def generate(self, prompt: str, out_dir: str, count: int = 1) -> list[str]:
        os.makedirs(out_dir, exist_ok=True)
        pipe = self._pipe()
        # SDXL-Turbo needs 1-4 steps and no guidance; other models get a
        # sensible default — cheap to override later per model.
        turbo = "turbo" in self._model_id.lower()
        kwargs = (
            {"num_inference_steps": 2, "guidance_scale": 0.0}
            if turbo
            else {"num_inference_steps": 25, "guidance_scale": 7.5}
        )
        paths = []
        for i in range(count):
            image = pipe(prompt, **kwargs).images[0]
            path = os.path.join(out_dir, f"image_{i + 1}.png")
            image.save(path)
            paths.append(path)
        return paths


class LocalDiffusionVideo(VideoProvider):
    """Text-to-video on the local GPU via diffusers (default Wan2.1-1.3B).

    Short clips only (dev/testing grade): 16 frames @8fps ≈ 2s of video,
    minutes of compute with CPU offload on a 16GB card.
    """

    def __init__(self) -> None:
        self._model_id = get_settings().local_video_model

    def _pipe(self):
        if "video" not in _pipes:
            torch, diffusers = _load_torch()
            if not torch.cuda.is_available():
                raise RuntimeError(
                    "Local video generation needs a CUDA GPU; use the mock or "
                    "kie provider on CPU."
                )
            logger.info("loading local video model %s", self._model_id)
            pipe = diffusers.WanPipeline.from_pretrained(
                self._model_id, torch_dtype=torch.bfloat16
            )
            pipe.enable_model_cpu_offload()  # fits a 16GB card
            _pipes["video"] = pipe
        return _pipes["video"]

    def generate(self, prompt: str, out_dir: str, count: int = 1) -> list[str]:
        os.makedirs(out_dir, exist_ok=True)
        pipe = self._pipe()
        from diffusers.utils import export_to_video

        paths = []
        for i in range(count):
            frames = pipe(
                prompt,
                num_frames=16,
                num_inference_steps=20,
                guidance_scale=5.0,
            ).frames[0]
            path = os.path.join(out_dir, f"video_{i + 1}.mp4")
            export_to_video(frames, path, fps=8)
            paths.append(path)
        return paths
