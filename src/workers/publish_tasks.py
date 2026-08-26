"""Publish worker tasks — HITL-gated publishing and scheduling (§8.3)."""
import asyncio

from sqlmodel import Session

from src.core.database.engine import engine
from src.workers.celery_app import celery_app


@celery_app.task
def publish_content_task(content_id: str) -> dict:
    """Publish one approved draft; returns the PublishResult as a dict."""
    from src.services import publish_service

    with Session(engine) as session:
        result = asyncio.run(publish_service.publish_content(session, content_id))
    return result.model_dump()


@celery_app.task
def dispatch_due_task() -> int:
    """Enqueue publishing for all due scheduled content (§5.5)."""
    from src.services import schedule_service

    with Session(engine) as session:
        return schedule_service.dispatch_due(session)
