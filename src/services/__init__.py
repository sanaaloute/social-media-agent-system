"""Business services layer (design doc §5).

Plain functions taking a ``sqlmodel.Session`` as first argument — no
classes. Every state transition writes an ``AuditLog`` row (§5.3.5) and
emits a best-effort websocket status event (§9.3).

Import rule: services NEVER import ``src.workers`` at module level — task
dispatch is lazy inside functions so the import graph stays acyclic
(workers import services, never the other way around).
"""
import logging
from typing import Dict, Optional

from sqlmodel import Session

from src.core.models import AuditLog

logger = logging.getLogger(__name__)


def _audit(
    session: Session,
    actor: str,
    action: str,
    content_id: Optional[str] = None,
    task_id: Optional[str] = None,
    detail: Optional[Dict] = None,
) -> AuditLog:
    """Append an audit entry to the session (committed by the caller)."""
    entry = AuditLog(
        actor=actor,
        action=action,
        content_id=content_id,
        task_id=task_id,
        detail=detail or {},
    )
    session.add(entry)
    return entry


def _notify(event: dict) -> None:
    """Best-effort websocket broadcast; never raises (§9.3).

    Imported lazily so that importing services never pulls in FastAPI or
    creates a module cycle (api routes import services).
    """
    try:
        from src.api.websocket.status import broadcast_status

        broadcast_status(event)
    except Exception:  # notifications must never break a state transition
        logger.debug("Status notification skipped", exc_info=True)
