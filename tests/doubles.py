"""Test doubles for the generation providers.

The product ships no mock providers (real local models are the default);
these lightweight stubs exist only so the test suite can run offline,
without a GPU or API keys. They are injected into the provider registries
under the name "mock" by conftest — a name that does not exist in the
product itself.
"""
import hashlib
import os
import textwrap

from PIL import Image, ImageDraw

from src.agents.providers import (
    ImageProvider,
    LLMProvider,
    VideoProvider,
    write_placeholder_mp4,
)


class StubLLM(LLMProvider):
    """Empty completions — pipeline nodes use their deterministic defaults."""

    def complete(self, system: str, prompt: str) -> str:
        return ""

    def complete_json(self, system: str, prompt: str) -> dict:
        return {}


class StubImage(ImageProvider):
    """Deterministic real PNG (solid colour + prompt text) without a GPU."""

    def generate(self, prompt: str, out_dir: str, count: int = 1) -> list[str]:
        os.makedirs(out_dir, exist_ok=True)
        digest = hashlib.md5((prompt or "").encode("utf-8")).hexdigest()
        background = (int(digest[0:2], 16), int(digest[2:4], 16), int(digest[4:6], 16))
        paths = []
        for i in range(count):
            img = Image.new("RGB", (1080, 1080), background)
            draw = ImageDraw.Draw(img)
            y = 60
            for line in ["STUB IMAGE", ""] + textwrap.wrap(prompt or "no prompt", 60)[:48]:
                draw.text((60, y), line, fill=(255, 255, 255))
                y += 16
            path = os.path.join(out_dir, f"image_{i + 1}.png")
            img.save(path, "PNG")
            paths.append(path)
        return paths


class StubVideo(VideoProvider):
    """Small real playable mp4 title card without a GPU."""

    def generate(self, prompt: str, out_dir: str, count: int = 1) -> list[str]:
        os.makedirs(out_dir, exist_ok=True)
        paths = []
        for i in range(count):
            path = os.path.join(out_dir, f"video_{i + 1}.mp4")
            write_placeholder_mp4(path, prompt)
            paths.append(path)
        return paths
