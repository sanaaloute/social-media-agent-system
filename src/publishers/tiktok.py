"""TikTok publishing via the Content Posting API v2 (design doc §4.1).

Direct posts init at `v2/post/publish/video/init/`; when
``metadata["draft"]`` is truthy the inbox init endpoint
`v2/post/publish/inbox/video/init/` is used instead, creating a creator
draft the user finishes in the TikTok app. Photo posts init at
`v2/post/publish/content/init/` with ``media_type=PHOTO``. Text-only posts
are not supported by the API.
"""
import logging
import os
from typing import Any, Dict

import httpx

from src.publishers.base import HTTP_TIMEOUT, PublishResult, PublisherAdapter

logger = logging.getLogger(__name__)

VIDEO_INIT_URL = "https://open.tiktokapis.com/v2/post/publish/video/init/"
INBOX_VIDEO_INIT_URL = (
    "https://open.tiktokapis.com/v2/post/publish/inbox/video/init/"
)
PHOTO_INIT_URL = "https://open.tiktokapis.com/v2/post/publish/content/init/"
CREATOR_INFO_URL = "https://open.tiktokapis.com/v2/post/publish/creator_info/query/"


class TikTokAdapter(PublisherAdapter):
    @property
    def platform_name(self) -> str:
        return "tiktok"

    @property
    def _access_token(self) -> str:
        return self.tokens.get("access_token", "")

    @property
    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json; charset=UTF-8",
        }

    async def authenticate(self) -> bool:
        if self.dry_run:
            return True
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                resp = await client.post(
                    CREATOR_INFO_URL, headers=self._headers
                )
                resp.raise_for_status()
                return True
        except Exception as exc:  # noqa: BLE001 — adapter boundary
            # Never log the exception object: httpx error messages embed
            # the request URL.
            status = (
                exc.response.status_code
                if isinstance(exc, httpx.HTTPStatusError)
                else None
            )
            logger.error(
                "TikTok auth check failed: %s (status=%s)",
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
            error="TikTok does not support text-only posts.",
        )

    async def publish_image(
        self, image_path: str, caption: str, metadata: dict
    ) -> PublishResult:
        """Photo post via content/init; image_path must be a public URL."""
        if guard := self._guard_rate_limit():
            return guard
        if self.dry_run:
            return self._dry_result(f"photo post: {image_path}")
        if not image_path.startswith(("http://", "https://")):
            return PublishResult(
                success=False,
                platform=self.platform_name,
                error=(
                    "TikTok photo posts require a publicly reachable "
                    f"image URL (PULL_FROM_URL), got: {image_path!r}"
                ),
            )
        try:
            body = {
                "post_info": {
                    "title": caption,
                    "privacy_level": metadata.get("privacy_level", "SELF_ONLY"),
                },
                "source_info": {
                    "source": "PULL_FROM_URL",
                    "photo_cover_index": 0,
                    "photo_images": [image_path],
                },
                "post_mode": "DIRECT_POST",
                "media_type": "PHOTO",
            }
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                resp = await client.post(
                    PHOTO_INIT_URL, json=body, headers=self._headers
                )
                resp.raise_for_status()
                data = resp.json().get("data", {})
            return PublishResult(
                success=True,
                platform=self.platform_name,
                remote_id=data.get("publish_id"),
                raw=data,
            )
        except Exception as exc:  # noqa: BLE001
            return self._error_result(exc)

    async def publish_video(
        self, video_path: str, title: str, description: str, metadata: dict
    ) -> PublishResult:
        """FILE_UPLOAD flow: init -> PUT bytes to the returned upload URL.

        metadata["draft"]=True switches to the inbox init endpoint so the
        video lands as a creator draft instead of posting directly (§4.1).
        """
        if guard := self._guard_rate_limit():
            return guard
        if self.dry_run:
            return self._dry_result(f"video: {video_path}")
        try:
            is_draft = bool(metadata.get("draft", False))
            init_url = INBOX_VIDEO_INIT_URL if is_draft else VIDEO_INIT_URL
            video_size = os.path.getsize(video_path)
            body: Dict[str, Any] = {
                "source_info": {
                    "source": "FILE_UPLOAD",
                    "video_size": video_size,
                    "chunk_size": video_size,
                    "total_chunk_count": 1,
                }
            }
            if not is_draft:
                body["post_info"] = {
                    "title": title or description[:150],
                    "privacy_level": metadata.get("privacy_level", "SELF_ONLY"),
                    "disable_duet": bool(metadata.get("disable_duet", False)),
                    "disable_comment": bool(
                        metadata.get("disable_comment", False)
                    ),
                    "disable_stitch": bool(metadata.get("disable_stitch", False)),
                }

            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                resp = await client.post(
                    init_url, json=body, headers=self._headers
                )
                resp.raise_for_status()
                data = resp.json().get("data", {})
                publish_id = data.get("publish_id")
                upload_url = data.get("upload_url")

                with open(video_path, "rb") as fh:
                    resp = await client.put(
                        upload_url,
                        content=fh.read(),
                        headers={
                            "Content-Type": "video/mp4",
                            "Content-Length": str(video_size),
                            "Content-Range": f"bytes 0-{video_size - 1}/{video_size}",
                        },
                    )
                    resp.raise_for_status()
            return PublishResult(
                success=True,
                platform=self.platform_name,
                remote_id=publish_id,
                raw={"publish_id": publish_id, "draft": is_draft},
            )
        except Exception as exc:  # noqa: BLE001
            return self._error_result(exc)
