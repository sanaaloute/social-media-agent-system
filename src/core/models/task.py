"""Content generation task — the unit of work entering the agent pipeline."""
import uuid
from datetime import datetime
from typing import List, Optional

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel


class ContentTask(SQLModel, table=True):
    __tablename__ = "content_task"

    id: str = Field(default_factory=lambda: uuid.uuid4().hex, primary_key=True)
    brand_id: str = Field(index=True)
    platforms: List[str] = Field(default_factory=list, sa_column=Column(JSON))
    topic: str
    content_type: str = "mixed"  # ContentType value
    status: str = "pending"  # TaskStatus value
    scheduled_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
