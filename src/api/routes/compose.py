"""Direct-compose route — user-written posts published straight away.

The composer IS the human in the loop: writing the post and clicking
"Post now" is the approval action, so composed posts skip the review queue
but stay fully audited — the approve and publish transitions are recorded
under the composer's actor name like any other review action (§5.3.5).
"""
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlmodel import Session

from src.core.config import get_settings
from src.core.database.engine import get_session
from src.core.models import ContentTask, GeneratedContent, TaskStatus
from src.publishers import validate_platforms
from src.services import approval_service

router = APIRouter(prefix="/compose", tags=["compose"])

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
VIDEO_EXT = {".mp4", ".mov", ".webm"}


@router.post("", status_code=201)
def compose_post(
    text: str = Form(""),
    platforms: str = Form(...),  # comma-separated, e.g. "twitter,linkedin"
    actor: str = Form("composer"),
    media: Optional[UploadFile] = File(default=None),
    session: Session = Depends(get_session),
):
    try:
        platform_list = validate_platforms(platforms.split(","))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not platform_list:
        raise HTTPException(400, "At least one platform is required")

    text = text.strip()
    has_media = media is not None and bool(media.filename)
    if not text and not has_media:
        raise HTTPException(400, "Text or a media file is required")

    media_path: Optional[str] = None
    ext = ""
    if has_media:
        ext = Path(media.filename).suffix.lower()
        if ext not in IMAGE_EXT | VIDEO_EXT:
            raise HTTPException(
                400,
                f"Unsupported media type {ext!r}; "
                f"images ({', '.join(sorted(IMAGE_EXT))}) or "
                f"videos ({', '.join(sorted(VIDEO_EXT))}) only",
            )
        upload_dir = Path(get_settings().media_cache_dir) / "uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
        media_path = str(upload_dir / f"{uuid.uuid4().hex}{ext}")
        # Sync read of the upload's spooled file — this route is sync.
        with open(media_path, "wb") as fh:
            fh.write(media.file.read())

    # A backing task keeps the FK intact and groups the per-platform rows.
    content_type = (
        "video" if ext in VIDEO_EXT else ("image" if media_path else "text")
    )
    task = ContentTask(
        brand_id="manual",
        platforms=platform_list,
        topic=text[:80] or f"Media post ({media.filename})",
        content_type=content_type,
        status=TaskStatus.GENERATED.value,
    )
    session.add(task)
    session.commit()
    session.refresh(task)

    results = []
    for platform in platform_list:
        content = GeneratedContent(
            task_id=task.id,
            platform=platform,
            text=text or None,
            media_urls=[media_path] if media_path else [],
            hashtags=[],
            meta={"source": "composer"},
            status="review",
        )
        session.add(content)
        session.commit()
        session.refresh(content)
        # The composer's submit IS the human approval (HITL); approve()
        # transitions REVIEW -> APPROVED and dispatches publishing when due.
        approval_service.approve(session, content.id, actor)
        session.refresh(content)
        results.append(
            {
                "platform": platform,
                "content_id": content.id,
                "status": content.status,
                "publish_result": content.publish_result,
            }
        )

    return {"task_id": task.id, "results": results}
