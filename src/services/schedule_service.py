"""Schedule service — dispatches approved content whose time is due (§5.5)."""
import logging
from datetime import datetime
from typing import List

from sqlalchemy import update
from sqlmodel import Session, select

from src.core.models import ApprovalStatus, GeneratedContent

logger = logging.getLogger(__name__)


def due_contents(session: Session) -> List[GeneratedContent]:
    """APPROVED content whose scheduled_at has passed (§5.5)."""
    now = datetime.utcnow()
    stmt = select(GeneratedContent).where(
        GeneratedContent.status == ApprovalStatus.APPROVED.value,
        GeneratedContent.scheduled_at.is_not(None),
        GeneratedContent.scheduled_at <= now,
    )
    return list(session.exec(stmt).all())


def dispatch_due(session: Session) -> int:
    """Claim every due draft (APPROVED -> QUEUED) and enqueue publishing."""
    from src.workers.publish_tasks import publish_content_task

    dispatched = 0
    for content in due_contents(session):
        # Atomic claim: only the dispatcher that flips APPROVED -> QUEUED
        # enqueues the task, so overlapping beats cannot double-dispatch.
        stmt = (
            update(GeneratedContent)
            .where(GeneratedContent.id == content.id)
            .where(GeneratedContent.status == ApprovalStatus.APPROVED.value)
            .values(status=ApprovalStatus.QUEUED.value)
        )
        if session.execute(stmt).rowcount != 1:
            continue
        session.commit()  # claim must be visible before the worker reads the row
        publish_content_task.delay(content.id)
        dispatched += 1
    if dispatched:
        logger.info("Dispatched %d due content(s) for publishing", dispatched)
    return dispatched
