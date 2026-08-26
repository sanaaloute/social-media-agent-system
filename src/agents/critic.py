"""Critic Agent: scores the drafts into a QualityReport (§3.3).

Default logic is deterministic: approved with score 0.9 when every draft has
non-empty text, otherwise rejected with per-platform issues. A real LLM may
override any field via complete_json.
"""
import json
import logging

from src.agents.providers import get_llm_provider, merge_llm_schema
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
    revision = state.get("revision_count", 0)
    revision_note = (
        f"\nThis is revision round {revision} of previously rejected drafts "
        "— be strict about whether the feedback was actually addressed."
        if revision
        else ""
    )
    report = merge_llm_schema(
        QualityReport,
        defaults,
        llm.complete_json(
            system="You are a strict social-media content-quality reviewer.",
            prompt=(
                "Review these platform drafts and return JSON like "
                '{"approved": true, "score": 0.0-1.0, "issues": ["..."], '
                '"feedback": "..."}.' + revision_note + "\nDrafts:\n"
                + json.dumps(drafts, ensure_ascii=False)[:4000]
            ),
        ),
    )
    return {"quality_report": report.model_dump(), "status": "critiqued"}
