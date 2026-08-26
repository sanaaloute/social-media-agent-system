"""Agent memory — DB-backed, brand-scoped long-term memory (§3.2).

What is stored:
- ``covered_topic``: topics the brand already posted about, so the
  Researcher Agent doesn't surface the same story again.
- ``review_feedback``: human reviewer feedback from rejects/edits, so the
  Writer Agent learns the reviewer's preferences over time.

Reads/writes use short-lived sessions on the shared engine, so memory is
usable from agents (no session of their own) and services alike.
"""
import logging
from datetime import datetime, timedelta
from typing import List, Optional

from sqlmodel import Field, SQLModel, Session, select

logger = logging.getLogger(__name__)


class MemoryEntry(SQLModel, table=True):
    __tablename__ = "memory_entry"

    id: Optional[int] = Field(default=None, primary_key=True)
    brand_id: str = Field(index=True)
    kind: str = Field(index=True)  # covered_topic | review_feedback
    value: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


def remember(brand_id: str, kind: str, value: str) -> None:
    """Append a memory entry (best-effort — memory never breaks a run)."""
    if not brand_id or not value.strip():
        return
    from src.core.database.engine import engine

    try:
        with Session(engine) as session:
            session.add(MemoryEntry(brand_id=brand_id, kind=kind, value=value.strip()))
            session.commit()
    except Exception:
        logger.warning("memory write failed for brand %s", brand_id, exc_info=True)


def recall(
    brand_id: str,
    kind: str,
    limit: int = 20,
    since_days: Optional[int] = None,
) -> List[str]:
    """Most recent memory values for a brand, newest first."""
    if not brand_id:
        return []
    from src.core.database.engine import engine

    try:
        with Session(engine) as session:
            stmt = select(MemoryEntry).where(
                MemoryEntry.brand_id == brand_id,
                MemoryEntry.kind == kind,
            )
            if since_days is not None:
                cutoff = datetime.utcnow() - timedelta(days=since_days)
                stmt = stmt.where(MemoryEntry.created_at >= cutoff)
            stmt = stmt.order_by(MemoryEntry.created_at.desc()).limit(limit)
            return [row.value for row in session.exec(stmt).all()]
    except Exception:
        logger.warning("memory read failed for brand %s", brand_id, exc_info=True)
        return []
