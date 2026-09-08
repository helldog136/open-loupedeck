"""Lazy OBS WebSocket (v5) client using simpleobsws."""

from __future__ import annotations

import asyncio
import errno
import inspect
import logging
from typing import Any

import simpleobsws

logger = logging.getLogger(__name__)


def _friendly_connect_error(url: str, exc: BaseException) -> str:
    """Human-readable hint when the TCP/WebSocket handshake to OBS fails."""

    if isinstance(exc, ConnectionRefusedError) or (
        isinstance(exc, OSError) and getattr(exc, "errno", None) in (errno.ECONNREFUSED, errno.ECONNABORTED)
    ):
        return (
            f"OBS WebSocket connection refused at {url}. "
            "Start OBS Studio, then enable the server: Settings → Network → "
            "“Enable WebSocket server” (OBS 28+) or Tools → WebSocket Server Settings, "
            "typically port 4455. Match obs.host and obs.port in your open-loupedeck config."
        )
    if isinstance(exc, TimeoutError):
        return (
            f"OBS WebSocket timed out connecting to {url}. "
            "Check firewall rules and that OBS is running and the WebSocket server is enabled."
        )
    return f"OBS WebSocket could not connect to {url}: {exc}"


def _identification_parameters() -> Any | None:
    """Build IdentificationParameters compatible with simpleobsws 1.4.x API variants."""
    cls = getattr(simpleobsws, "IdentificationParameters", None)
    if cls is None:
        return None
    sig = inspect.signature(cls)
    params = sig.parameters
    if "ignoreNonFatalVersionCheck" in params:
        return cls(ignoreNonFatalVersionCheck=True)
    if "ignoreNonFatalRequestChecks" in params:
        return cls(ignoreNonFatalRequestChecks=True)
    return cls()


class ObsSession:
    def __init__(self, host: str, port: int, password: str) -> None:
        self._host = host
        self._port = port
        self._password = password
        self._ws: simpleobsws.WebSocketClient | None = None
        self._lock = asyncio.Lock()

    @property
    def url(self) -> str:
        return f"ws://{self._host}:{self._port}"

    async def _ensure(self, *, quiet: bool = False) -> simpleobsws.WebSocketClient:
        async with self._lock:
            if self._ws is not None:
                return self._ws
            kwargs: dict[str, Any] = {"url": self.url, "password": self._password}
            ident = _identification_parameters()
            if ident is not None:
                kwargs["identification_parameters"] = ident
            ws = simpleobsws.WebSocketClient(**kwargs)
            logger.debug("OBS WebSocket connecting to %s", self.url)
            try:
                await ws.connect()
                await ws.wait_until_identified()
            except Exception as exc:
                try:
                    await ws.disconnect()
                except Exception:
                    logger.debug("OBS disconnect after failed connect", exc_info=True)
                friendly = _friendly_connect_error(self.url, exc)
                if quiet:
                    logger.debug("%s", friendly)
                else:
                    logger.warning("%s", friendly)
                raise RuntimeError(friendly) from exc
            self._ws = ws
            logger.info("Connected to OBS WebSocket at %s", self.url)
            return self._ws

    def is_connected(self) -> bool:
        return self._ws is not None

    async def probe(self, timeout: float = 6.0) -> bool:
        """Try to connect if needed; return True when the WebSocket session is usable."""

        if self._ws is not None:
            return True
        try:
            await asyncio.wait_for(self._ensure(quiet=True), timeout=timeout)
            return self._ws is not None
        except Exception:
            return False

    async def call(self, request_type: str, request_data: dict[str, Any] | None = None) -> Any:
        ws = await self._ensure()
        payload = request_data or {}
        logger.debug("OBS request %s %s", request_type, payload)
        req = simpleobsws.Request(request_type, payload)
        ret = await ws.call(req)
        if not ret.ok():
            code = getattr(ret, "requestStatus", None)
            comment = getattr(ret, "comment", "")
            logger.error(
                "OBS request failed %s code=%s comment=%r data=%s",
                request_type,
                code,
                comment,
                payload,
            )
            raise RuntimeError(f"OBS request {request_type} failed: {code} {comment}")
        data = ret.responseData
        logger.debug(
            "OBS response %s ok data=%s",
            request_type,
            data if isinstance(data, dict) else type(data).__name__,
        )
        return data

    async def set_current_program_scene(self, scene_name: str) -> None:
        await self.call("SetCurrentProgramScene", {"sceneName": scene_name})

    async def get_current_program_scene(self) -> str:
        data = await self.call("GetCurrentProgramScene")
        if isinstance(data, dict):
            return str(data.get("currentProgramSceneName") or "")
        return ""

    async def toggle_input_mute(self, input_name: str) -> None:
        await self.call("ToggleInputMute", {"inputName": input_name})

    async def get_input_volume(self, input_name: str) -> dict[str, Any]:
        """Returns ``inputVolumeMul`` and ``inputVolumeDb`` (OBS WebSocket v5)."""

        data = await self.call("GetInputVolume", {"inputName": str(input_name)})
        return data if isinstance(data, dict) else {}

    async def set_input_volume_mul(self, input_name: str, volume_mul: float) -> None:
        """Set input volume by multiplier (0.0–1.0 typical UI range)."""

        await self.call(
            "SetInputVolume",
            {"inputName": str(input_name), "inputVolumeMul": float(volume_mul)},
        )

    async def close(self) -> None:
        async with self._lock:
            if self._ws is None:
                return
            try:
                await self._ws.disconnect()
            except Exception:
                logger.exception("Error while disconnecting OBS WebSocket")
            finally:
                self._ws = None
