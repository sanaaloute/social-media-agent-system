"""X (Twitter) browser publisher: composes tweets on x.com (§4.2, §7.2).

Fallback for accounts flagged ``use_browser``. All selectors are
BEST-EFFORT — X changes its DOM frequently; verify before production use.
"""
import logging

from src.publishers.base import PublishResult
from src.publishers.browser_base import BrowserPublisherAdapter

logger = logging.getLogger(__name__)

# BEST-EFFORT selectors — verify against the live site before production use
HOME_URL = "https://x.com/home"
COMPOSE_URL = "https://x.com/compose/tweet"
LOGIN_INDICATOR = '[data-testid="SideNav_NewTweet_Button"]'
TWEET_TEXTBOX = '[data-testid="tweetTextarea_0"]'
MEDIA_FILE_INPUT = '[data-testid="fileInput"]'
TWEET_SUBMIT_BUTTON = '[data-testid="tweetButtonInline"]'
CONFIRMATION_TOAST = '[data-testid="toast"]'


class BrowserTwitterAdapter(BrowserPublisherAdapter):
    login_check_url = HOME_URL
    login_indicator = LOGIN_INDICATOR

    @property
    def platform_name(self) -> str:
        return "twitter"

    async def publish_text(self, content: str, metadata: dict) -> PublishResult:
        if guard := self._guard_rate_limit():
            return guard
        if dry := self._dry_or_none(f"tweet: {content[:80]}"):
            return dry
        try:
            return await self._compose_tweet(content, media_path=None)
        except Exception as exc:  # noqa: BLE001
            return self._error_result(exc)

    async def publish_image(
        self, image_path: str, caption: str, metadata: dict
    ) -> PublishResult:
        if guard := self._guard_rate_limit():
            return guard
        if dry := self._dry_or_none(f"tweet with image: {image_path}"):
            return dry
        try:
            return await self._compose_tweet(caption, media_path=image_path)
        except Exception as exc:  # noqa: BLE001
            return self._error_result(exc)

    async def publish_video(
        self, video_path: str, title: str, description: str, metadata: dict
    ) -> PublishResult:
        if guard := self._guard_rate_limit():
            return guard
        if dry := self._dry_or_none(f"tweet with video: {video_path}"):
            return dry
        try:
            text = f"{title}\n\n{description}".strip() or title
            return await self._compose_tweet(text, media_path=video_path)
        except Exception as exc:  # noqa: BLE001
            return self._error_result(exc)

    # ------------------------------------------------------------------

    async def _compose_tweet(
        self, text: str, media_path: str | None
    ) -> PublishResult:
        context = await self._get_browser_context()
        page = context.pages[0] if context.pages else await context.new_page()

        await page.goto(COMPOSE_URL, wait_until="domcontentloaded")
        await self._human_like_delay()

        textbox = await page.wait_for_selector(TWEET_TEXTBOX, timeout=15000)
        await textbox.click()
        await self._human_like_delay(0.3, 0.8)
        await self._type_human_like(textbox, text)
        await self._human_like_delay()

        if media_path:
            file_input = await page.wait_for_selector(
                MEDIA_FILE_INPUT, timeout=10000
            )
            await file_input.set_input_files(media_path)
            # Wait for the media upload to finish before submitting.
            await self._human_like_delay(4.0, 7.0)

        submit = await page.wait_for_selector(TWEET_SUBMIT_BUTTON, timeout=10000)
        await submit.click()
        await self._human_like_delay(2.0, 4.0)

        toast = await page.query_selector(CONFIRMATION_TOAST)
        logger.info(
            "Browser tweet submitted for account %s (toast=%s)",
            self.account_id,
            bool(toast),
        )
        return PublishResult(
            success=True,
            platform=self.platform_name,
            raw={"via": "browser", "confirmation": bool(toast)},
        )
