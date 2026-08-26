"""Content task service — task intake and generation dispatch (§3.1)."""
import logging
from datetime import datetime
from typing import List, Optional

from sqlmodel import Session, select

from src.core.models import ContentTask, TaskStatus
from src.services import _audit, _notify

logger = logging.getLogger(__name__)


def create_task(
    session: Session,
    brand_id: str,
    platforms: List[str],
    topic: str,
    content_type: str = "mixed",
    scheduled_at: Optional[datetime] = None,
) -> ContentTask:
    """Persist a new ContentTask in PENDING status (§3.1)."""
    task = ContentTask(
        brand_id=brand_id,
        platforms=list(platforms),
        topic=topic,
        content_type=content_type,
        status=TaskStatus.PENDING.value,
        scheduled_at=scheduled_at,
    )
    session.add(task)
    _audit(
        session,
        actor="system",
        action="task_created",
        task_id=task.id,
        detail={"brand_id": brand_id, "platforms": list(platforms), "topic": topic},
    )
    session.commit()
    session.refresh(task)
    _notify({"event": "task_created", "task_id": task.id, "status": task.status})
    return task


def dispatch_generation(task_id: str) -> None:
    """Queue the generation pipeline for a task (§8.1).

    In eager queue mode ``.delay()`` executes inline; in celery mode it is
    sent to the broker. Lazy import — services never import workers at
    module level.
    """
    from src.workers.generation_tasks import generate_content

    generate_content.delay(task_id)


def get_task(session: Session, task_id: str) -> Optional[ContentTask]:
    return session.get(ContentTask, task_id)


def list_tasks(session: Session) -> List[ContentTask]:
    """All tasks, newest first."""
    stmt = select(ContentTask).order_by(ContentTask.created_at.desc())
    return list(session.exec(stmt).all())
