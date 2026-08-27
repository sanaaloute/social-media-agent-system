"""Runtime settings: API, DB overrides, and consumer wiring (§9).

Verifies that changing a setting on the settings page actually changes the
behavior of publishers (dry_run), the rate limiter (daily cap), and that
validation rejects bad values before anything is written.
"""
from sqlmodel import select

from src.core.models import AuditLog, PlatformAccount
from src.core import runtime_settings
from src.publishers import get_adapter
from src.utils.crypto import get_cipher
from src.utils.rate_limiter import RateLimiter


def test_get_settings_defaults(client):
    settings = {s["key"]: s for s in client.get("/api/settings").json()}
    assert set(settings) == set(runtime_settings.OVERRIDABLE_KEYS)
    assert settings["dry_run"]["value"] is True  # DRY_RUN=true in test env
    assert settings["dry_run"]["overridden"] is False
    assert settings["llm_provider"]["choices"] == ["ollama", "openrouter", "claude", "openai"]


def test_dry_run_override_changes_adapter_behavior(client):
    resp = client.put("/api/settings", json={"values": {"dry_run": False}})
    assert resp.status_code == 200, resp.text
    settings = {s["key"]: s for s in resp.json()}
    assert settings["dry_run"]["value"] is False
    assert settings["dry_run"]["overridden"] is True

    # An account WITH a token now leaves dry-run (env said true, DB says false).
    account = PlatformAccount(
        platform="twitter", username="@x",
        tokens_enc=get_cipher().encrypt({"access_token": "t"}),
    )
    assert get_adapter(account).dry_run is False

    # Clearing the override restores the env value.
    resp = client.put("/api/settings", json={"values": {"dry_run": None}})
    settings = {s["key"]: s for s in resp.json()}
    assert settings["dry_run"]["value"] is True
    assert settings["dry_run"]["overridden"] is False


def test_rate_limit_override_changes_limiter(client):
    client.put("/api/settings", json={"values": {"max_posts_per_account_per_day": 1}})
    limiter = RateLimiter("twitter", account_id="acct-settings-1")
    assert limiter.limit == 1
    assert limiter.acquire() is True
    assert limiter.acquire() is False


def test_invalid_values_rejected_and_nothing_written(client):
    resp = client.put("/api/settings", json={"values": {"llm_provider": "chatgpt"}})
    assert resp.status_code == 400
    resp = client.put("/api/settings", json={"values": {"max_posts_per_account_per_day": 0}})
    assert resp.status_code == 400
    resp = client.put("/api/settings", json={"values": {"not_a_setting": 1}})
    assert resp.status_code == 400

    # Rejected batch must not have persisted anything.
    settings = {s["key"]: s for s in client.get("/api/settings").json()}
    assert all(s["overridden"] is False for s in settings.values())


def test_settings_changes_are_audited(client, session):
    client.put("/api/settings", json={"values": {"video_provider": "falai"}})
    rows = session.exec(
        select(AuditLog).where(AuditLog.action == "settings_updated")
    ).all()
    assert len(rows) == 1
    assert rows[0].detail["changed"] == {"video_provider": "falai"}
