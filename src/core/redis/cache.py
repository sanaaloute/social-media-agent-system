"""Token cache — short-lived storage for decrypted platform access tokens."""
from typing import Optional

from src.core.redis.client import get_cache_client

_PREFIX = "token:"


def cache_token(account_id: str, token: str, ttl_seconds: int = 3600) -> None:
    get_cache_client().set(_PREFIX + account_id, token, ex=ttl_seconds)


def get_cached_token(account_id: str) -> Optional[str]:
    return get_cache_client().get(_PREFIX + account_id)


def invalidate_token(account_id: str) -> None:
    get_cache_client().delete(_PREFIX + account_id)
