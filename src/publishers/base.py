"""Publisher adapter base contract (design doc §7.2).

Every platform adapter — official API or browser automation — implements
`PublisherAdapter`. Adapters never raise past their own boundary: any
transport/platform error is wrapped into `PublishResult(success=False, ...)`.
In dry-run mode (settings.dry_run, or the account has no access token) every
publish_* method short-circuits into a simulated success before any HTTP.
"""
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

from src.core import runtime_settings
from src.core.models import PlatformAccount
from src.utils.crypto import get_cipher
from src.utils.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

HTTP_TIMEOUT = 30.0  # seconds, applied to every httpx.AsyncClient


class PublishResult(BaseModel):
    """Outcome of one publish attempt (§7.2)."""

    success: bool
    platform: str
    remote_id: Optional[str] = None
    url: Optional[str] = None
    dry_run: bool = False
    raw: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None


class PublisherAdapter(ABC):
    """Abstract per-account publisher. One instance per PlatformAccount."""

    def __init__(self, account: PlatformAccount):
        self.account = account
        self.account_id = account.id
        self.credentials: Dict[str, Any] = (
            get_cipher().decrypt(account.credentials_enc)
            if account.credentials_enc
            else {}
        )
        self.tokens: Dict[str, Any] = (
            get_cipher().decrypt(account.tokens_enc) if account.tokens_enc else {}
        )
        self.rate_limiter = RateLimiter(self.platform_name, account.id)
        self.dry_run = (
            runtime_settings.get_value("dry_run")
            or not self.tokens.get("access_token")
        )

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """Canonical platform key, e.g. 'facebook', 'tiktok'."""

    @abstractmethod
    async def authenticate(self) -> bool:
        """Verify the stored credentials/tokens are usable."""

    @abstractmethod
    async def publish_text(self, content: str, metadata: dict) -> PublishResult:
        """Publish a text-only post."""

    @abstractmethod
    async def publish_image(
        self, image_path: str, caption: str, metadata: dict
    ) -> PublishResult:
        """Publish an image post with caption."""

    @abstractmethod
    async def publish_video(
        self, video_path: str, title: str, description: str, metadata: dict
    ) -> PublishResult:
        """Publish a video post."""

    async def publish(self, content: dict) -> PublishResult:
        """Dispatch on content["type"] (§7.2).

        Expected shapes:
          {"type": "text",  "text": str, "metadata": {...}}
          {"type": "image", "image_path": str, "caption": str, "metadata": {...}}
          {"type": "video", "video_path": str, "title": str,
           "description": str, "metadata": {...}}
        """
        metadata = content.get("metadata", {})
        content_type = content.get("type", "text")
        if content_type == "text":
            return await self.publish_text(content.get("text", ""), metadata)
        if content_type == "image":
            return await self.publish_image(
                content.get("image_path", ""), content.get("caption", ""), metadata
            )
        if content_type == "video":
            return await self.publish_video(
                content.get("video_path", ""),
                content.get("title", ""),
                content.get("description", ""),
                metadata,
            )
        return PublishResult(
            success=False,
            platform=self.platform_name,
            error=f"Unsupported content type: {content_type!r}",
        )

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _guard_rate_limit(self) -> Optional[PublishResult]:
        """Return a failed PublishResult when the daily cap is hit, else None.

        Call at the top of every publish_* implementation. Dry-run mode
        never consumes quota.
        """
        if self.dry_run:
            return None
        if self.rate_limiter.acquire():
            return None
        logger.warning(
            "Daily post cap reached for %s account %s",
            self.platform_name,
            self.account_id,
        )
        return PublishResult(
            success=False,
            platform=self.platform_name,
            error=(
                f"Daily post cap reached for {self.platform_name} "
                f"(limit {self.rate_limiter.limit}/day)"
            ),
        )

    def _dry_result(self, content_desc: str) -> PublishResult:
        """Simulated success used in dry-run mode (§7.2)."""
        return PublishResult(
            success=True,
            platform=self.platform_name,
            remote_id=f"dryrun-{uuid4().hex[:12]}",
            dry_run=True,
            raw={"simulated": content_desc},
        )

    def _error_result(self, exc: Exception) -> PublishResult:
        """Wrap any exception into a failed PublishResult (never raise).

        A live attempt made it past the rate-limit guard without
        publishing anything, so its slot is refunded.
        """
        if not self.dry_run:
            self.rate_limiter.refund()
        logger.error(
            "%s publish failed for account %s: %s",
            self.platform_name,
            self.account_id,
            exc,
        )
        return PublishResult(
            success=False, platform=self.platform_name, error=str(exc)
        )
