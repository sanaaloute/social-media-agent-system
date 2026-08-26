"""FastAPI application factory (design doc §9).

Serves the REST API under ``/api``, the realtime status channel at
``/ws/status``, and the single-file review panel at ``/panel``.
"""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.api.routes import accounts, approvals, compose, contents, platforms, settings, tasks
from src.api.websocket import status as ws_status
from src.api.websocket.status import status_ws
from src.core.database.engine import init_db

_STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    ws_status.set_loop(asyncio.get_running_loop())
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Social Media Auto-Publishing", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(tasks.router, prefix="/api")
    app.include_router(contents.router, prefix="/api")
    app.include_router(approvals.router, prefix="/api")
    app.include_router(accounts.router, prefix="/api")
    app.include_router(compose.router, prefix="/api")
    app.include_router(platforms.router, prefix="/api")
    app.include_router(settings.router, prefix="/api")
    app.add_api_websocket_route("/ws/status", status_ws)
    app.mount(
        "/panel",
        StaticFiles(directory=_STATIC_DIR, html=True),
        name="panel",
    )
    return app


app = create_app()
