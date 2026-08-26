"""Typed payloads passed between agents inside the LangGraph state (§3.2)."""
from typing import Dict, List

from pydantic import BaseModel, Field


class TrendReport(BaseModel):
    """Research Agent output."""

    topics: List[str] = Field(default_factory=list)
    hashtags: List[str] = Field(default_factory=list)
    summary: str = ""


class ContentPlan(BaseModel):
    """Planner Agent output."""

    angle: str = ""
    guidelines: str = ""
    # platform -> ISO-8601 scheduled time
    schedule: Dict[str, str] = Field(default_factory=dict)


class PlatformDraft(BaseModel):
    """Writer Agent output, one per platform."""

    platform: str
    text: str = ""
    hashtags: List[str] = Field(default_factory=list)
    content_type: str = "text"  # ContentType value


class QualityReport(BaseModel):
    """Critic Agent output."""

    approved: bool = False
    score: float = 0.0  # 0..1
    issues: List[str] = Field(default_factory=list)
    feedback: str = ""
