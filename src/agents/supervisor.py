"""Supervisor: runs the generation pipeline for a ContentTask and persists
the resulting drafts as GeneratedContent rows in REVIEW status (§3.5).

The task row tracks lifecycle via TaskStatus (GENERATING -> GENERATED, or
FAILED with the error returned rather than raised).
"""
import logging
import traceback
from datetime import datetime

from sqlmodel import Session

from src.agents.graph import create_workflow
from src.core.database.engine import engine, init_db
from src.core.models import (
    ApprovalStatus,
    Brand,
    ContentTask,
    GeneratedContent,
    TaskStatus,
)

logger = logging.getLogger(__name__)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        logger.warning("Unparseable schedule time %r; ignoring.", value)
        return None


def run_generation(task_id: str) -> dict:
    """Run the agent pipeline for a task and persist the generated drafts."""
    init_db()
    with Session(engine) as session:
        task = session.get(ContentTask, task_id)
        if task is None:
            raise ValueError(f"ContentTask {task_id!r} not found")
        task.status = TaskStatus.GENERATING.value
        session.add(task)
        session.commit()

        brand = session.get(Brand, task.brand_id) if task.brand_id else None
        initial_state = {
            "task_id": task.id,
            "brand_context": {
                "brand_id": task.brand_id,
                "content_type": task.content_type,
                "name": brand.name if brand else "",
                "niche": brand.niche if brand else "",
                "keywords": list(brand.keywords) if brand else [],
                "tone": brand.tone if brand else "",
            },
            "topic": task.topic,
            "platforms": task.platforms,
            "research_results": None,
            "content_plan": None,
            "drafts": None,
            "images": None,
            "videos": None,
            "quality_report": None,
            "approved_content": None,
            "publish_results": None,
            "error": None,
            "status": "started",
            "revision_count": 0,
        }

        try:
            final_state = create_workflow().invoke(initial_state)
        except Exception as exc:
            logger.error(
                "Generation pipeline failed for task %s\n%s",
                task_id,
                traceback.format_exc(),
            )
            task.status = TaskStatus.FAILED.value
            session.add(task)
            session.commit()
            return {"task_id": task_id, "status": "failed", "error": str(exc)}

        drafts = final_state.get("drafts") or {}
        images = final_state.get("images") or {}
        videos = final_state.get("videos") or {}
        schedule = (final_state.get("content_plan") or {}).get("schedule") or {}
        meta = {
            "quality_report": final_state.get("quality_report"),
            "content_plan": final_state.get("content_plan"),
        }
        content_ids = []
        for platform, draft in drafts.items():
            media = (images.get(platform) or []) + (videos.get(platform) or [])
            content = GeneratedContent(
                task_id=task.id,
                platform=platform,
                text=draft.get("text"),
                hashtags=draft.get("hashtags") or [],
                media_urls=media,
                meta=meta,
                status=ApprovalStatus.REVIEW.value,
                scheduled_at=task.scheduled_at or _parse_dt(schedule.get(platform)),
            )
            session.add(content)
            session.commit()
            session.refresh(content)
            content_ids.append(content.id)

        task.topic = final_state.get("topic") or task.topic
        task.status = TaskStatus.GENERATED.value
        session.add(task)
        session.commit()

        # Memory: record the covered topic so future research avoids repeats.
        if task.brand_id and task.topic:
            from src.agents.memory import remember

            remember(task.brand_id, "covered_topic", task.topic)

    return {"task_id": task_id, "status": "generated", "content_ids": content_ids}
