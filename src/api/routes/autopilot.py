"""Autopilot routes — status and manual tick (§8).

The manual tick matters in eager queue mode (no beat process) and for
demos: one call auto-approves pending autopilot drafts, creates due
autopilot tasks, and flushes the scheduled-publish queue.
"""
from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from src.core import runtime_settings
from src.core.database.engine import get_session
from src.core.models import Brand
from src.services.autopilot_service import autopilot_tick

router = APIRouter(prefix="/autopilot", tags=["autopilot"])


@router.get("/status")
def autopilot_status(session: Session = Depends(get_session)):
    brands = list(session.exec(select(Brand)).all())
    return {
        "enabled": runtime_settings.get_value("autopilot_enabled"),
        "brands": [
            {
                "id": b.id,
                "name": b.name,
                "niche": b.niche,
                "platforms": b.platforms,
                "autopilot": b.autopilot,
            }
            for b in brands
        ],
    }


@router.post("/tick")
def run_autopilot_tick(session: Session = Depends(get_session)):
    return autopilot_tick(session)
