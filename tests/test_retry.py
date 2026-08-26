"""Retry endpoint: FAILED publishes can be requeued exactly once (§5.2)."""
from sqlmodel import select

from src.core.models import ApprovalStatus, AuditLog, GeneratedContent


def _failed_content(session, platform="youtube"):
    """A FAILED video row (e.g. publish attempted with no account registered)."""
    content = GeneratedContent(
        task_id="t1",
        platform=platform,
        text="retry me",
        media_urls=["./media_cache/t1/youtube/video_1.mp4"],
        status=ApprovalStatus.FAILED.value,
        publish_result={"success": False, "error": "boom"},
    )
    session.add(content)
    session.commit()
    session.refresh(content)
    return content


def test_retry_failed_content_republishes(client, session):
    # Register an account so the retried publish succeeds this time.
    client.post(
        "/api/accounts",
        json={"platform": "youtube", "username": "yt",
              "tokens": {"access_token": "t"}},
    )
    content = _failed_content(session)

    resp = client.post(f"/api/contents/{content.id}/retry", json={"actor": "bob"})
    assert resp.status_code == 200, resp.text

    # Eager queue: the retry already republished inline.
    assert resp.json()["status"] == "published"
    actions = [r.action for r in session.exec(select(AuditLog)).all()]
    assert "retry" in actions
    assert actions.count("publish") == 1  # exactly one successful republish


def test_retry_rejects_non_failed_content(client, session):
    content = GeneratedContent(
        task_id="t1", platform="twitter", text="x",
        status=ApprovalStatus.REVIEW.value,
    )
    session.add(content)
    session.commit()

    resp = client.post(f"/api/contents/{content.id}/retry", json={})
    assert resp.status_code == 400

    resp = client.post("/api/contents/no-such-id/retry", json={})
    assert resp.status_code == 404


def test_double_retry_dispatches_once(client, session):
    client.post(
        "/api/accounts",
        json={"platform": "youtube", "username": "yt",
              "tokens": {"access_token": "t"}},
    )
    content = _failed_content(session)
    assert client.post(f"/api/contents/{content.id}/retry", json={}).status_code == 200
    # Second retry: row is PUBLISHED now, not FAILED — must be rejected.
    resp = client.post(f"/api/contents/{content.id}/retry", json={})
    assert resp.status_code == 400
