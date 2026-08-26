"""Direct-compose endpoint: user-written posts publish immediately (HITL =
the composer). Covers text posts, media upload, and per-platform failures.
"""
import io

from sqlmodel import select

from src.core.models import AuditLog, GeneratedContent


def _add_account(client, platform, username="@acct"):
    resp = client.post(
        "/api/accounts",
        json={"platform": platform, "username": username,
              "tokens": {"access_token": "x"}},
    )
    assert resp.status_code == 201, resp.text


def test_compose_text_publishes_immediately(client, session):
    _add_account(client, "twitter")
    resp = client.post(
        "/api/compose",
        data={"text": "hello from the composer", "platforms": "twitter"},
    )
    assert resp.status_code == 201, resp.text
    result = resp.json()["results"][0]
    assert result["platform"] == "twitter"
    assert result["status"] == "published"
    assert result["publish_result"]["dry_run"] is True

    # The composer's approval is on the audit trail like any review action.
    actions = [r.action for r in session.exec(select(AuditLog)).all()]
    assert "approve" in actions
    assert "publish" in actions


def test_compose_with_media_upload(client, tmp_path):
    _add_account(client, "instagram", "acme_ig")
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
        b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    resp = client.post(
        "/api/compose",
        data={"text": "look at this", "platforms": "instagram"},
        files={"media": ("pic.png", io.BytesIO(png), "image/png")},
    )
    assert resp.status_code == 201, resp.text
    result = resp.json()["results"][0]
    assert result["status"] == "published"

    content = client.get(f"/api/contents/{result['content_id']}").json()
    assert len(content["media_urls"]) == 1
    assert content["media_urls"][0].endswith(".png")
    assert "uploads" in content["media_urls"][0].replace("\\", "/")


def test_compose_platform_without_account_fails_per_platform(client):
    _add_account(client, "twitter")
    resp = client.post(
        "/api/compose",
        data={"text": "multi-platform", "platforms": "twitter,youtube"},
    )
    assert resp.status_code == 201, resp.text
    by_platform = {r["platform"]: r for r in resp.json()["results"]}
    assert by_platform["twitter"]["status"] == "published"
    assert by_platform["youtube"]["status"] == "failed"
    assert "No active account" in by_platform["youtube"]["publish_result"]["error"]


def test_compose_requires_text_or_media(client):
    _add_account(client, "twitter")
    resp = client.post("/api/compose", data={"text": "  ", "platforms": "twitter"})
    assert resp.status_code == 400


def test_compose_rejects_unsupported_media(client):
    _add_account(client, "twitter")
    resp = client.post(
        "/api/compose",
        data={"text": "x", "platforms": "twitter"},
        files={"media": ("evil.exe", io.BytesIO(b"MZ"), "application/octet-stream")},
    )
    assert resp.status_code == 400


def test_compose_requires_platform(client):
    resp = client.post("/api/compose", data={"text": "x", "platforms": " ,"})
    assert resp.status_code == 400
