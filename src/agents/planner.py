"""Planner Agent: turns research into a ContentPlan with a schedule (§3.3).

Default schedule slots each platform at now+1h, now+2h, ... (ISO-8601, UTC).
"""
import logging
from datetime import datetime, timedelta, timezone

from src.agents.providers import get_llm_provider, merge_llm_schema
from src.agents.state import AgentState
from src.core.models.schemas import ContentPlan

logger = logging.getLogger(__name__)


def planner_agent(state: AgentState) -> dict:
    topic = state.get("topic", "")
    platforms = state.get("platforms") or []
    research = state.get("research_results") or {}

    now = datetime.now(timezone.utc)
    schedule = {
        platform: (now + timedelta(hours=i + 1)).isoformat()
        for i, platform in enumerate(platforms)
    }
    defaults = {
        "angle": f"Educational angle on {topic}: {research.get('summary', '')}".strip(),
        "guidelines": (
            "Stay on-brand, one clear call-to-action per post, and match each "
            "platform's native format."
        ),
        "schedule": schedule,
    }
    llm = get_llm_provider()
    plan = merge_llm_schema(
        ContentPlan,
        defaults,
        llm.complete_json(
            system="You are a social-media content strategist.",
            prompt=(
                f"Plan a content campaign about: {topic}.\n"
                f"Target platforms: {', '.join(platforms)}.\n"
                f"Research: {research.get('summary', '')}\n"
                'Return JSON like {"angle": "...", "guidelines": "...", '
                '"schedule": {"platform": "ISO-8601 time"}}.'
            ),
        ),
    )
    return {"content_plan": plan.model_dump(), "status": "planned"}
