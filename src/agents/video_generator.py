"""Video Generation Agent: renders assets for drafts that need video (§3.3).

Same contract as the image agent: one asset per platform into a per-platform
subdirectory, returned as a platform -> paths dict; per-platform provider
failures degrade to a skipped platform plus a state["error"] note.
"""
import logging

import httpx

from src.agents.providers import get_video_provider
from src.agents.state import AgentState
from src.core.config import get_settings

logger = logging.getLogger(__name__)


def video_generation_agent(state: AgentState) -> dict:
    drafts = state.get("drafts") or {}
    targets = [
        platform
        for platform, draft in drafts.items()
        if (draft or {}).get("content_type") == "video"
    ]
    if not targets:
        logger.info("No draft needs video; skipping video generation.")
        return {"videos": {}}

    settings = get_settings()
    videos: dict[str, list[str]] = {}
    errors: list[str] = []
    for platform in targets:
        out_dir = (
            f"{settings.media_cache_dir}/{state.get('task_id', 'unknown')}/{platform}"
        )
        text = (drafts[platform] or {}).get("text") or state.get("topic", "")
        prompt = f"Short social media video for {platform}: {text}"
        try:
            videos[platform] = get_video_provider().generate(prompt, out_dir, count=1)
        except (RuntimeError, httpx.HTTPError) as exc:  # missing key, network, etc.
            logger.warning("Video generation failed for %s: %s", platform, exc)
            errors.append(f"{platform}: {exc}")
    result: dict = {"videos": videos, "status": "videos_done"}
    if errors:
        result["error"] = "; ".join(errors)
    return result
