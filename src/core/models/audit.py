"""Audit log — every review/publish state transition is recorded (§5.3.5)."""
from datetime import datetime
from typing import Dict, Optional

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel


class AuditLog(SQLModel, table=True):
    __tablename__ = "audit_log"

    id: Optional[int] = Field(default=None, primary_key=True)
    actor: str = "system"  # reviewer name or "system"
    action: str  # e.g. approve | reject | modify | publish | publish_failed
    content_id: Optional[str] = Field(default=None, index=True)
    task_id: Optional[str] = Field(default=None, index=True)
    detail: Dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=datetime.utcnow)
