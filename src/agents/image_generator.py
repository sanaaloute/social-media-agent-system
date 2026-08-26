"""Image Generation Agent: renders assets for drafts that need images (§3.3).

Generates one asset per platform into a per-platform subdirectory and returns
a platform -> paths dict. Skips cleanly when nothing needs images; per-platform
provider failures (missing keys, network errors) are logged and recorded in
state["error"] without failing the pipeline or other platforms.
"""
import logging

import httpx

from src.agents.providers import get_image_provider
from src.agents.state import AgentState
from src.core.config import get_settings

logger = logging.getLogger(__name__)


def image_generation_agent(state: AgentState) -> dict:
    drafts = state.get("drafts") or {}
    targets = [
        platform
        for platform, draft in drafts.items()
        if (draft or {}).get("content_type") == "image"
    ]
    if not targets:
        logger.info("No draft needs images; skipping image generation.")
        return {"images": {}}

    settings = get_settings()
    images: dict[str, list[str]] = {}
    errors: list[str] = []
    for platform in targets:
        out_dir = (
            f"{settings.media_cache_dir}/{state.get('task_id', 'unknown')}/{platform}"
        )
        text = (drafts[platform] or {}).get("text") or state.get("topic", "")
        prompt = f"Social media image for {platform}: {text}"
        try:
            images[platform] = get_image_provider().generate(prompt, out_dir, count=1)
        except (RuntimeError, httpx.HTTPError) as exc:  # missing key, network, etc.
            logger.warning("Image generation failed for %s: %s", platform, exc)
            errors.append(f"{platform}: {exc}")
    result: dict = {"images": images, "status": "images_done"}
    if errors:
        result["error"] = "; ".join(errors)
    return result
