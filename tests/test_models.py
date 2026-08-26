"""Model persistence: JSON list/dict columns roundtrip through the DB (§5.1)."""
from sqlmodel import select

from src.core.models import (
    ApprovalStatus,
    AuditLog,
    ContentTask,
    GeneratedContent,
    PlatformAccount,
    TaskStatus,
)


def test_content_task_roundtrip(session):
    task = ContentTask(
        brand_id="brand-1",
        platforms=["twitter", "linkedin"],
        topic="launch",
        content_type="mixed",
        status=TaskStatus.PENDING.value,
    )
    session.add(task)
    session.commit()

    loaded = session.get(ContentTask, task.id)
    assert loaded.platforms == ["twitter", "linkedin"]
    assert loaded.status == "pending"
    assert loaded.created_at is not None


def test_generated_content_roundtrip(session):
    task = ContentTask(brand_id="b", platforms=["twitter"], topic="t")
    session.add(task)
    session.commit()

    content = GeneratedContent(
        task_id=task.id,
        platform="twitter",
        text="hello",
        media_urls=["./media_cache/x/img.png"],
        hashtags=["ai", "launch"],
        meta={"score": 0.9},
        status=ApprovalStatus.REVIEW.value,
    )
    session.add(content)
    session.commit()

    loaded = session.get(GeneratedContent, content.id)
    assert loaded.media_urls == ["./media_cache/x/img.png"]
    assert loaded.hashtags == ["ai", "launch"]
    assert loaded.meta == {"score": 0.9}
    assert loaded.status == "review"


def test_platform_account_and_audit(session):
    account = PlatformAccount(platform="twitter", username="@brand")
    session.add(account)
    session.add(
        AuditLog(actor="alice", action="approve", content_id="c1", detail={"ok": True})
    )
    session.commit()

    assert session.get(PlatformAccount, account.id).is_active is True
    rows = session.exec(select(AuditLog).where(AuditLog.content_id == "c1")).all()
    assert len(rows) == 1
    assert rows[0].actor == "alice"
    assert rows[0].detail == {"ok": True}
