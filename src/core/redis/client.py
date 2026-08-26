"""Cache client: real Redis when REDIS_URL is set, in-memory fallback otherwise.

Exposes the small surface the app needs: get/set/delete/incr/expire.
"""
import threading
import time
from typing import Optional

from src.core.config import get_settings


class MemoryClient:
    """Minimal Redis-compatible in-memory store for local dev and tests."""

    def __init__(self) -> None:
        self._data: dict[str, str] = {}
        self._expires: dict[str, float] = {}
        self._lock = threading.Lock()

    def _purge(self, key: str) -> None:
        exp = self._expires.get(key)
        if exp is not None and exp < time.time():
            self._data.pop(key, None)
            self._expires.pop(key, None)

    def get(self, key: str) -> Optional[str]:
        with self._lock:
            self._purge(key)
            return self._data.get(key)

    def set(self, key: str, value: str, ex: Optional[int] = None) -> bool:
        with self._lock:
            self._data[key] = str(value)
            if ex is not None:
                self._expires[key] = time.time() + ex
            return True

    def delete(self, key: str) -> int:
        with self._lock:
            self._expires.pop(key, None)
            return 1 if self._data.pop(key, None) is not None else 0

    def incr(self, key: str) -> int:
        with self._lock:
            self._purge(key)
            value = int(self._data.get(key, "0")) + 1
            self._data[key] = str(value)
            return value

    def decr(self, key: str) -> int:
        with self._lock:
            self._purge(key)
            value = max(0, int(self._data.get(key, "0")) - 1)
            self._data[key] = str(value)
            return value

    def expire(self, key: str, seconds: int) -> bool:
        with self._lock:
            if key not in self._data:
                return False
            self._expires[key] = time.time() + seconds
            return True


_client = None


def get_cache_client():
    """Return a shared redis.Redis or MemoryClient instance."""
    global _client
    if _client is None:
        url = get_settings().redis_url
        if url:
            import redis

            _client = redis.Redis.from_url(url, decode_responses=True)
        else:
            _client = MemoryClient()
    return _client
