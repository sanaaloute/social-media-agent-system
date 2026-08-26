"""Live-mode publisher behaviour with a fake httpx.AsyncClient (no network).

DRY_RUN stays true in the environment; tests flip ``adapter.dry_run``
directly after construction to exercise the live code paths.
"""
import logging

import httpx
import pytest

import src.publishers.browser_base as browser_base
from src.core.models import PlatformAccount
from src.publishers.browser_tiktok import BrowserTikTokAdapter
from src.publishers.facebook import FacebookAdapter
from src.publishers.youtube import YouTubeAdapter
from src.utils.crypto import get_cipher


class FakeResponse:
    def __init__(self, json_data=None, headers=None):
        self._json = json_data or {}
        self.headers = headers or {}

    def json(self):
        return self._json

    def raise_for_status(self):
        return None


class FakeClient:
    """AsyncClient stand-in: records every request, answers via `responder`."""

    instances: list = []
    responder = None  # callable(method, url, kwargs) -> FakeResponse (or raises)

    def __init__(self, **kwargs):
        self.calls = []
        FakeClient.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def _handle(self, method, url, kwargs):
        self.calls.append({"method": method, "url": str(url), "kwargs": kwargs})
        return FakeClient.responder(method, str(url), kwargs)

    async def get(self, url, **kwargs):
        return self._handle("GET", url, kwargs)

    async def post(self, url, **kwargs):
        return self._handle("POST", url, kwargs)

    async def put(self, url, **kwargs):
        return self._handle("PUT", url, kwargs)


@pytest.fixture
def fake_client(monkeypatch):
    FakeClient.instances = []
    FakeClient.responder = None
    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    yield FakeClient
    FakeClient.instances = []
    FakeClient.responder = None


def make_account(platform: str, credentials: dict | None = None) -> PlatformAccount:
    cipher = get_cipher()
    return PlatformAccount(
        platform=platform,
        username="acct",
        tokens_enc=cipher.encrypt({"access_token": "tok"}),
        credentials_enc=cipher.encrypt(credentials or {}),
    )


def all_calls() -> list:
    return [call for inst in FakeClient.instances for call in inst.calls]


def assert_all_content_is_bytes():
    for call in all_calls():
        if "content" in call["kwargs"]:
            assert isinstance(call["kwargs"]["content"], bytes), (
                f"{call['method']} {call['url']} sent a non-bytes content body"
            )


# --------------------------------------------------------------------
# 1. Video uploads must send bytes, not raw file objects
# --------------------------------------------------------------------


async def test_facebook_video_upload_sends_bytes(fake_client, tmp_path):
    def responder(method, url, kwargs):
        data = kwargs.get("data") or {}
        if data.get("upload_phase") == "start":
            return FakeResponse(
                {"video_id": "v1", "upload_url": "https://rupload.example.com/x"}
            )
        return FakeResponse({"success": True})  # byte upload + finish phase

    fake_client.responder = responder
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"\x00" * 64)

    adapter = FacebookAdapter(make_account("facebook", {"page_id": "p"}))
    adapter.dry_run = False
    result = await adapter.publish_video(str(video), "t", "d", {})

    assert result.success is True
    assert result.remote_id == "v1"
    assert_all_content_is_bytes()


async def test_youtube_video_upload_sends_bytes(fake_client, tmp_path):
    def responder(method, url, kwargs):
        if method == "POST":  # open the resumable session
            return FakeResponse(
                {}, headers={"Location": "https://upload.example.com/session"}
            )
        return FakeResponse({"id": "vid123"})  # PUT of the file bytes

    fake_client.responder = responder
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"\x00" * 64)

    adapter = YouTubeAdapter(make_account("youtube"))
    adapter.dry_run = False
    result = await adapter.publish_video(str(video), "t", "d", {})

    assert result.success is True
    assert result.remote_id == "vid123"
    assert result.url == "https://www.youtube.com/watch?v=vid123"
    assert_all_content_is_bytes()


