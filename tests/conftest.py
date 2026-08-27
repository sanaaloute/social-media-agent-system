"""Shared fixtures: isolated SQLite DB, eager queue, stub providers, dry-run.

Environment must be set BEFORE any src.* import, because
`src.core.database.engine` builds the global engine at import time.

The product ships no mock providers — tests inject the lightweight stubs
from `tests/doubles.py` into the provider registries under the test-only
name "mock", so the suite runs offline with no GPU or API keys.
"""
import os
import tempfile

_TMPDIR = tempfile.mkdtemp(prefix="smas-test-")

os.environ["DATABASE_URL"] = f"sqlite:///{_TMPDIR}/test.db"
os.environ["REDIS_URL"] = ""
os.environ["QUEUE_MODE"] = "eager"
os.environ["DRY_RUN"] = "true"
os.environ["LLM_PROVIDER"] = "mock"  # test-only name, injected below
os.environ["IMAGE_PROVIDER"] = "mock"
os.environ["VIDEO_PROVIDER"] = "mock"
os.environ["MEDIA_CACHE_DIR"] = f"{_TMPDIR}/media"
os.environ["BROWSER_PROFILES_DIR"] = f"{_TMPDIR}/profiles"

import pytest  # noqa: E402
from sqlmodel import SQLModel, Session  # noqa: E402

from src.agents import providers as _providers  # noqa: E402
from src.core.database.engine import engine, init_db  # noqa: E402
from tests.doubles import StubImage, StubLLM, StubVideo  # noqa: E402

_providers._LLM_PROVIDERS.setdefault("mock", StubLLM)
_providers._IMAGE_PROVIDERS.setdefault("mock", StubImage)
_providers._VIDEO_PROVIDERS.setdefault("mock", StubVideo)


@pytest.fixture(autouse=True)
def _db():
    """Fresh schema around every test."""
    init_db()
    yield
    SQLModel.metadata.drop_all(engine)


@pytest.fixture
def session():
    with Session(engine) as s:
        yield s


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from src.api.main import app

    with TestClient(app) as c:
        yield c
