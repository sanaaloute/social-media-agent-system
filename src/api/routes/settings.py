"""Settings routes — view and edit runtime-overridable settings (§9).

Only whitelisted keys (see `src.core.runtime_settings`) can be changed;
changes take effect immediately and are audited (§5.3.5).
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from src.core import runtime_settings
from src.core.database.engine import get_session
from src.services import _audit

router = APIRouter(prefix="/settings", tags=["settings"])


class SettingsUpdate(BaseModel):
    """Bulk update; a value of None clears the override (env applies again)."""

    values: dict[str, object]


@router.get("")
def get_all_settings():
    """Effective values with override flags and UI metadata."""
    return runtime_settings.list_effective()


@router.put("")
def update_settings(payload: SettingsUpdate, session: Session = Depends(get_session)):
    """Apply a batch of setting changes (all validated before any write)."""
    coerced = {}
    for key, raw in payload.values.items():
        if raw is None:
            if key not in runtime_settings.OVERRIDABLE_KEYS:
                raise HTTPException(400, f"Unknown setting {key!r}")
            continue
        try:
            coerced[key] = runtime_settings.validate(key, raw)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    for key, raw in payload.values.items():
        if raw is None:
            runtime_settings.clear_value(key)
        else:
            runtime_settings.set_value(key, raw)

    _audit(
        session,
        actor="operator",
        action="settings_updated",
        detail={
            "changed": {k: str(v) for k, v in coerced.items()},
            "cleared": [k for k, v in payload.values.items() if v is None],
        },
    )
    session.commit()
    return runtime_settings.list_effective()
