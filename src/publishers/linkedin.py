"""LinkedIn publishing via the UGC Posts API (design doc §4.1).

All posts go through POST `https://api.linkedin.com/v2/ugcPosts` with the
author URN from the account credentials (e.g. ``urn:li:person:xxx``).
Text posts use ``shareCommentary`` only; image posts attach a previously
uploaded media URN (passed in via ``metadata["media_urn"]``) as
``shareMedia``. Video is published the same way — LinkedIn requires the
asset to be uploaded to their media service first.
"""
import logging
from typing import Any, Dict, List

import httpx

from src.publishers.base import HTTP_TIMEOUT, PublishResult, PublisherAdapter

logger = logging.getLogger(__name__)

UGC_POSTS_URL = "https://api.linkedin.com/v2/ugcPosts"
ME_URL = "https://api.linkedin.com/v2/me"


class LinkedInAdapter(PublisherAdapter):
    @property
    def platform_name(self) -> str:
        return "linkedin"

    @property
    def _access_token(self) -> str:
        return self.tokens.get("access_token", "")

    @property
    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._access_token}",
            "X-Restli-Protocol-Version": "2.0.0",
            "Content-Type": "application/json",
        }

    async def authenticate(self) -> bool:
        if self.dry_run:
            return True
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                resp = await client.get(ME_URL, headers=self._headers)
                resp.raise_for_status()
                return True
        except Exception as exc:  # noqa: BLE001 — adapter boundary
            logger.error("LinkedIn auth check failed: %s", exc)
            return False

    async def publish_text(self, content: str, metadata: dict) -> PublishResult:
        if guard := self._guard_rate_limit():
            return guard
        if self.dry_run:
            return self._dry_result(f"text post: {content[:80]}")
        try:
            return await self._create_post(content, media=[])
        except Exception as exc:  # noqa: BLE001
            return self._error_result(exc)

    async def publish_image(
        self, image_path: str, caption: str, metadata: dict
    ) -> PublishResult:
        """image_path must be a LinkedIn media URN in metadata["media_urn"],
        or a URL/URN passed as image_path (LinkedIn needs pre-uploaded assets).
        """
        if guard := self._guard_rate_limit():
            return guard
        if self.dry_run:
            return self._dry_result(f"image: {image_path}")
        media_urn = metadata.get("media_urn", image_path)
        try:
            return await self._create_post(
                caption,
                media=[
                    {
                        "status": "READY",
                        "description": {"text": caption[:512]},
                        "media": media_urn,
                        "title": {"text": metadata.get("title", "")},
                    }
                ],
            )
        except Exception as exc:  # noqa: BLE001
            return self._error_result(exc)

    async def publish_video(
        self, video_path: str, title: str, description: str, metadata: dict
    ) -> PublishResult:
        """Same UGC shape as images; the video asset must be pre-uploaded and
        its URN supplied via metadata["media_urn"]."""
        if guard := self._guard_rate_limit():
            return guard
        if self.dry_run:
            return self._dry_result(f"video: {video_path}")
        media_urn = metadata.get("media_urn", video_path)
        try:
            return await self._create_post(
                f"{title}\n\n{description}".strip(),
                media=[
                    {
                        "status": "READY",
                        "description": {"text": description[:512]},
                        "media": media_urn,
                        "title": {"text": title},
                    }
                ],
            )
        except Exception as exc:  # noqa: BLE001
            return self._error_result(exc)

    # ------------------------------------------------------------------

    async def _create_post(
        self, commentary: str, media: List[Dict[str, Any]]
    ) -> PublishResult:
        body = {
            "author": self.credentials.get("author_urn", ""),
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": commentary},
                    "shareMediaCategory": "IMAGE" if media else "NONE",
                    "media": media,
                }
            },
            "visibility": {
                "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
            },
        }
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.post(
                UGC_POSTS_URL, json=body, headers=self._headers
            )
            resp.raise_for_status()
            data = resp.json()
        post_id = data.get("id", "")
        return PublishResult(
            success=True,
            platform=self.platform_name,
            remote_id=post_id,
            url=f"https://www.linkedin.com/feed/update/{post_id}"
            if post_id
            else None,
            raw=data,
        )
