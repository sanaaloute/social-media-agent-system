"""Approval routes — the human review queue (§5.3, §9.1)."""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from src.core.database.engine import get_session
from src.core.models import GeneratedContent
from src.services import approval_service

router = APIRouter(prefix="/approvals", tags=["approvals"])


class ActorBody(BaseModel):
    actor: str = "reviewer"


class RejectBody(BaseModel):
    actor: str = "reviewer"
    feedback: str


class ModifyBody(BaseModel):
    actor: str = "reviewer"
    text: Optional[str] = None
    hashtags: Optional[List[str]] = None


@router.get("/pending", response_model=List[GeneratedContent])
def list_pending(session: Session = Depends(get_session)):
    """Drafts waiting on a reviewer (§5.3.1)."""
    return approval_service.list_pending(session)


@router.post("/{content_id}/approve", response_model=GeneratedContent)
def approve(
    content_id: str, body: ActorBody, session: Session = Depends(get_session)
):
    try:
        return approval_service.approve(session, content_id, body.actor)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{content_id}/reject", response_model=GeneratedContent)
def reject(
    content_id: str, body: RejectBody, session: Session = Depends(get_session)
):
    try:
        return approval_service.reject(
            session, content_id, body.actor, body.feedback
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{content_id}/modify", response_model=GeneratedContent)
def modify(
    content_id: str, body: ModifyBody, session: Session = Depends(get_session)
):
    try:
        return approval_service.modify(
            session, content_id, body.actor, body.text, body.hashtags
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
