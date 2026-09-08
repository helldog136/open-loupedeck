"""
Upstream python-loupedeck-live sets self.connection only after serial.Serial() succeeds.
If open fails (e.g. permission denied), __del__ still runs and raises AttributeError.

We wrap Loupedeck.__init__ to always define connection before opening the port.

``LoupedeckLive._read_serial`` catches *all* exceptions and resumes immediately; when the USB
device is unplugged, pyserial raises ``SerialException`` every iteration and spams the log.
We replace the reader loop to stop cleanly on disconnect and back off on other errors.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

_log = logging.getLogger("LoupedeckLive")

_serial_fatal_callback: Callable[[], None] | None = None


def set_serial_fatal_callback(fn: Callable[[], None] | None) -> None:
    """Called from the serial reader thread when the device is gone (unplug, I/O error)."""

    global _serial_fatal_callback
    _serial_fatal_callback = fn


def _notify_serial_fatal() -> None:
    cb = _serial_fatal_callback
    if cb is None:
        return
    try:
        cb()
    except Exception:
        _log.debug("serial fatal callback failed", exc_info=True)


def apply_loupedeck_init_patch() -> None:
    from Loupedeck.Devices.Loupedeck import Loupedeck

    if getattr(Loupedeck, "_open_loupedeck_init_patch", False):
        return

    _orig = Loupedeck.__init__

    def __init__(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        self.connection = None
        try:
            _orig(self, *args, **kwargs)
        except Exception:
            self.connection = None
            raise

    Loupedeck.__init__ = __init__  # type: ignore[method-assign]
    Loupedeck._open_loupedeck_init_patch = True  # type: ignore[attr-defined]


def _loupedeck_read_serial_patched(self: Any) -> None:
    """Same framing logic as upstream ``LoupedeckLive._read_serial``, but exit on unplug."""

    from serial.serialutil import SerialException

    def magic_byte_length_parser(chunk: bytes, magicByte: int = 0x82) -> None:
        trace = False
        self._buffer = self._buffer + chunk
        position = self._buffer.find(magicByte)
        while position != -1:
            if trace:
                _log.debug("magic: found %x at %s", magicByte, position)
            if len(self._buffer) < position + 2:
                if trace:
                    _log.debug(
                        "magic: not enough bytes (%s), waiting for more",
                        len(self._buffer),
                    )
                break
            next_length = self._buffer[position + 1]
            expected_end = position + next_length + 2
            if len(self._buffer) < expected_end:
                if trace:
                    _log.debug(
                        "magic: not enough bytes for message (%s, exp=%s), waiting for more",
                        len(self._buffer),
                        expected_end,
                    )
                break
            if trace:
                _log.debug(
                    "magic: message from %s to %s (len=%s), enqueueing (%s)",
                    position + 2,
                    expected_end,
                    next_length,
                    self._messages.qsize(),
                )
            self._messages.put(self._buffer[position + 2 : expected_end])
            self._buffer = self._buffer[expected_end:]
            position = self._buffer.find(magicByte)

    _log.debug("_read_serial: starting")

    while self.reading_running:
        try:
            if self.connection is None:
                _log.warning("Loupedeck serial reader: connection is None; stopping")
                self.reading_running = False
                self.process_running = False
                _notify_serial_fatal()
                break
            raw_byte = self.connection.read()
            if raw_byte != b"":
                magic_byte_length_parser(raw_byte)
        except SerialException as e:
            _log.warning(
                "Loupedeck serial device disconnected or read failed (%s); stopping reader",
                e,
            )
            self.reading_running = False
            self.process_running = False
            _notify_serial_fatal()
            break
        except OSError as e:
            _log.warning(
                "Loupedeck serial OS error (%s); stopping reader",
                e,
            )
            self.reading_running = False
            self.process_running = False
            _notify_serial_fatal()
            break
        except Exception:
            _log.exception("_read_serial: unexpected exception; backing off")
            time.sleep(0.25)

    self.reading_running = False
    try:
        conn = getattr(self, "connection", None)
        if conn is not None and hasattr(conn, "close"):
            conn.close()
    except Exception:
        _log.debug("Loupedeck: could not close serial after read thread exit", exc_info=True)

    _log.debug("_read_serial: terminated")


def apply_loupedeck_serial_reader_patch() -> None:
    from Loupedeck.Devices.LoupedeckLive import LoupedeckLive

    if getattr(LoupedeckLive, "_open_loupedeck_serial_reader_patch", False):
        return

    LoupedeckLive._read_serial = _loupedeck_read_serial_patched  # type: ignore[method-assign]
    LoupedeckLive._open_loupedeck_serial_reader_patch = True  # type: ignore[attr-defined]
