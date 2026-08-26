"""Scheduling and publish-race guarantees (§5.2–§5.5).

Covers the atomic compare-and-set transitions: future-scheduled approvals
wait for the beat dispatcher, due content is claimed exactly once, and
double approve / double publish attempts are rejected.
"""
import asyncio
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import yaml
from sqlalchemy import update
from sqlmodel import Session, select

from src.core.database.engine import engine
from src.core.models import (
    ApprovalStatus,
    AuditLog,
    GeneratedContent,
    PlatformAccount,
)
from src.services.approval_service import approve
from src.services.publish_service import publish_content
from src.services.schedule_service import dispatch_due
from src.utils.crypto import get_cipher


def _twitter_account(session: Session) -> PlatformAccount:
    account = PlatformAccount(
        platform="twitter",
        username="@brand",
        tokens_enc=get_cipher().encrypt({"access_token": "x"}),
    )
    session.add(account)
    session.commit()
    return account


def _make_content(
    session: Session, *, status: str, scheduled_at: datetime | None = None
) -> GeneratedContent:
    content = GeneratedContent(
        task_id="task-1",
        platform="twitter",
        text="hello world",
        status=status,
        scheduled_at=scheduled_at,
    )
    session.add(content)
    session.commit()
    return content


def _audit_count(session: Session, action: str) -> int:
    rows = session.exec(select(AuditLog).where(AuditLog.action == action)).all()
    return len(rows)


def test_future_scheduled_approve_does_not_publish(session):
    _twitter_account(session)
    content = _make_content(
        session,
        status=ApprovalStatus.REVIEW.value,
        scheduled_at=datetime.utcnow() + timedelta(days=7),
    )

    approve(session, content.id, actor="alice")

    session.refresh(content)
    assert content.status == ApprovalStatus.APPROVED.value
    assert content.published_at is None
    assert _audit_count(session, "publish") == 0


def test_dispatch_due_publishes_due_content_exactly_once(session):
    _twitter_account(session)
    content = _make_content(
        session,
        status=ApprovalStatus.APPROVED.value,
        scheduled_at=datetime.utcnow() - timedelta(minutes=1),
    )

    assert dispatch_due(session) == 1

    session.refresh(content)
    assert content.status == ApprovalStatus.PUBLISHED.value
    assert content.published_at is not None
    assert content.publish_result["dry_run"] is True
    assert content.publish_result["success"] is True

    # The claim flipped APPROVED -> QUEUED, so a re-dispatch finds nothing.
    assert dispatch_due(session) == 0
    assert _audit_count(session, "publish") == 1


def test_double_approve_blocked(session):
    content = _make_content(session, status=ApprovalStatus.REVIEW.value)

    approve(session, content.id, actor="alice")
    with pytest.raises(ValueError):
        approve(session, content.id, actor="bob")

    assert _audit_count(session, "approve") == 1


def test_double_publish_blocked(session):
    _twitter_account(session)
    content = _make_content(session, status=ApprovalStatus.APPROVED.value)

    result = asyncio.run(publish_content(session, content.id))
    assert result.success is True
    session.refresh(content)
    assert content.status == ApprovalStatus.PUBLISHED.value

    # Terminal state: the HITL gate refuses a second publish outright.
    with pytest.raises(PermissionError):
        asyncio.run(publish_content(session, content.id))

    # Lost-race path: this session still holds a stale APPROVED snapshot
    # while a competing publisher wins the atomic claim underneath it.
    content.status = ApprovalStatus.APPROVED.value
    session.add(content)
    session.commit()
    session.refresh(content)
    claim = (
        update(GeneratedContent)
        .where(GeneratedContent.id == content.id)
        .where(
            GeneratedContent.status.in_(
                (ApprovalStatus.APPROVED.value, ApprovalStatus.QUEUED.value)
            )
        )
        .values(status=ApprovalStatus.PUBLISHING.value)
    )
    with Session(engine) as rival:
        assert rival.execute(claim).rowcount == 1
        rival.commit()

    result = asyncio.run(publish_content(session, content.id))
    assert result.success is False
    assert result.error == "content already claimed by another publisher"

    with Session(engine) as check:
        row = check.get(GeneratedContent, content.id)
        assert row.status == ApprovalStatus.PUBLISHING.value


def test_compose_database_url_uses_psycopg_v3():
    compose = Path(__file__).resolve().parents[1] / "docker-compose.yml"
    data = yaml.safe_load(compose.read_text())
    url = data["services"]["web"]["environment"]["DATABASE_URL"]
    assert "postgresql+psycopg://" in url
