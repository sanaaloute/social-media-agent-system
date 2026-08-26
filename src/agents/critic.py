"""Critic Agent: scores the drafts into a QualityReport (§3.3).

Default logic is deterministic: approved with score 0.9 when every draft has
non-empty text, otherwise rejected with per-platform issues. A real LLM may
override any field via complete_json.
"""
import json
import logging

from src.agents.providers import get_llm_provider
from src.agents.state import AgentState
from src.core.models.schemas import QualityReport

logger = logging.getLogger(__name__)


def critic_agent(state: AgentState) -> dict:
    drafts = state.get("drafts") or {}
    empty = sorted(
        platform
        for platform, draft in drafts.items()
        if not str((draft or {}).get("text") or "").strip()
    )
    if not drafts:
        defaults = {
            "approved": False,
            "score": 0.0,
            "issues": ["no drafts were produced"],
            "feedback": "Produce at least one platform draft.",
        }
    elif empty:
        defaults = {
            "approved": False,
            "score": 0.3,
            "issues": [f"{p}: draft text is empty" for p in empty],
            "feedback": "Rewrite the empty drafts with substantive, on-topic text.",
        }
    else:
        defaults = {
            "approved": True,
            "score": 0.9,
            "issues": [],
            "feedback": "Drafts are on-topic and platform-appropriate.",
        }
    llm = get_llm_provider()
    data = defaults | llm.complete_json(
        system="You are a strict social-media content-quality reviewer.",
        prompt=(
            "Review these platform drafts and return JSON like "
            '{"approved": true, "score": 0.0-1.0, "issues": ["..."], '
            '"feedback": "..."}.\nDrafts:\n'
            + json.dumps(drafts, ensure_ascii=False)[:4000]
        ),
    )
    data = {k: v for k, v in data.items() if k in QualityReport.model_fields}
    report = QualityReport(**data)
    return {"quality_report": report.model_dump(), "status": "critiqued"}
