"""Full HTTP loop: task → generation → approval queue → publish (§5.2/§5.3).

Runs against the FastAPI TestClient with eager queue + mock providers +
dry-run publishing, so the whole lifecycle executes without any credentials.
"""
from sqlmodel import select

from src.core.models import AuditLog, GeneratedContent


def _create_twitter_account(client):
    resp = client.post(
        "/api/accounts",
        json={
            "platform": "twitter",
            "username": "@brand",
            "tokens": {"access_token": "fake"},
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_task(client, platforms=("twitter",)):
    resp = client.post(
        "/api/tasks",
        json={
            "brand_id": "brand-1",
            "platforms": list(platforms),
            "topic": "spring product launch",
            "content_type": "text",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_full_loop_approve_then_dry_run_publish(client, session):
    _create_twitter_account(client)
    task = _create_task(client)

    # POST returns the pre-dispatch snapshot; re-fetch to see the outcome.
    # Eager queue: generation already ran inline during POST /api/tasks.
    task = client.get(f"/api/tasks/{task['id']}").json()
    assert task["status"] == "generated"

    pending = client.get("/api/approvals/pending").json()
    assert len(pending) == 1
    content = pending[0]
    assert content["platform"] == "twitter"
    assert content["status"] == "review"
    assert content["text"]

    # The planner proposes a default schedule per platform; this loop tests
    # the unscheduled path, where approval publishes immediately.
    row = session.get(GeneratedContent, content["id"])
    row.scheduled_at = None
    session.add(row)
    session.commit()

    resp = client.post(f"/api/approvals/{content['id']}/approve", json={"actor": "alice"})
    assert resp.status_code == 200, resp.text

    final = client.get(f"/api/contents/{content['id']}").json()
    assert final["status"] == "published"
    assert final["published_at"] is not None
    assert final["publish_result"]["dry_run"] is True
    assert final["publish_result"]["success"] is True

    # Audit trail: task_created, queued/publishing, publish — with actors.
    actions = [
        row.action for row in session.exec(select(AuditLog)).all()
    ]
    assert "task_created" in actions
    assert "approve" in actions
    assert "publish" in actions


def test_reject_flow(client, session):
    _create_twitter_account(client)
    _create_task(client)

    pending = client.get("/api/approvals/pending").json()
    cid = pending[0]["id"]

    resp = client.post(
        f"/api/approvals/{cid}/reject",
        json={"actor": "bob", "feedback": "off-brand tone"},
    )
    assert resp.status_code == 200, resp.text

    final = client.get(f"/api/contents/{cid}").json()
    assert final["status"] == "rejected"
    assert final["reviewer_feedback"] == "off-brand tone"

    # Rejected content must not be publishable via the approval action.
    resp = client.post(f"/api/approvals/{cid}/approve", json={"actor": "bob"})
    assert resp.status_code == 400

    # Queue is now empty.
    assert client.get("/api/approvals/pending").json() == []


def test_modify_flow(client):
    _create_twitter_account(client)
    _create_task(client)
    pending = client.get("/api/approvals/pending").json()
    cid = pending[0]["id"]

    resp = client.post(
        f"/api/approvals/{cid}/modify",
        json={"actor": "carol", "text": "rewritten copy", "hashtags": ["new"]},
    )
    assert resp.status_code == 200, resp.text

    final = client.get(f"/api/contents/{cid}").json()
    assert final["status"] == "review"
    assert final["text"] == "rewritten copy"
    assert final["hashtags"] == ["new"]


def test_accounts_are_masked(client):
    _create_twitter_account(client)
    accounts = client.get("/api/accounts").json()
    assert len(accounts) == 1
    assert accounts[0]["tokens_enc"] == "***"
    assert accounts[0]["credentials_enc"] == "***"


def test_unknown_content_404(client):
    resp = client.get("/api/contents/does-not-exist")
    assert resp.status_code == 404
