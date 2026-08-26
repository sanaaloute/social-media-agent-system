"""Platform routes — the canonical list of supported platforms (§4).

The panel's platform picker is built from this endpoint: every supported
platform is listed, flagged with whether an active account is registered.
"""
from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from src.core.database.engine import get_session
from src.core.models import PlatformAccount
from src.publishers import SUPPORTED_PLATFORMS

router = APIRouter(prefix="/platforms", tags=["platforms"])


@router.get("")
def list_platforms(session: Session = Depends(get_session)):
    """All supported platforms with account-registration status."""
    active = {
        account.platform
        for account in session.exec(
            select(PlatformAccount).where(PlatformAccount.is_active.is_(True))
        )
    }
    return [
        {
            "name": name,
            "via": meta["via"],
            "media": meta["media"],
            "has_account": name in active,
        }
        for name, meta in SUPPORTED_PLATFORMS.items()
    ]
