"""Instagram publishing via the Graph API content-publishing flow (§4.1).

Instagram professional accounts publish in three steps:
  1. POST `/{ig-user-id}/media`         — create a media container
  2. POST `/{ig-user-id}/media_publish` — publish the container
Text-only posts are not supported: IG requires media on every post.
Media must be a publicly reachable URL (image_url / video_url).
"""
import logging
from typing import Any, Dict
from urllib.parse import urljoin

import httpx

from src.publishers.base import HTTP_TIMEOUT, PublishResult, PublisherAdapter

logger = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.facebook.com/v21.0/"


class InstagramAdapter(PublisherAdapter):
    @property
    def platform_name(self) -> str:
        return "instagram"

    @property
    def _ig_user_id(self) -> str:
        return self.credentials.get("ig_user_id", "")

    @property
    def _access_token(self) -> str:
        return self.tokens.get("access_token", "")

    async def authenticate(self) -> bool:
        if self.dry_run:
            return True
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                resp = await client.get(
                    urljoin(GRAPH_BASE, self._ig_user_id),
                    params={"fields": "id,username"},
                    headers={"Authorization": f"Bearer {self._access_token}"},
                )
                resp.raise_for_status()
                return True
        except Exception as exc:  # noqa: BLE001 — adapter boundary
            # Never log the exception object: httpx error messages embed
            # the request URL, which used to carry the access token.
            status = (
                exc.response.status_code
                if isinstance(exc, httpx.HTTPStatusError)
                else None
            )
            logger.error(
                "Instagram auth check failed: %s (status=%s)",
                type(exc).__name__,
                status,
            )
            return False

    async def publish_text(self, content: str, metadata: dict) -> PublishResult:
        # Reject before the rate-limit guard: unsupported content must not
        # consume daily quota.
        return PublishResult(
            success=False,
            platform=self.platform_name,
            error=(
                "Instagram does not support text-only posts; "
                "provide an image or video."
            ),
        )

    async def publish_image(
        self, image_path: str, caption: str, metadata: dict
    ) -> PublishResult:
        if guard := self._guard_rate_limit():
            return guard
        if self.dry_run:
            return self._dry_result(f"image: {image_path}")
        try:
            creation_id = await self._create_container(
                {"image_url": image_path, "caption": caption}
            )
            return await self._publish_container(creation_id)
        except Exception as exc:  # noqa: BLE001
            return self._error_result(exc)

    async def publish_video(
        self, video_path: str, title: str, description: str, metadata: dict
    ) -> PublishResult:
        """Videos publish as Reels (media_type=REELS); caption = title + body."""
        if guard := self._guard_rate_limit():
            return guard
        if self.dry_run:
            return self._dry_result(f"reel: {video_path}")
        caption = f"{title}\n\n{description}".strip()
        try:
            creation_id = await self._create_container(
                {
                    "video_url": video_path,
                    "caption": caption,
                    "media_type": "REELS",
                }
            )
            return await self._publish_container(creation_id)
        except Exception as exc:  # noqa: BLE001
            return self._error_result(exc)

    # ------------------------------------------------------------------
    # Container flow helpers
    # ------------------------------------------------------------------

    async def _create_container(self, payload: Dict[str, Any]) -> str:
        """Step 1: POST /{ig-user-id}/media -> creation (container) id."""
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.post(
                urljoin(GRAPH_BASE, f"{self._ig_user_id}/media"),
                data={**payload, "access_token": self._access_token},
            )
            resp.raise_for_status()
            return resp.json()["id"]

    async def _publish_container(self, creation_id: str) -> PublishResult:
        """Step 2: POST /{ig-user-id}/media_publish with the container id."""
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.post(
                urljoin(GRAPH_BASE, f"{self._ig_user_id}/media_publish"),
                data={
                    "creation_id": creation_id,
                    "access_token": self._access_token,
                },
            )
            resp.raise_for_status()
            data = resp.json()
        return PublishResult(
            success=True,
            platform=self.platform_name,
            remote_id=data.get("id"),
            raw={"creation_id": creation_id, "publish": data},
        )