# --------------------------------------------------------------------
# 2. Auth failures must not leak the token into logs; token goes via header
# --------------------------------------------------------------------


def _auth_error(url: str) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", url)
    response = httpx.Response(400, request=request)
    return httpx.HTTPStatusError(
        f"Client error '400' for url '{url}'", request=request, response=response
    )


async def test_facebook_auth_failure_logs_no_token(fake_client, caplog):
    def responder(method, url, kwargs):
        raise _auth_error(
            "https://graph.facebook.com/v21.0/me?access_token=tok"
        )

    fake_client.responder = responder
    adapter = FacebookAdapter(make_account("facebook", {"page_id": "p"}))
    adapter.dry_run = False

    with caplog.at_level(logging.ERROR):
        assert await adapter.authenticate() is False

    assert "tok" not in caplog.text
    call = all_calls()[0]
    assert call["kwargs"]["headers"] == {"Authorization": "Bearer tok"}
    assert "access_token" not in (call["kwargs"].get("params") or {})


async def test_youtube_auth_failure_logs_no_token(fake_client, caplog):
    def responder(method, url, kwargs):
        raise _auth_error(
            "https://www.googleapis.com/oauth2/v3/tokeninfo?access_token=tok"
        )

    fake_client.responder = responder
    adapter = YouTubeAdapter(make_account("youtube"))
    adapter.dry_run = False

    with caplog.at_level(logging.ERROR):
        assert await adapter.authenticate() is False

    assert "tok" not in caplog.text
    call = all_calls()[0]
    assert call["url"] == "https://www.googleapis.com/youtube/v3/channels"
    assert call["kwargs"]["headers"] == {"Authorization": "Bearer tok"}
    assert "access_token" not in (call["kwargs"].get("params") or {})


# --------------------------------------------------------------------
# 3.-5. Rate-limit quota semantics
# --------------------------------------------------------------------


async def test_dry_run_consumes_no_quota():
    adapter = FacebookAdapter(make_account("facebook", {"page_id": "p"}))
    assert adapter.dry_run is True  # DRY_RUN=true in test env
    before = adapter.rate_limiter.remaining()
    result = await adapter.publish({"type": "text", "text": "hi", "metadata": {}})
    assert result.success is True
    assert result.dry_run is True
    assert adapter.rate_limiter.remaining() == before


async def test_failed_live_publish_refunds_quota(fake_client):
    def responder(method, url, kwargs):
        raise httpx.ConnectError("boom")

    fake_client.responder = responder
    adapter = FacebookAdapter(make_account("facebook", {"page_id": "p"}))
    adapter.dry_run = False
    before = adapter.rate_limiter.remaining()

    result = await adapter.publish({"type": "text", "text": "hi", "metadata": {}})

    assert result.success is False
    assert adapter.rate_limiter.remaining() == before


async def test_unsupported_content_consumes_no_quota():
    adapter = YouTubeAdapter(make_account("youtube"))
    adapter.dry_run = False  # even live mode must not burn quota on rejects
    before = adapter.rate_limiter.remaining()

    result = await adapter.publish({"type": "text", "text": "hi", "metadata": {}})

    assert result.success is False
    assert "text-only" in result.error
    assert adapter.rate_limiter.remaining() == before


# --------------------------------------------------------------------
# 6. Browser adapters follow settings.dry_run (no tokens held)
# --------------------------------------------------------------------


def test_browser_adapter_dry_run_follows_settings(monkeypatch):
    account = PlatformAccount(platform="tiktok", username="acct")  # no tokens

    monkeypatch.setattr(
        browser_base.runtime_settings, "get_value", lambda key: False
    )
    assert BrowserTikTokAdapter(account).dry_run is False

    monkeypatch.setattr(
        browser_base.runtime_settings, "get_value", lambda key: True
    )
    assert BrowserTikTokAdapter(account).dry_run is True
