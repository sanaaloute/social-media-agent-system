"""Realtime status channel (§9.3).

State transitions in the services layer call ``broadcast_status`` so the
review panel can refresh live. Broadcasting is strictly best-effort: with
no running event loop (e.g. sync worker threads) it is a no-op.
"""
import asyncio
import logging
from typing import List

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Tracks the open websocket connections of the review panel."""

    def __init__(self) -> None:
        self.connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.connections:
            self.connections.remove(websocket)

    async def broadcast_json(self, event: dict) -> None:
        """Send an event to every connection; drop the broken ones."""
        for connection in list(self.connections):
            try:
                await connection.send_json(event)
            except Exception:
                logger.debug("Dropping broken websocket connection")
                self.disconnect(connection)


manager = ConnectionManager()

_loop: asyncio.AbstractEventLoop | None = None


def set_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Capture the app's event loop (called from the FastAPI lifespan).

    Services run in sync contexts (route threadpool, Celery workers) where
    there is no running loop; broadcasting must therefore hop onto the app
    loop via run_coroutine_threadsafe.
    """
    global _loop
    _loop = loop


def broadcast_status(event: dict) -> None:
    """Sync-safe broadcast: hand the event to the app loop, else no-op."""
    try:
        if _loop is not None and _loop.is_running():
            asyncio.run_coroutine_threadsafe(manager.broadcast_json(event), _loop)
            return
        loop = asyncio.get_running_loop()
        loop.create_task(manager.broadcast_json(event))
    except RuntimeError:
        return  # no loop here (separate worker process) — skip silently
    except Exception:
        logger.debug("Failed to schedule status broadcast", exc_info=True)


async def status_ws(websocket: WebSocket) -> None:
    """Websocket endpoint: keep the connection open until the client leaves."""
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        logger.debug("Websocket closed abnormally", exc_info=True)
        manager.disconnect(websocket)
