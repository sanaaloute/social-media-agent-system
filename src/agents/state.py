"""Shared LangGraph state threaded through the agent pipeline (design doc §3.1).

All keys are optional (total=False) so nodes only ever set what they produce;
pydantic payloads from src.core.models.schemas are stored as plain dicts.
"""
from typing import TypedDict


class AgentState(TypedDict, total=False):
    task_id: str
    brand_context: dict
    topic: str
    platforms: list[str]
    research_results: dict | None  # TrendReport as dict
    content_plan: dict | None  # ContentPlan as dict
    drafts: dict | None  # platform -> PlatformDraft as dict
    images: dict[str, list[str]] | None  # platform -> generated image file paths
    videos: dict[str, list[str]] | None  # platform -> generated video file paths
    quality_report: dict | None  # QualityReport as dict
    approved_content: dict | None  # packaged by the publisher node (HITL gate)
    publish_results: dict | None
    error: str | None
    status: str
    revision_count: int
