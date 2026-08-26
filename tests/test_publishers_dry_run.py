"""API adapters in dry-run mode + HITL gate enforcement (§4.1, §5.2)."""
import asyncio

import pytest

from src.core.models import ApprovalStatus, GeneratedContent, PlatformAccount
from src.publishers import get_adapter
from src.services import publish_service

API_PLATFORMS = ["facebook", "instagram", "linkedin", "youtube", "twitter", "tiktok"]

# Content type each platform can accept (per adapter contracts).
PLATFORM_CONTENT = {
    "facebook": {"type": "text", "text": "hello world", "metadata": {}},
    "instagram": {
        "type": "image",
        "image_path": "./x.png",
        "caption": "hi",
        "metadata": {},
    },
    "linkedin": {"type": "text", "text": "hello world", "metadata": {}},
    "youtube": {
        "type": "video",
        "video_path": "./x.mp4",
        "title": "t",
        "description": "d",
        "metadata": {},
    },
    "twitter": {"type": "text", "text": "hello world", "metadata": {}},
    "tiktok": {
        "type": "video",
        "video_path": "./x.mp4",
        "title": "t",
        "description": "d",
        "metadata": {},
    },
}


@pytest.mark.parametrize("platform", API_PLATFORMS)
async def test_api_adapter_dry_run(platform):
    account = PlatformAccount(platform=platform, username="acct")
    adapter = get_adapter(account)
    assert adapter.dry_run is True  # DRY_RUN=true in test env
    result = await adapter.publish(PLATFORM_CONTENT[platform])
    assert result.success is True
    assert result.dry_run is True
    assert result.remote_id.startswith("dryrun-")


def test_unknown_platform_raises():
    account = PlatformAccount(platform="myspace", username="acct")
    with pytest.raises(KeyError):
        get_adapter(account)


def test_hitl_gate_blocks_unapproved_content(session):
    """publish_service must refuse content that never passed review (§5.3)."""
    content = GeneratedContent(
        task_id="t1",
        platform="twitter",
        text="unreviewed",
        status=ApprovalStatus.REVIEW.value,
    )
    session.add(content)
    session.commit()

    with pytest.raises(PermissionError):
        asyncio.run(publish_service.publish_content(session, content.id))

    session.refresh(content)
    assert content.status == ApprovalStatus.REVIEW.value  # untouched
