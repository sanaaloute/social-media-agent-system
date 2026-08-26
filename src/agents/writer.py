"""Writer Agent: drafts one PlatformDraft per target platform (§3.3).

Drafts are templated deterministically per platform (length, hashtag count,
tone); a real LLM may override text/hashtags via complete_json. When the
critic rejected a previous attempt its feedback is folded into the prompt.
A task-level content_type of text/image/video forces every draft to that
type; "mixed" keeps the per-platform default mapping.
"""
import logging

from src.agents.providers import get_llm_provider, merge_llm_schema
from src.agents.state import AgentState
from src.core.models.schemas import PlatformDraft

logger = logging.getLogger(__name__)

# platform -> (max chars, hashtag count, tone note)
_PLATFORM_STYLE = {
    "twitter": (280, 2, "short and punchy"),
    "linkedin": (1300, 3, "professional and insightful"),
    "instagram": (2200, 5, "visual and upbeat"),
    "facebook": (1500, 3, "friendly and conversational"),
    "tiktok": (300, 4, "playful and trend-aware"),
    "youtube": (1000, 3, "descriptive and keyword-rich"),
}
_DEFAULT_STYLE = (1000, 3, "engaging")

# platforms whose drafts need media assets by default
_PLATFORM_CONTENT_TYPE = {
    "instagram": "image",
    "tiktok": "video",
    "youtube": "video",
}


def _default_hashtags(topic: str, count: int) -> list[str]:
    slug = "#" + "".join((topic or "content").lower().split())[:20]
    generic = ["#socialmedia", "#marketing", "#trending", "#contentcreator"]
    return ([slug] + generic)[: max(count, 1)]


def writer_agent(state: AgentState) -> dict:
    topic = state.get("topic", "")
    platforms = state.get("platforms") or []
    plan = state.get("content_plan") or {}
    research = state.get("research_results") or {}
    feedback = (state.get("quality_report") or {}).get("feedback") or ""
    task_type = (state.get("brand_context") or {}).get("content_type", "mixed")
    forced_type = task_type if task_type in ("text", "image", "video") else None
    llm = get_llm_provider()

    drafts = {}
    brand = state.get("brand_context") or {}
    niche = brand.get("niche") or ""
    brand_tone = brand.get("tone") or ""
    for platform in platforms:
        max_chars, tag_count, tone = _PLATFORM_STYLE.get(platform, _DEFAULT_STYLE)
        content_type = forced_type or _PLATFORM_CONTENT_TYPE.get(platform, "text")
        angle = plan.get("angle") or f"Fresh take on {topic}"
        summary = research.get("summary") or f"Insights about {topic}."
        defaults = {
            "platform": platform,
            "text": f"{angle}\n\n{summary}\n\nTone: {tone}."[:max_chars],
            "hashtags": _default_hashtags(topic, tag_count),
            "content_type": content_type,
        }
        prompt = (
            f"Write a {platform} post about: {topic}.\n"
            f"Angle: {angle}\n"
            f"Guidelines: {plan.get('guidelines', '')}\n"
            f"Research summary: {summary}\n"
            f"Niche: {niche or 'general'}. Brand tone: {brand_tone or 'neutral'}.\n"
            f"Constraints: {tone} tone; max {max_chars} characters; "
            f"exactly {tag_count} hashtags; content_type {content_type}.\n"
            'Return JSON like {"text": "...", "hashtags": ["#..."], '
            '"content_type": "..."}.'
        )
        if feedback:
            prompt += f"\n\nRevision feedback to address: {feedback}"
        draft = merge_llm_schema(
            PlatformDraft,
            defaults,
            llm.complete_json(
                system="You are a social-media copywriter.", prompt=prompt
            ),
        )
        draft = draft.model_copy(update={"platform": platform})
        if forced_type:  # task-level request wins over any LLM override
            draft = draft.model_copy(update={"content_type": forced_type})
        drafts[platform] = draft.model_dump()
    return {"drafts": drafts, "status": "drafted"}
