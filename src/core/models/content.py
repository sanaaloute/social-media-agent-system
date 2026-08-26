"""Generated content — one row per platform draft produced by the pipeline."""
import uuid
from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel


class GeneratedContent(SQLModel, table=True):
    __tablename__ = "generated_content"

    id: str = Field(default_factory=lambda: uuid.uuid4().hex, primary_key=True)
    task_id: str = Field(foreign_key="content_task.id", index=True)
    platform: str = Field(index=True)
    text: Optional[str] = None
    media_urls: List[str] = Field(default_factory=list, sa_column=Column(JSON))
    hashtags: List[str] = Field(default_factory=list, sa_column=Column(JSON))
    # NB: named `meta` — `metadata` is reserved by SQLAlchemy's Declarative API.
    meta: Dict = Field(default_factory=dict, sa_column=Column(JSON))
    status: str = Field(default="review", index=True)  # ApprovalStatus value
    reviewer_feedback: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    published_at: Optional[datetime] = None
    publish_result: Optional[Dict] = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=datetime.utcnow)
