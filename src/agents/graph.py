"""LangGraph workflow wiring for the generation pipeline (design doc §3.3).

Flow: researcher -> planner -> writer -> image_gen -> video_gen -> critic,
then should_publish gates to the publisher (approved) or back to the writer
via a revision-counting passthrough (rejected). The publisher only packages
content for human review — publishing itself happens after HITL approval.

Every node runs inside a logging wrapper (structured per-node start/end/
duration records), so one pipeline run is traceable end-to-end in the logs.
"""
import logging
import sqlite3
import time
from functools import wraps

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.agents.critic import critic_agent
from src.agents.image_generator import image_generation_agent
from src.agents.planner import planner_agent
from src.agents.researcher import researcher_agent
from src.agents.state import AgentState
from src.agents.video_generator import video_generation_agent
from src.agents.writer import writer_agent
from src.core.config import get_settings

logger = logging.getLogger(__name__)

MAX_REVISIONS = 3


def _logged_node(name: str, fn):
    """Structured per-node logging: start, outcome, duration, errors."""

    @wraps(fn)
    def wrapper(state: AgentState) -> dict:
        task_id = state.get("task_id", "?")
        revision = state.get("revision_count", 0)
        logger.info("[node:%s] start task=%s rev=%d", name, task_id, revision)
        started = time.monotonic()
        try:
            update = fn(state)
        except Exception:
            logger.exception(
                "[node:%s] FAILED task=%s after %.0fms",
                name, task_id, (time.monotonic() - started) * 1000,
            )
            raise
        duration_ms = (time.monotonic() - started) * 1000
        status = (update or {}).get("status", "")
        error = (update or {}).get("error")
        if error:
            logger.warning(
                "[node:%s] done task=%s in %.0fms status=%s error=%s",
                name, task_id, duration_ms, status, error,
            )
        else:
            logger.info(
                "[node:%s] done task=%s in %.0fms status=%s",
                name, task_id, duration_ms, status,
            )
        return update

    return wrapper


def should_publish(state: AgentState) -> str:
    """Route after the critic: 'approved' or 'rejected' (revision-capped)."""
    report = state.get("quality_report") or {}
    if report.get("approved"):
        return "approved"
    if state.get("revision_count", 0) >= MAX_REVISIONS:
        logger.warning(
            "Revision cap (%d) reached for task %s; approving latest drafts as-is.",
            MAX_REVISIONS,
            state.get("task_id"),
        )
        return "approved"
    return "rejected"


def revise_node(state: AgentState) -> dict:
    """Passthrough on the rejected edge: counts one more revision cycle."""
    return {"revision_count": state.get("revision_count", 0) + 1}


def publisher_node(state: AgentState) -> dict:
    """Package approved content for human review (HITL — does NOT publish)."""
    approved_content = {
        "drafts": state.get("drafts") or {},
        "images": state.get("images") or {},
        "videos": state.get("videos") or {},
    }
    return {"approved_content": approved_content, "status": "awaiting_approval"}


def _build_checkpointer():
    """SqliteSaver on settings.checkpoint_db; None (with a warning) on failure."""
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver
    except ImportError:
        logger.warning(
            "langgraph-checkpoint-sqlite is not installed; "
            "compiling without a checkpointer."
        )
        return None
    try:
        conn = sqlite3.connect(get_settings().checkpoint_db, check_same_thread=False)
        saver = SqliteSaver(conn)
        setup = getattr(saver, "setup", None)
        if callable(setup):
            setup()
        return saver
    except Exception:
        logger.exception(
            "Failed to initialise SqliteSaver; compiling without a checkpointer."
        )
        return None


def create_workflow(checkpointer: bool = False) -> CompiledStateGraph:
    """Build and compile the generation graph.

    Compiles without persistence by default; pass checkpointer=True to
    checkpoint state into settings.checkpoint_db via SqliteSaver.
    """
    workflow = StateGraph(AgentState)
    workflow.add_node("researcher", _logged_node("researcher", researcher_agent))
    workflow.add_node("planner", _logged_node("planner", planner_agent))
    workflow.add_node("writer", _logged_node("writer", writer_agent))
    workflow.add_node("image_gen", _logged_node("image_gen", image_generation_agent))
    workflow.add_node("video_gen", _logged_node("video_gen", video_generation_agent))
    workflow.add_node("critic", _logged_node("critic", critic_agent))
    workflow.add_node("revise", revise_node)
    workflow.add_node("publisher", _logged_node("publisher", publisher_node))

    workflow.set_entry_point("researcher")
    workflow.add_edge("researcher", "planner")
    workflow.add_edge("planner", "writer")
    workflow.add_edge("writer", "image_gen")
    workflow.add_edge("image_gen", "video_gen")
    workflow.add_edge("video_gen", "critic")
    workflow.add_conditional_edges(
        "critic",
        should_publish,
        {"approved": "publisher", "rejected": "revise"},
    )
    workflow.add_edge("revise", "writer")
    workflow.add_edge("publisher", END)

    saver = _build_checkpointer() if checkpointer else None
    return workflow.compile(checkpointer=saver)
