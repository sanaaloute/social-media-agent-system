"""Approval queue service — human-in-the-loop review transitions (§5.3).

Lifecycle (§5.2): REVIEW -> APPROVED | REJECTED, with in-place edits that
keep the draft in REVIEW. Every transition is audited (§5.3.5).
"""
import logging
from datetime import datetime
from typing import List, Optional

from sqlalchemy import update
from sqlmodel import Session, select

from src.core.models import ApprovalStatus, GeneratedContent
from src.services import _audit, _notify

logger = logging.getLogger(__name__)


def list_pending(session: Session) -> List[GeneratedContent]:
    """All drafts waiting on a reviewer, oldest first (§5.3.1)."""
    stmt = (
        select(GeneratedContent)
        .where(GeneratedContent.status == ApprovalStatus.REVIEW.value)
        .order_by(GeneratedContent.created_at)
    )
    return list(session.exec(stmt).all())


def _get_reviewable(session: Session, content_id: str) -> GeneratedContent:
    """Fetch a draft or raise ValueError (missing row / wrong status)."""
    content = session.get(GeneratedContent, content_id)
    if content is None:
        raise ValueError(f"GeneratedContent {content_id!r} not found")
    if content.status != ApprovalStatus.REVIEW.value:
        raise ValueError(
            f"Content {content_id!r} is {content.status!r}, "
            f"expected {ApprovalStatus.REVIEW.value!r}"
        )
    return content


def approve(session: Session, content_id: str, actor: str) -> GeneratedContent:
    """REVIEW -> APPROVED, then queue publishing when due (§5.3.2)."""
    # Atomic compare-and-set: exactly one approver can win the REVIEW race.
    stmt = (
        update(GeneratedContent)
        .where(GeneratedContent.id == content_id)
        .where(GeneratedContent.status == ApprovalStatus.REVIEW.value)
        .values(status=ApprovalStatus.APPROVED.value)
    )
    if session.execute(stmt).rowcount == 0:
        content = session.get(GeneratedContent, content_id)
        if content is None:
            raise ValueError(f"GeneratedContent {content_id!r} not found")
        raise ValueError(
            f"Content {content_id!r} is {content.status!r}, "
            f"expected {ApprovalStatus.REVIEW.value!r}"
        )
    content = session.get(GeneratedContent, content_id)
    _audit(
        session,
        actor=actor,
        action="approve",
        content_id=content.id,
        task_id=content.task_id,
    )
    session.commit()
    session.refresh(content)
    _notify(
        {
            "event": "approve",
            "content_id": content.id,
            "task_id": content.task_id,
            "status": content.status,
            "actor": actor,
        }
    )

    # Future-scheduled drafts stay APPROVED for the beat dispatcher (§5.5).
    if content.scheduled_at is None or content.scheduled_at <= datetime.utcnow():
        from src.workers.publish_tasks import publish_content_task

        publish_content_task.delay(content.id)
    return content


def _brand_id_for(session: Session, content: GeneratedContent) -> str:
    """Brand behind a content row (via its task), for memory writes."""
    from src.core.models import ContentTask

    task = session.get(ContentTask, content.task_id)
    return task.brand_id if task else ""


def reject(
    session: Session, content_id: str, actor: str, feedback: str
) -> GeneratedContent:
    """REVIEW -> REJECTED, recording the reviewer's feedback (§5.3.3)."""
    content = _get_reviewable(session, content_id)
    content.status = ApprovalStatus.REJECTED.value
    content.reviewer_feedback = feedback
    session.add(content)
    _audit(
        session,
        actor=actor,
        action="reject",
        content_id=content.id,
        task_id=content.task_id,
        detail={"feedback": feedback},
    )
    session.commit()
    session.refresh(content)
    # Memory: the writer learns the reviewer's preferences from feedback.
    if feedback.strip():
        from src.agents.memory import remember

        remember(_brand_id_for(session, content), "review_feedback", feedback)
    _notify(
        {
            "event": "reject",
            "content_id": content.id,
            "task_id": content.task_id,
            "status": content.status,
            "actor": actor,
        }
    )
    return content


def modify(
    session: Session,
    content_id: str,
    actor: str,
    text: Optional[str] = None,
    hashtags: Optional[List[str]] = None,
) -> GeneratedContent:
    """Apply reviewer edits; the draft stays in REVIEW (§5.3.4)."""
    content = _get_reviewable(session, content_id)
    fields = []
    if text is not None:
        content.text = text
        fields.append("text")
    if hashtags is not None:
        content.hashtags = list(hashtags)
        fields.append("hashtags")
    content.status = ApprovalStatus.REVIEW.value
    session.add(content)
    _audit(
        session,
        actor=actor,
        action="modify",
        content_id=content.id,
        task_id=content.task_id,
        detail={"fields": fields},
    )
    session.commit()
    session.refresh(content)
    _notify(
        {
            "event": "modify",
            "content_id": content.id,
            "task_id": content.task_id,
            "status": content.status,
            "actor": actor,
        }
    )
    return content
