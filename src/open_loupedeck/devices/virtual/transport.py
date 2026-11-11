"""WebSocket transport of the virtual device (``/ws/virtual``) and its HTTP state.

Server -> browser (JSON text frames, ``t`` = message type):

* ``snapshot``: ``model`` (``DeviceModel.to_dict()``), ``images`` (control id -> base64 PNG),
  ``leds`` (control id -> ``[r, g, b]``), ``brightness`` (0..100), ``models`` (selectable virtual
  models); sent on connect and whenever a client fell behind;
* ``image`` (``id``, ``png``), ``led`` (``id``, ``rgb``), ``brightness`` (``value``);
* ``bye`` (``reason``): this device is going away (model switch); the socket is then closed and
  the browser reconnects to the new device.

Browser -> server: ``{"t": "event", "id": "key_0_0", "type": "press|release|rotate|value|touch",
"value": ...}``; anything invalid is ignored (see ``VirtualBackend.parse_input``).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Callable
from typing import Any

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

from .backend import VirtualBackend

logger = logging.getLogger(__name__)

MAX_INCOMING_BYTES = 4096
QUEUE_SIZE = 512
CLOSE_NO_DEVICE = 1013
"""Try again later: no virtual device is open (yet)."""
CLOSE_RESTART = 1012


def virtual_backend_of(deck: Any) -> VirtualBackend | None:
    return deck if isinstance(deck, VirtualBackend) else None


async def handle_virtual_socket(ws: WebSocket, get_deck: Callable[[], Any]) -> None:
    """Serve one browser: snapshot, then a live stream of device output; relay its inputs."""

    await ws.accept()
    backend = virtual_backend_of(get_deck())
    if backend is None or backend.unplugged:
        await ws.close(code=CLOSE_NO_DEVICE)
        return

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=QUEUE_SIZE)
    state = {"resync": False}

    def _put(message: dict[str, Any]) -> None:
        try:
            queue.put_nowait(message)
        except asyncio.QueueFull:
            state["resync"] = True  # this client is too slow: it gets a fresh snapshot instead

    def listener(message: dict[str, Any]) -> None:
        # Called from any thread (skin draws run in worker threads).
        with contextlib.suppress(RuntimeError):  # loop closed during shutdown
            loop.call_soon_threadsafe(_put, message)

    unsubscribe = backend.subscribe(listener)
    pressed: set[str] = set()

    async def sender() -> None:
        await ws.send_json(backend.snapshot())
        while True:
            message = await queue.get()
            if state["resync"]:
                state["resync"] = False
                while not queue.empty():
                    queue.get_nowait()
                await ws.send_json(backend.snapshot())
                continue
            await ws.send_json(message)
            if message.get("t") == "bye":
                await ws.close(code=CLOSE_RESTART)
                return

    send_task = asyncio.create_task(sender())
    try:
        while True:
            receive = asyncio.ensure_future(ws.receive_text())
            done, _ = await asyncio.wait({receive, send_task}, return_when=asyncio.FIRST_COMPLETED)
            if send_task in done:
                receive.cancel()
                break
            text = receive.result()
            if len(text) > MAX_INCOMING_BYTES:
                continue
            try:
                msg = json.loads(text)
            except ValueError:
                continue
            if not isinstance(msg, dict) or msg.get("t") != "event":
                continue
            ev = backend.inject(msg)
            if ev is not None:
                if ev.type == "press":
                    pressed.add(ev.control_id)
                elif ev.type == "release":
                    pressed.discard(ev.control_id)
    except (WebSocketDisconnect, RuntimeError):
        pass
    except Exception:
        logger.debug("virtual WebSocket ended", exc_info=True)
    finally:
        unsubscribe()
        send_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await send_task
        if pressed:
            backend.release_controls(pressed)
