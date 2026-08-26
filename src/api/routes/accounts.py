"""Account routes — register and manage platform accounts (§6.2, §9.1).

Credentials and tokens are encrypted at rest (§6.1) and never returned in
plaintext — list responses mask the encrypted blobs.
"""
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from src.core.database.engine import get_session
from src.core.models import AuditLog, PlatformAccount
from src.utils.crypto import get_cipher

router = APIRouter(prefix="/accounts", tags=["accounts"])


class AccountCreate(BaseModel):
    platform: str
    username: str
    credentials: Dict[str, Any] = Field(default_factory=dict)
    tokens: Dict[str, Any] = Field(default_factory=dict)
    use_browser: bool = False


def _masked(account: PlatformAccount) -> dict:
    """Public view of an account — encrypted blobs masked (§6.1)."""
    return {
        "id": account.id,
        "platform": account.platform,
        "username": account.username,
        "credentials_enc": "***",
        "tokens_enc": "***",
        "browser_profile_path": account.browser_profile_path,
        "use_browser": account.use_browser,
        "is_active": account.is_active,
    }


@router.post("", status_code=201, response_model=PlatformAccount)
def create_account(payload: AccountCreate, session: Session = Depends(get_session)):
    """Register an account, encrypting credentials and tokens (§6.1)."""
    cipher = get_cipher()
    account = PlatformAccount(
        platform=payload.platform.lower(),
        username=payload.username,
        credentials_enc=cipher.encrypt(payload.credentials),
        tokens_enc=cipher.encrypt(payload.tokens),
        use_browser=payload.use_browser,
    )
    session.add(account)
    session.add(
        AuditLog(
            actor="system",
            action="account_created",
            detail={"platform": account.platform, "username": account.username},
        )
    )
    session.commit()
    session.refresh(account)
    return account


@router.get("", response_model=List[dict])
def list_accounts(session: Session = Depends(get_session)):
    """All accounts with encrypted fields masked."""
    accounts = session.exec(select(PlatformAccount)).all()
    return [_masked(account) for account in accounts]


@router.delete("/{account_id}")
def delete_account(account_id: str, session: Session = Depends(get_session)):
    """Soft delete: the account is kept but deactivated."""
    account = session.get(PlatformAccount, account_id)
    if account is None:
        raise HTTPException(
            status_code=404, detail=f"Account {account_id!r} not found"
        )
    account.is_active = False
    session.add(account)
    session.commit()
    session.refresh(account)
    return _masked(account)
