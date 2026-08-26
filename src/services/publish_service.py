"""Publish service — HITL-gated publishing of approved content (§5.4, §7).

The gate (§5.4): only content explicitly APPROVED by a human (or already
QUEUED for delivery) may be published — anything else raises
PermissionError. Transitions QUEUED -> PUBLISHING -> PUBLISHED | FAILED
are committed and audited step by step (§5.3.5).
"""
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import update
from sqlmodel import Session, select

from src.core.models import ApprovalStatus, GeneratedContent, PlatformAccount
from src.publishers import PublishResult, get_adapter
from src.services import _audit, _notify

logger = logging.getLogger(__name__)

VIDEO_EXTENSIONS = (".mp4", ".mov", ".webm")

_PUBLISHABLE = (ApprovalStatus.APPROVED.value, ApprovalStatus.QUEUED.value)


def _find_account(session: Session, platform: str) -> Optional[PlatformAccount]:
    """First active account for the platform, if any (§6.2)."""
    stmt = select(PlatformAccount).where(
        PlatformAccount.platform == platform,
        PlatformAccount.is_active.is_(True),
    )
    return session.exec(stmt).first()


def _build_payload(content: GeneratedContent) -> dict:
    """Map a GeneratedContent row to the adapter content shape (§7.2)."""
    media = content.media_urls or []
    text = content.text or ""
    metadata = {"hashtags": content.hashtags or []}
    video = next(
        (url for url in media if url.lower().endswith(VIDEO_EXTENSIONS)), None
    )
    if video is not None:
        title = (text.splitlines() or [""])[0][:100] or "Untitled"
        return {
            "type": "video",
            "video_path": video,
            "path": video,
            "title": title,
            "description": text,
            "metadata": metadata,
        }
    if media:
        return {
            "type": "image",
            "image_path": media[0],
            "path": media[0],
            "caption": text,
            "metadata": metadata,
        }
    return {"type": "text", "text": text, "metadata": metadata}


async def publish_content(session: Session, content_id: str) -> PublishResult:
    """Publish one approved draft through its platform adapter (§5.4)."""
    content = session.get(GeneratedContent, content_id)
    if content is None:
        raise ValueError(f"GeneratedContent {content_id!r} not found")
    if content.status not in _PUBLISHABLE:
        # HITL gate (§5.4): nothing reaches a platform without human approval.
        raise PermissionError(
            f"Refusing to publish content {content_id!r} in status "
            f"{content.status!r}; human approval is required first"
        )

    # Atomic claim: the first publisher to flip APPROVED|QUEUED -> PUBLISHING
    # wins; a loser stops here instead of double-publishing.
    stmt = (
        update(GeneratedContent)
        .where(GeneratedContent.id == content_id)
        .where(GeneratedContent.status.in_(_PUBLISHABLE))
        .values(status=ApprovalStatus.PUBLISHING.value)
    )
    if session.execute(stmt).rowcount == 0:
        return PublishResult(
            success=False,
            platform=content.platform,
            error="content already claimed by another publisher",
        )

    content.status = ApprovalStatus.PUBLISHING.value
    session.add(content)
    # Both lifecycle steps stay on the audit trail even though the claim is
    # a single atomic transition (§5.3.5).
    _audit(session, actor="system", action="queued", content_id=content.id,
           task_id=content.task_id)
    _audit(session, actor="system", action="publishing", content_id=content.id,
           task_id=content.task_id)
    session.commit()
    session.refresh(content)
    _notify({"event": "queued", "content_id": content.id,
             "task_id": content.task_id, "status": content.status})
    _notify({"event": "publishing", "content_id": content.id,
             "task_id": content.task_id, "status": content.status})

    account = _find_account(session, content.platform)
    if account is None:
        result = PublishResult(
            success=False,
            platform=content.platform,
            error=f"No active account for platform {content.platform!r}",
        )
        content.status = ApprovalStatus.FAILED.value
        content.publish_result = result.model_dump()
        session.add(content)
        _audit(session, actor="system", action="publish_failed",
               content_id=content.id, task_id=content.task_id,
               detail={"error": result.error})
        session.commit()
        _notify({"event": "publish_failed", "content_id": content.id,
                 "task_id": content.task_id, "status": content.status})
        return result

    payload = _build_payload(content)
    try:
        result = await get_adapter(account).publish(payload)
    except Exception as exc:  # adapters wrap errors, but never strand PUBLISHING
        logger.exception("Publish raised for content %s", content.id)
        result = PublishResult(
            success=False, platform=content.platform, error=str(exc)
        )

    if result.success:
        content.status = ApprovalStatus.PUBLISHED.value
        content.published_at = datetime.utcnow()
        action = "publish"
    else:
        content.status = ApprovalStatus.FAILED.value
        action = "publish_failed"
    content.publish_result = result.model_dump()
    session.add(content)
    _audit(session, actor="system", action=action, content_id=content.id,
           task_id=content.task_id,
           detail={"url": result.url, "remote_id": result.remote_id,
                   "error": result.error})
    session.commit()
    session.refresh(content)
    _notify({"event": action, "content_id": content.id,
             "task_id": content.task_id, "status": content.status})
    return result
