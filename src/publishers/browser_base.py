"""Browser-automation publisher base (design doc §4.2, §7.2).

Used for platforms without an official publishing API (or when the account
is flagged ``use_browser``). Playwright is imported lazily INSIDE methods so
`import src.publishers` works on machines without browsers installed.

Each account gets a persistent per-platform profile directory holding the
logged-in session (cookies/storage). In dry-run mode every publish_* method
returns a simulated result WITHOUT launching a browser.
"""
import asyncio
import logging
import random
from typing import Any, Optional

from src.core import runtime_settings
from src.core.models import PlatformAccount
from src.publishers.base import PublishResult, PublisherAdapter
from src.utils.browser_utils import browser_profile_path, random_user_agent

logger = logging.getLogger(__name__)


class BrowserPublisherAdapter(PublisherAdapter):
    """Base for Playwright-driven publishers (§7.2)."""

    #: URL loaded to check whether the stored session is still logged in.
    login_check_url: str = ""
    #: CSS selector that only exists when logged in.
    login_indicator: str = ""

    def __init__(self, account: PlatformAccount):
        super().__init__(account)
        # Browser accounts hold no API tokens — the base class would force
        # them into dry-run forever. The live login session is validated by
        # authenticate() instead, so only the global flag applies here.
        self.dry_run = runtime_settings.get_value("dry_run")
        self._playwright = None
        self._context = None

    # ------------------------------------------------------------------
    # Browser lifecycle
    # ------------------------------------------------------------------

    async def _get_browser_context(self):
        """Launch (or reuse) a persistent Chromium context for this account."""
        if self._context is not None:
            return self._context
        from playwright.async_api import async_playwright  # lazy: §7.2

        user_data_dir = self.account.browser_profile_path or browser_profile_path(
            self.platform_name, self.account_id
        )
        self._playwright = await async_playwright().start()
        self._context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=False,  # headed sessions survive bot checks better (§4.2)
            viewport={"width": 1920, "height": 1080},
            user_agent=random_user_agent(),
            locale="en-US",
        )
        return self._context

    async def close(self) -> None:
        """Tear down the browser context and Playwright driver."""
        if self._context is not None:
            await self._context.close()
            self._context = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None

    async def authenticate(self) -> bool:
        """Check the stored session by loading `login_check_url` and looking
        for the subclass-defined `login_indicator` selector."""
        if self.dry_run:
            return True
        try:
            context = await self._get_browser_context()
            page = context.pages[0] if context.pages else await context.new_page()
            await page.goto(self.login_check_url, wait_until="domcontentloaded")
            await self._human_like_delay(2.0, 4.0)
            indicator = await page.query_selector(self.login_indicator)
            return indicator is not None
        except Exception as exc:  # noqa: BLE001 — adapter boundary
            logger.error(
                "%s browser auth check failed: %s", self.platform_name, exc
            )
            return False

    # ------------------------------------------------------------------
    # Human-mimicry helpers (§4.2)
    # ------------------------------------------------------------------

    async def _human_like_delay(self, min_sec: float = 1.0, max_sec: float = 3.0) -> None:
        """Sleep a random interval to avoid robotic timing patterns."""
        await asyncio.sleep(random.uniform(min_sec, max_sec))

    async def _type_human_like(self, element: Any, text: str) -> None:
        """Type text character by character with 50-150 ms delays."""
        for char in text:
            await element.type(char)
            await asyncio.sleep(random.uniform(0.05, 0.15))

    # ------------------------------------------------------------------
    # Dry-run guard for subclass publish_* methods
    # ------------------------------------------------------------------

    def _dry_or_none(self, content_desc: str) -> Optional[PublishResult]:
        """Return the dry result in dry-run mode (no browser launched), else
        None so the caller proceeds with the real flow."""
        if self.dry_run:
            return self._dry_result(content_desc)
        return None
