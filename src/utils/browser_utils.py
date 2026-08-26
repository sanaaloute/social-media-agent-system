"""Browser automation utilities: UA rotation and profile paths (§4.2)."""
import random
from pathlib import Path

from src.core.config import get_settings

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
]


def random_user_agent() -> str:
    return random.choice(USER_AGENTS)


def browser_profile_path(platform: str, account_id: str) -> str:
    """Per-platform, per-account persistent profile dir — stored locally only."""
    path = (
        Path(get_settings().browser_profiles_dir) / platform / account_id
    )
    path.mkdir(parents=True, exist_ok=True)
    return str(path)
