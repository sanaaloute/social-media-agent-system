"""X (Twitter) publishing via API v2, media via v1.1 upload (design doc §4.1).

Tweets are created with POST `https://api.twitter.com/2/tweets`. Media must
first be uploaded to the v1.1 endpoint
`https://upload.twitter.com/1.1/media/upload.json` (multipart), then
referenced by ``media_ids`` on the v2 tweet body.
"""
import logging
import os
from typing import Any, Dict, List

import httpx

from src.publishers.base import HTTP_TIMEOUT, PublishResult, PublisherAdapter

logger = logging.getLogger(__name__)

TWEETS_URL = "https://api.twitter.com/2/tweets"
MEDIA_UPLOAD_URL = "https://upload.twitter.com/1.1/media/upload.json"
ME_URL = "https://api.twitter.com/2/users/me"

# v1.1 upload accepts a plain OAuth2 user-context bearer token for app-only
# read/write apps; accounts with OAuth1.0a user context would need signing
# here instead — kept simple per design doc §4.1.


class TwitterAdapter(PublisherAdapter):
    @property
    def platform_name(self) -> str:
        return "twitter"

    @property
    def _access_token(self) -> str:
        return self.tokens.get("access_token", "")

    @property
    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self._access_token}"}

    async def authenticate(self) -> bool:
        if self.dry_run:
            return True
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                resp = await client.get(ME_URL, headers=self._headers)
                resp.raise_for_status()
                return True
        except Exception as exc:  # noqa: BLE001 — adapter boundary
            logger.error("Twitter auth check failed: %s", exc)
            return False

    async def publish_text(self, content: str, metadata: dict) -> PublishResult:
        if guard := self._guard_rate_limit():
            return guard
        if self.dry_run:
            return self._dry_result(f"tweet: {content[:80]}")
        try:
            return await self._create_tweet(content, media_ids=[])
        except Exception as exc:  # noqa: BLE001
            return self._error_result(exc)

    async def publish_image(
        self, image_path: str, caption: str, metadata: dict
    ) -> PublishResult:
        if guard := self._guard_rate_limit():
            return guard
        if self.dry_run:
            return self._dry_result(f"tweet with image: {image_path}")
        try:
            media_id = await self._upload_media(image_path)
            return await self._create_tweet(caption, media_ids=[media_id])
        except Exception as exc:  # noqa: BLE001
            return self._error_result(exc)

    async def publish_video(
        self, video_path: str, title: str, description: str, metadata: dict
    ) -> PublishResult:
        if guard := self._guard_rate_limit():
            return guard
        if self.dry_run:
            return self._dry_result(f"tweet with video: {video_path}")
        try:
            media_id = await self._upload_media(video_path)
            text = f"{title}\n\n{description}".strip() or title
            return await self._create_tweet(text, media_ids=[media_id])
        except Exception as exc:  # noqa: BLE001
            return self._error_result(exc)

    # ------------------------------------------------------------------

    async def _upload_media(self, media_path: str) -> str:
        """v1.1 simple upload: multipart form -> media_id_string."""
        mime = "video/mp4" if media_path.lower().endswith(".mp4") else "image/png"
        filename = os.path.basename(media_path)
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            with open(media_path, "rb") as fh:
                resp = await client.post(
                    MEDIA_UPLOAD_URL,
                    headers=self._headers,
                    files={"media": (filename, fh, mime)},
                )
            resp.raise_for_status()
            return resp.json()["media_id_string"]

    async def _create_tweet(
        self, text: str, media_ids: List[str]
    ) -> PublishResult:
        payload: Dict[str, Any] = {"text": text}
        if media_ids:
            payload["media"] = {"media_ids": media_ids}
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.post(
                TWEETS_URL,
                json=payload,
                headers={**self._headers, "Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json().get("data", {})
        tweet_id = data.get("id")
        username = self.account.username
        return PublishResult(
            success=True,
            platform=self.platform_name,
            remote_id=tweet_id,
            url=f"https://x.com/{username}/status/{tweet_id}"
            if tweet_id
            else None,
            raw=data,
        )
