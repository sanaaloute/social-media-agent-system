"""Token management: decrypt stored tokens, cache them, refresh when needed.

Refresh flow shapes follow the official docs but are only exercised with
real credentials; in dry-run mode the stored tokens are returned as-is.
"""
import logging
from typing import Any, Dict

import httpx

from src.core.models import PlatformAccount
from src.core.redis.cache import cache_token, get_cached_token
from src.utils.crypto import get_cipher

logger = logging.getLogger(__name__)


def store_tokens(account: PlatformAccount, tokens: Dict[str, Any]) -> None:
    """Encrypt and persist a token dict onto the account row."""
    account.tokens_enc = get_cipher().encrypt(tokens)


def load_tokens(account: PlatformAccount) -> Dict[str, Any]:
    if not account.tokens_enc:
        return {}
    return get_cipher().decrypt(account.tokens_enc)


def get_access_token(account: PlatformAccount) -> str | None:
    """Return a usable access token, using the short-lived cache first."""
    cached = get_cached_token(account.id)
    if cached:
        return cached
    tokens = load_tokens(account)
    token = tokens.get("access_token")
    if token:
        cache_token(account.id, token, ttl_seconds=3600)
    return token


async def refresh_tokens(account: PlatformAccount) -> Dict[str, Any]:
    """Refresh the account's tokens when the platform supports it.

    Currently implements the TikTok refresh shape (24h access / 365d refresh,
    §4.1). Other platforms either use long-lived tokens (Meta Page tokens)
    or re-auth flows; extend here as needed.
    """
    tokens = load_tokens(account)
    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        return tokens

    if account.platform == "tiktok":
        from src.core.config import get_settings

        settings = get_settings()
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://open.tiktokapis.com/v2/oauth/token/",
                data={
                    "client_key": settings.tiktok_client_key,
                    "client_secret": settings.tiktok_client_secret,
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            resp.raise_for_status()
            tokens.update(resp.json())
            store_tokens(account, tokens)
            logger.info("Refreshed TikTok tokens for account %s", account.id)
    return tokens
