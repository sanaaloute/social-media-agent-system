"""Platform account. Credentials and tokens are stored AES-256 encrypted."""
import uuid
from typing import Optional

from sqlmodel import Field, SQLModel


class PlatformAccount(SQLModel, table=True):
    __tablename__ = "platform_account"

    id: str = Field(default_factory=lambda: uuid.uuid4().hex, primary_key=True)
    platform: str = Field(index=True)
    username: str
    credentials_enc: str = ""  # encrypted JSON blob (login, app secrets, ...)
    tokens_enc: str = ""  # encrypted JSON blob (access/refresh tokens, expiry)
    browser_profile_path: Optional[str] = None
    use_browser: bool = False  # True -> browser adapter, False -> official API
    is_active: bool = True
