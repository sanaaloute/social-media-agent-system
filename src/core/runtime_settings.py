"""Runtime-overridable settings, edited from the settings page (§9).

Resolution order: DB override (``app_setting`` row) > env / .env
(``pydantic Settings``) > field default. Only the whitelisted keys in
``_OVERRIDABLE`` can be changed at runtime; everything else stays env-only.
"""
import logging
from typing import Any, Callable, Optional

from sqlmodel import Session

from src.core.config import get_settings
from src.core.database.engine import engine

logger = logging.getLogger(__name__)


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "1", "yes", "on")


# key -> (coerce, validator, choices-for-UI)
_OVERRIDABLE: dict[str, tuple[Callable[[Any], Any], Callable[[Any], bool], Optional[list]]] = {
    "dry_run": (_to_bool, lambda v: isinstance(v, bool), None),
    "max_posts_per_account_per_day": (int, lambda v: 1 <= v <= 1000, None),
    "llm_provider": (str, lambda v: v in ("ollama", "openrouter", "claude", "openai"),
                     ["ollama", "openrouter", "claude", "openai"]),
    "image_provider": (str, lambda v: v in ("local", "kie", "dalle", "stable_diffusion"),
                       ["local", "kie", "dalle", "stable_diffusion"]),
    "video_provider": (str, lambda v: v in ("local", "kie", "falai", "kling"),
                       ["local", "kie", "falai", "kling"]),
    "autopilot_enabled": (_to_bool, lambda v: isinstance(v, bool), None),
}

OVERRIDABLE_KEYS = sorted(_OVERRIDABLE)


def _read_override(key: str) -> Optional[str]:
    """Raw override string from the DB, or None (missing/table not ready)."""
    from src.core.models.setting import AppSetting

    try:
        with Session(engine) as session:
            row = session.get(AppSetting, key)
            return row.value if row is not None else None
    except Exception:  # e.g. table not created yet — fall back to env
        logger.debug("settings override read failed for %s", key, exc_info=True)
        return None


def get_value(key: str) -> Any:
    """Effective value for a runtime setting (DB override > env > default)."""
    if key not in _OVERRIDABLE:
        raise KeyError(f"Setting {key!r} is not runtime-overridable")
    coerce, _, _ = _OVERRIDABLE[key]
    raw = _read_override(key)
    if raw is not None:
        return coerce(raw)
    return coerce(getattr(get_settings(), key))


def validate(key: str, raw: Any) -> Any:
    """Coerce and validate a value without persisting it."""
    if key not in _OVERRIDABLE:
        raise ValueError(
            f"Unknown setting {key!r}; overridable: {OVERRIDABLE_KEYS}"
        )
    coerce, valid, _ = _OVERRIDABLE[key]
    try:
        value = coerce(raw)
    except (TypeError, ValueError):
        raise ValueError(f"Setting {key!r}: cannot interpret {raw!r}") from None
    if not valid(value):
        raise ValueError(f"Setting {key!r}: invalid value {value!r}")
    return value


def set_value(key: str, raw: Any) -> Any:
    """Validate and persist an override; returns the coerced value."""
    from src.core.models.setting import AppSetting

    value = validate(key, raw)
    with Session(engine) as session:
        row = session.get(AppSetting, key)
        if row is None:
            row = AppSetting(key=key, value=str(value))
        else:
            row.value = str(value)
        session.add(row)
        session.commit()
    return value


def clear_value(key: str) -> None:
    """Remove an override so the env/default value applies again."""
    if key not in _OVERRIDABLE:
        raise ValueError(f"Unknown setting {key!r}")
    from src.core.models.setting import AppSetting

    with Session(engine) as session:
        row = session.get(AppSetting, key)
        if row is not None:
            session.delete(row)
            session.commit()


def list_effective() -> list[dict]:
    """Effective values with override flags — the settings-page payload."""
    result = []
    for key in OVERRIDABLE_KEYS:
        coerce, _, choices = _OVERRIDABLE[key]
        raw = _read_override(key)
        overridden = raw is not None
        value = coerce(raw) if overridden else coerce(getattr(get_settings(), key))
        result.append(
            {
                "key": key,
                "value": value,
                "overridden": overridden,
                "choices": choices,
            }
        )
    return result
