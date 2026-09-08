"""Fan-out WebSocket messages to OBS overlay browser sources."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

logger = logging.getLogger(__name__)


class OverlayHub:
    """Keeps active ``/ws/overlay`` connections; ``broadcast`` sends JSON to all clients."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._sockets: list[WebSocket] = []

    async def handle_connection(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._sockets.append(websocket)
        logger.debug("OBS overlay WebSocket connected (%s client(s))", len(self._sockets))
        try:
            while True:
                await websocket.receive_text()
        except asyncio.CancelledError:
            raise
        except WebSocketDisconnect:
            pass
        except Exception:
            logger.debug("overlay WebSocket receive ended", exc_info=True)
        finally:
            async with self._lock:
                if websocket in self._sockets:
                    self._sockets.remove(websocket)
            logger.debug("OBS overlay WebSocket disconnected (%s left)", len(self._sockets))

    async def broadcast(self, message: dict[str, Any]) -> None:
        async with self._lock:
            targets = list(self._sockets)
        if not targets:
            logger.debug(
                "OBS overlay: no browser connected — open GET /overlay (WebSocket /ws/overlay). Dropped cmd=%s",
                message.get("cmd"),
            )
            return
        dead: list[WebSocket] = []
        for ws in targets:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        if dead:
            async with self._lock:
                self._sockets = [w for w in self._sockets if w not in dead]
