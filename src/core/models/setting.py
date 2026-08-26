"""Runtime setting overrides edited from the settings page (§9).

Stored as key/value rows; resolution order is DB override > env > default
(see `src.core.runtime_settings`).
"""
from sqlmodel import Field, SQLModel


class AppSetting(SQLModel, table=True):
    __tablename__ = "app_setting"

    key: str = Field(primary_key=True)
    value: str
