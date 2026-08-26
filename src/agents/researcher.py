"""Researcher Agent: turns the task topic into a TrendReport (§3.3).

With the mock LLM the deterministic defaults are used as-is; a real LLM may
override any subset of fields via complete_json.
"""
import logging

from src.agents.providers import get_llm_provider
from src.agents.state import AgentState
from src.core.models.schemas import TrendReport

logger = logging.getLogger(__name__)


def researcher_agent(state: AgentState) -> dict:
    topic = state.get("topic", "")
    defaults = {
        "topics": [topic, f"{topic} trends", f"{topic} tips"],
        "hashtags": ["#trending", "#socialmedia", "#viral"],
        "summary": (
            f"Audience interest in '{topic}' is steady; practical, visual "
            "content performs best right now."
        ),
    }
    llm = get_llm_provider()
    data = defaults | llm.complete_json(
        system="You are a social-media trend researcher.",
        prompt=(
            f"Research current trends for the topic: {topic}.\n"
            'Return JSON like {"topics": ["..."], "hashtags": ["#..."], '
            '"summary": "..."}.'
        ),
    )
    data = {k: v for k, v in data.items() if k in TrendReport.model_fields}
    report = TrendReport(**data)
    return {"research_results": report.model_dump(), "status": "researched"}
