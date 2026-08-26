"""Content routes — inspect generated drafts and retry failed publishes (§9.1)."""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import update
from sqlmodel import Session, select

from src.core.database.engine import get_session
from src.core.models import ApprovalStatus, GeneratedContent
from src.services import _audit

router = APIRouter(prefix="/contents", tags=["contents"])


@router.get("", response_model=List[GeneratedContent])
def list_contents(
    status: Optional[str] = None,
    task_id: Optional[str] = None,
    session: Session = Depends(get_session),
):
    """All generated content, newest first; filter by status and/or task."""
    stmt = select(GeneratedContent)
    if status is not None:
        stmt = stmt.where(GeneratedContent.status == status)
    if task_id is not None:
        stmt = stmt.where(GeneratedContent.task_id == task_id)
    stmt = stmt.order_by(GeneratedContent.created_at.desc())
    return list(session.exec(stmt).all())


@router.get("/{content_id}", response_model=GeneratedContent)
def get_content(content_id: str, session: Session = Depends(get_session)):
    content = session.get(GeneratedContent, content_id)
    if content is None:
        raise HTTPException(
            status_code=404, detail=f"Content {content_id!r} not found"
        )
    return content


class RetryRequest(BaseModel):
    actor: str = "reviewer"


@router.post("/{content_id}/retry", response_model=GeneratedContent)
def retry_content(
    content_id: str,
    payload: RetryRequest,
    session: Session = Depends(get_session),
):
    """Requeue a FAILED publish (§5.2): FAILED -> QUEUED, then dispatch.

    Only FAILED rows are retryable — anything else is a 400. The claim is
    atomic so two retries can't dispatch the same content twice.
    """
    stmt = (
        update(GeneratedContent)
        .where(GeneratedContent.id == content_id)
        .where(GeneratedContent.status == ApprovalStatus.FAILED.value)
        .values(status=ApprovalStatus.QUEUED.value)
    )
    if session.execute(stmt).rowcount == 0:
        content = session.get(GeneratedContent, content_id)
        if content is None:
            raise HTTPException(404, f"Content {content_id!r} not found")
        raise HTTPException(
            400,
            f"Content {content_id!r} is {content.status!r}; "
            f"only {ApprovalStatus.FAILED.value!r} content can be retried",
        )
    content = session.get(GeneratedContent, content_id)
    _audit(
        session,
        actor=payload.actor,
        action="retry",
        content_id=content.id,
        task_id=content.task_id,
    )
    session.commit()
    session.refresh(content)

    from src.workers.publish_tasks import publish_content_task

    publish_content_task.delay(content.id)
    session.refresh(content)
    return content
