"""TikTok browser publisher: uploads via the web upload page (§4.2, §7.2).

Fallback for accounts flagged ``use_browser`` (e.g. unapproved Content
Posting API apps). All selectors are BEST-EFFORT — TikTok's creator upload
DOM changes frequently; verify before production use.
"""
import logging

from src.publishers.base import PublishResult
from src.publishers.browser_base import BrowserPublisherAdapter

logger = logging.getLogger(__name__)

# BEST-EFFORT selectors — verify against the live site before production use
UPLOAD_URL = "https://www.tiktok.com/tiktokstudio/upload"
LOGIN_INDICATOR = '[data-e2e="profile-icon"]'
VIDEO_FILE_INPUT = 'input[type="file"]'
CAPTION_EDITOR = 'div.public-DraftEditor-content'
POST_BUTTON = 'button[data-e2e="post_video_button"]'
CONFIRMATION_MODAL = 'div[data-e2e="upload-success"]'


class BrowserTikTokAdapter(BrowserPublisherAdapter):
    login_check_url = UPLOAD_URL
    login_indicator = LOGIN_INDICATOR

    @property
    def platform_name(self) -> str:
        return "tiktok"

    async def publish_text(self, content: str, metadata: dict) -> PublishResult:
        if guard := self._guard_rate_limit():
            return guard
        return PublishResult(
            success=False,
            platform=self.platform_name,
            error="TikTok does not support text-only posts.",
        )

    async def publish_image(
        self, image_path: str, caption: str, metadata: dict
    ) -> PublishResult:
        if guard := self._guard_rate_limit():
            return guard
        if dry := self._dry_or_none(f"photo post: {image_path}"):
            return dry
        try:
            return await self._upload(image_path, caption)
        except Exception as exc:  # noqa: BLE001
            return self._error_result(exc)

    async def publish_video(
        self, video_path: str, title: str, description: str, metadata: dict
    ) -> PublishResult:
        if guard := self._guard_rate_limit():
            return guard
        if dry := self._dry_or_none(f"video upload: {video_path}"):
            return dry
        try:
            caption = f"{title}\n\n{description}".strip() or title
            return await self._upload(video_path, caption)
        except Exception as exc:  # noqa: BLE001
            return self._error_result(exc)

    # ------------------------------------------------------------------

    async def _upload(self, media_path: str, caption: str) -> PublishResult:
        context = await self._get_browser_context()
        page = context.pages[0] if context.pages else await context.new_page()

        await page.goto(UPLOAD_URL, wait_until="domcontentloaded")
        await self._human_like_delay(2.0, 4.0)

        # The file input is hidden — set files on it directly.
        file_input = await page.wait_for_selector(
            VIDEO_FILE_INPUT, timeout=15000
        )
        await file_input.set_input_files(media_path)
        # Upload + processing takes a while for larger videos.
        await self._human_like_delay(6.0, 10.0)

        editor = await page.wait_for_selector(CAPTION_EDITOR, timeout=30000)
        await editor.click()
        await self._human_like_delay(0.3, 0.8)
        await self._type_human_like(editor, caption)
        await self._human_like_delay()

        post_button = await page.wait_for_selector(POST_BUTTON, timeout=10000)
        await post_button.click()
        await self._human_like_delay(3.0, 5.0)

        confirmation = await page.query_selector(CONFIRMATION_MODAL)
        logger.info(
            "Browser TikTok post submitted for account %s (confirmation=%s)",
            self.account_id,
            bool(confirmation),
        )
        return PublishResult(
            success=True,
            platform=self.platform_name,
            raw={"via": "browser", "confirmation": bool(confirmation)},
        )
