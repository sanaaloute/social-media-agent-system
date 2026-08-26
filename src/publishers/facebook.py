"""Facebook Page publishing via the Graph API v21.0 (design doc §4.1).

Text/link posts go to `/{page-id}/feed`, images to `/{page-id}/photos`,
and videos are published as Reels via the two-phase
`/{page-id}/video_reels` upload (start -> finish). The Page access token
comes from the account's stored tokens, the page id from its credentials.
"""
import logging
import os
from typing import Any, Dict
from urllib.parse import urljoin

import httpx

from src.publishers.base import HTTP_TIMEOUT, PublishResult, PublisherAdapter

logger = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.facebook.com/v21.0/"


class FacebookAdapter(PublisherAdapter):
    @property
    def platform_name(self) -> str:
        return "facebook"

    @property
    def _page_id(self) -> str:
        return self.credentials.get("page_id", "")

    @property
    def _access_token(self) -> str:
        return self.tokens.get("access_token", "")

    async def authenticate(self) -> bool:
        if self.dry_run:
            return True
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                resp = await client.get(
                    urljoin(GRAPH_BASE, "me"),
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
                "Facebook auth check failed: %s (status=%s)",
                type(exc).__name__,
                status,
            )
            return False

    async def publish_text(self, content: str, metadata: dict) -> PublishResult:
        if guard := self._guard_rate_limit():
            return guard
        if self.dry_run:
            return self._dry_result(f"text post: {content[:80]}")
        try:
            params: Dict[str, Any] = {
                "message": content,
                "access_token": self._access_token,
            }
            if link := metadata.get("link"):
                params["link"] = link
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                resp = await client.post(
                    urljoin(GRAPH_BASE, f"{self._page_id}/feed"), data=params
                )
                resp.raise_for_status()
                data = resp.json()
            return PublishResult(
                success=True,
                platform=self.platform_name,
                remote_id=data.get("id"),
                url=data.get("permalink_url"),
                raw=data,
            )
        except Exception as exc:  # noqa: BLE001
            return self._error_result(exc)

    async def publish_image(
        self, image_path: str, caption: str, metadata: dict
    ) -> PublishResult:
        if guard := self._guard_rate_limit():
            return guard
        if self.dry_run:
            return self._dry_result(f"photo: {image_path}")
        try:
            params: Dict[str, Any] = {
                "caption": caption,
                "access_token": self._access_token,
            }
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                if image_path.startswith(("http://", "https://")):
                    params["url"] = image_path
                    resp = await client.post(
                        urljoin(GRAPH_BASE, f"{self._page_id}/photos"),
                        data=params,
                    )
                else:
                    with open(image_path, "rb") as fh:
                        resp = await client.post(
                            urljoin(GRAPH_BASE, f"{self._page_id}/photos"),
                            data=params,
                            files={"source": fh},
                        )
                resp.raise_for_status()
                data = resp.json()
            return PublishResult(
                success=True,
                platform=self.platform_name,
                remote_id=data.get("id") or data.get("post_id"),
                raw=data,
            )
        except Exception as exc:  # noqa: BLE001
            return self._error_result(exc)

    async def publish_video(
        self, video_path: str, title: str, description: str, metadata: dict
    ) -> PublishResult:
        """Publish as a Reel: start upload phase, upload bytes, finish (§4.1)."""
        if guard := self._guard_rate_limit():
            return guard
        if self.dry_run:
            return self._dry_result(f"reel: {video_path}")
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                # Phase 1: START — reserve a video id and upload URL.
                resp = await client.post(
                    urljoin(GRAPH_BASE, f"{self._page_id}/video_reels"),
                    data={
                        "upload_phase": "start",
                        "access_token": self._access_token,
                    },
                )
                resp.raise_for_status()
                start_data = resp.json()
                video_id = start_data["video_id"]
                upload_url = start_data["upload_url"]

                # Phase 2: transfer the file bytes to the upload URL.
                file_size = os.path.getsize(video_path)
                with open(video_path, "rb") as fh:
                    resp = await client.post(
                        upload_url,
                        headers={
                            "Authorization": f"OAuth {self._access_token}",
                            "offset": "0",
                            "file_size": str(file_size),
                        },
                        content=fh.read(),
                    )
                    resp.raise_for_status()

                # Phase 3: FINISH — attach metadata and publish.
                resp = await client.post(
                    urljoin(GRAPH_BASE, f"{self._page_id}/video_reels"),
                    data={
                        "upload_phase": "finish",
                        "video_id": video_id,
                        "title": title,
                        "description": description,
                        "access_token": self._access_token,
                    },
                )
                resp.raise_for_status()
                finish_data = resp.json()
            return PublishResult(
                success=True,
                platform=self.platform_name,
                remote_id=video_id,
                raw={"start": start_data, "finish": finish_data},
            )
        except Exception as exc:  # noqa: BLE001
            return self._error_result(exc)
