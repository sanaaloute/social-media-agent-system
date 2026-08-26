"""Per-platform / per-account rate limiting with daily post caps (§6.2, §6.3).

Uses the shared cache client (Redis or in-memory). Counters key on the
UTC day and expire after 48h, so no cleanup is needed.
"""
from datetime import datetime, timezone

from src.core import runtime_settings
from src.core.redis.client import get_cache_client


class RateLimiter:
    """Sliding daily counter: `rl:{platform}:{account_id}:{yyyy-mm-dd}`."""

    def __init__(self, platform: str, account_id: str = "_", limit: int | None = None):
        self.platform = platform
        self.account_id = account_id
        self.limit = (
            limit
            if limit is not None
            else runtime_settings.get_value("max_posts_per_account_per_day")
        )

    def _key(self) -> str:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return f"rl:{self.platform}:{self.account_id}:{day}"

    def remaining(self) -> int:
        raw = get_cache_client().get(self._key())
        used = int(raw) if raw else 0
        return max(0, self.limit - used)

    def acquire(self) -> bool:
        """Consume one slot atomically. Returns False when the daily cap
        is reached (the over-shot increment is rolled back)."""
        client = get_cache_client()
        key = self._key()
        used = client.incr(key)
        client.expire(key, 48 * 3600)
        if used > self.limit:
            client.decr(key)
            return False
        return True

    def refund(self) -> None:
        """Give one slot back (e.g. the publish attempt failed)."""
        get_cache_client().decr(self._key())
