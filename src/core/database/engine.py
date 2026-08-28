"""SQLModel engine / session management. SQLite for local dev, Postgres in compose."""
from typing import Generator

from sqlmodel import SQLModel, Session, create_engine

from src.core.config import apply_proxy_settings, get_settings

_settings = get_settings()
apply_proxy_settings(_settings)

_connect_args = (
    {"check_same_thread": False}
    if _settings.database_url.startswith("sqlite")
    else {}
)

engine = create_engine(_settings.database_url, echo=False, connect_args=_connect_args)


def init_db() -> None:
    """Create tables (dev convenience; use Alembic for real migrations)."""
    import src.core.models  # noqa: F401 — registers table metadata

    SQLModel.metadata.create_all(engine)


def get_session() -> Generator[Session, None, None]:
    """FastAPI dependency."""
    with Session(engine) as session:
        yield session
