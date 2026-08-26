"""Autopilot service — fully autonomous mode (opt-in, §5/§8).

Requires BOTH the global ``autopilot_enabled`` setting (default OFF) and a
per-brand ``autopilot`` flag. Each tick:
1. Auto-approves the brand's REVIEW drafts (actor "autopilot") — they then
   publish at their planner-assigned schedule like any approved content.
2. Creates one topic-less "mixed" task per brand if none was created within
   ``autopilot_interval_hours`` — the agents decide the topic (hot-topic
   discovery), the content types, and the schedule themselves.
3. Flushes any due scheduled content via the regular dispatcher.
"""
import logging
from datetime import datetime, timedelta

from sqlmodel import Session, select

from src.core import runtime_settings
from src.core.config import get_settings
from src.core.models import ApprovalStatus, Brand, ContentTask, GeneratedContent
from src.services import approval_service, content_service, schedule_service

logger = logging.getLogger(__name__)


def autopilot_tick(session: Session) -> dict:
    summary: dict = {"auto_approved": 0, "tasks_created": 0, "dispatched_due": 0, "brands": []}
    if not runtime_settings.get_value("autopilot_enabled"):
        summary["disabled"] = True
        return summary

    brands = list(session.exec(select(Brand).where(Brand.autopilot.is_(True))).all())
    interval = timedelta(hours=get_settings().autopilot_interval_hours)

    for brand in brands:
        if not brand.platforms:
            logger.warning("autopilot brand %s has no platforms; skipping", brand.name)
            continue

        task_ids = [
            t.id
            for t in session.exec(
                select(ContentTask).where(ContentTask.brand_id == brand.id)
            ).all()
        ]
        pending = (
            list(
                session.exec(
                    select(GeneratedContent).where(
                        GeneratedContent.task_id.in_(task_ids),
                        GeneratedContent.status == ApprovalStatus.REVIEW.value,
                    )
                ).all()
            )
            if task_ids
            else []
        )
        for content in pending:
            try:
                approval_service.approve(session, content.id, actor="autopilot")
                summary["auto_approved"] += 1
            except ValueError:
                pass  # status changed concurrently — nothing to approve

        latest = session.exec(
            select(ContentTask)
            .where(ContentTask.brand_id == brand.id)
            .order_by(ContentTask.created_at.desc())
        ).first()
        if latest is None or datetime.utcnow() - latest.created_at >= interval:
            logger.info("autopilot: creating task for brand %s", brand.name)
            task = content_service.create_task(
                session,
                brand_id=brand.id,
                platforms=list(brand.platforms),
                topic="",
                content_type="mixed",
            )
            content_service.dispatch_generation(task.id)
            summary["tasks_created"] += 1
            summary["brands"].append(brand.name)

    summary["dispatched_due"] = schedule_service.dispatch_due(session)
    return summary
