"""Platform publishing adapters (design doc §7).

`get_adapter(account)` is the single entry point: it returns a browser
adapter when the account is flagged ``use_browser`` or when the platform
has no official API adapter, otherwise the official API adapter.
"""
from src.core.models import PlatformAccount
from src.publishers.base import PublishResult, PublisherAdapter
from src.publishers.browser_base import BrowserPublisherAdapter
from src.publishers.browser_tiktok import BrowserTikTokAdapter
from src.publishers.browser_twitter import BrowserTwitterAdapter
from src.publishers.facebook import FacebookAdapter
from src.publishers.instagram import InstagramAdapter
from src.publishers.linkedin import LinkedInAdapter
from src.publishers.tiktok import TikTokAdapter
from src.publishers.twitter import TwitterAdapter
from src.publishers.youtube import YouTubeAdapter

API_ADAPTERS: dict[str, type[PublisherAdapter]] = {
    "facebook": FacebookAdapter,
    "instagram": InstagramAdapter,
    "linkedin": LinkedInAdapter,
    "youtube": YouTubeAdapter,
    "twitter": TwitterAdapter,
    "tiktok": TikTokAdapter,
}

BROWSER_ADAPTERS: dict[str, type[BrowserPublisherAdapter]] = {
    "twitter": BrowserTwitterAdapter,
    "tiktok": BrowserTikTokAdapter,
}

# Canonical platform registry (§4): what the system supports, via which
# channel, and which content types each platform accepts. Single source of
# truth for intake validation and the panel's platform picker.
SUPPORTED_PLATFORMS: dict[str, dict] = {
    "facebook": {"via": "api", "media": ["text", "image", "video"]},
    "instagram": {"via": "api", "media": ["image", "video"]},
    "linkedin": {"via": "api", "media": ["text", "image", "video"]},
    "youtube": {"via": "api", "media": ["video"]},
    "twitter": {"via": "api+browser", "media": ["text", "image", "video"]},
    "tiktok": {"via": "api+browser", "media": ["image", "video"]},
}


def validate_platforms(platforms: list[str]) -> list[str]:
    """Normalize platform names (case-insensitive) and reject unknown ones."""
    normalized = [p.strip().lower() for p in platforms if p and p.strip()]
    unknown = sorted(set(normalized) - set(SUPPORTED_PLATFORMS))
    if unknown:
        raise ValueError(
            f"Unsupported platform(s): {unknown}. "
            f"Supported: {sorted(SUPPORTED_PLATFORMS)}"
        )
    return normalized


def get_adapter(account: PlatformAccount) -> PublisherAdapter:
    """Browser adapter when account.use_browser or platform has no API
    adapter; else the official API adapter."""
    platform = account.platform.lower()
    if account.use_browser or platform not in API_ADAPTERS:
        try:
            return BROWSER_ADAPTERS[platform](account)
        except KeyError:
            known = sorted(set(API_ADAPTERS) | set(BROWSER_ADAPTERS))
            raise KeyError(
                f"No publisher adapter for platform {account.platform!r}. "
                f"Known platforms: {known}"
            ) from None
    return API_ADAPTERS[platform](account)


__all__ = [
    "API_ADAPTERS",
    "BROWSER_ADAPTERS",
    "SUPPORTED_PLATFORMS",
    "PublishResult",
    "PublisherAdapter",
    "BrowserPublisherAdapter",
    "get_adapter",
    "validate_platforms",
]
