"""Task routes — create content tasks and inspect them (§9.1)."""
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from src.core.database.engine import get_session
from src.core.models import Brand, ContentTask, ContentType
from src.publishers import validate_platforms
from src.services import content_service

router = APIRouter(prefix="/tasks", tags=["tasks"])


class TaskCreate(BaseModel):
    brand_id: Optional[str] = None
    platforms: List[str]
    topic: Optional[str] = None  # empty + brand -> agent discovers hot topics
    content_type: str = "mixed"
    scheduled_at: Optional[datetime] = None


@router.post("", status_code=201, response_model=ContentTask)
def create_task(payload: TaskCreate, session: Session = Depends(get_session)):
    """Create a task and dispatch the generation pipeline (§3.1).

    Either an explicit ``topic`` or a ``brand_id`` (whose niche guides
    hot-topic discovery) is required.
    """
    try:
        platforms = validate_platforms(payload.platforms)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not platforms:
        raise HTTPException(status_code=400, detail="At least one platform is required")

    topic = (payload.topic or "").strip()
    if payload.brand_id:
        if session.get(Brand, payload.brand_id) is None:
            raise HTTPException(404, f"Brand {payload.brand_id!r} not found")
    elif not topic:
        raise HTTPException(400, "Provide a topic or a brand_id for guided discovery")

    valid_types = {ct.value for ct in ContentType}
    if payload.content_type not in valid_types:
        raise HTTPException(
            400, f"Invalid content_type {payload.content_type!r}; expected one of {sorted(valid_types)}"
        )

    task = content_service.create_task(
        session,
        brand_id=payload.brand_id or "",
        platforms=platforms,
        topic=topic,
        content_type=payload.content_type,
        scheduled_at=payload.scheduled_at,
    )
    content_service.dispatch_generation(task.id)
    return task


@router.get("", response_model=List[ContentTask])
def list_tasks(session: Session = Depends(get_session)):
    """All tasks, newest first."""
    return content_service.list_tasks(session)


@router.get("/{task_id}", response_model=ContentTask)
def get_task(task_id: str, session: Session = Depends(get_session)):
    task = content_service.get_task(session, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task {task_id!r} not found")
    return task
