"""YouTube publishing via the Data API v3 resumable upload (design doc §4.1).

Flow:
  1. POST `upload/youtube/v3/videos?uploadType=resumable&part=snippet,status`
     with the video metadata — response header ``Location`` is the upload URL.
  2. PUT the raw file bytes to that URL.

Per the design-doc note on unverified OAuth apps, new uploads default to
``privacyStatus="private"``; override with ``metadata["privacy_status"]``.
Text and image posts are not supported on YouTube.
"""
import logging
import os

import httpx

from src.publishers.base import HTTP_TIMEOUT, PublishResult, PublisherAdapter

logger = logging.getLogger(__name__)

RESUMABLE_INIT_URL = (
    "https://www.googleapis.com/upload/youtube/v3/videos"
    "?uploadType=resumable&part=snippet,status"
)
CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels"


class YouTubeAdapter(PublisherAdapter):
    @property
    def platform_name(self) -> str:
        return "youtube"

    @property
    def _access_token(self) -> str:
        return self.tokens.get("access_token", "")

    async def authenticate(self) -> bool:
        if self.dry_run:
            return True
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                # Validates the token via a Bearer header so the secret
                # never appears in a URL (and thus never in error logs).
                resp = await client.get(
                    CHANNELS_URL,
                    params={"part": "id", "mine": "true"},
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
                "YouTube auth check failed: %s (status=%s)",
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
            error="YouTube does not support text-only posts.",
        )

    async def publish_image(
        self, image_path: str, caption: str, metadata: dict
    ) -> PublishResult:
        return PublishResult(
            success=False,
            platform=self.platform_name,
            error="YouTube does not support image posts.",
        )

    async def publish_video(
        self, video_path: str, title: str, description: str, metadata: dict
    ) -> PublishResult:
        if guard := self._guard_rate_limit():
            return guard
        if self.dry_run:
            return self._dry_result(f"video upload: {video_path}")
        try:
            # Unverified OAuth apps are restricted to private uploads (§4.1).
            privacy_status = metadata.get("privacy_status", "private")
            body = {
                "snippet": {
                    "title": title,
                    "description": description,
                    "tags": metadata.get("tags", []),
                    "categoryId": str(metadata.get("category_id", "22")),
                },
                "status": {
                    "privacyStatus": privacy_status,
                    "selfDeclaredMadeForKids": bool(
                        metadata.get("made_for_kids", False)
                    ),
                },
            }
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                # Step 1: open the resumable session.
                resp = await client.post(
                    RESUMABLE_INIT_URL,
                    json=body,
                    headers={
                        "Authorization": f"Bearer {self._access_token}",
                        "X-Upload-Content-Length": str(
                            os.path.getsize(video_path)
                        ),
                    },
                )
                resp.raise_for_status()
                upload_url = resp.headers["Location"]

                # Step 2: PUT the file bytes.
                with open(video_path, "rb") as fh:
                    resp = await client.put(upload_url, content=fh.read())
                    resp.raise_for_status()
                    data = resp.json()
            video_id = data.get("id")
            return PublishResult(
                success=True,
                platform=self.platform_name,
                remote_id=video_id,
                url=f"https://www.youtube.com/watch?v={video_id}"
                if video_id
                else None,
                raw=data,
            )
        except Exception as exc:  # noqa: BLE001
            return self._error_result(exc)
