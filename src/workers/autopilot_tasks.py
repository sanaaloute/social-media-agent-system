"""Autopilot beat task — runs autopilot_tick on a schedule (§8.1)."""
from sqlmodel import Session

from src.core.database.engine import engine
from src.workers.celery_app import celery_app


@celery_app.task
def autopilot_tick_task() -> dict:
    from src.services.autopilot_service import autopilot_tick

    with Session(engine) as session:
        return autopilot_tick(session)
