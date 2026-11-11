"""Virtual device backend: implements :class:`~..base.DeviceBackend` with no hardware.

Output (images, LEDs, brightness) is kept in memory and mirrored to subscribers (the web
transport, :mod:`.transport`); input comes from :meth:`VirtualBackend.inject` (the browser) and is
delivered to the event callback exactly as a hardware backend would. It always opens.
"""

from __future__ import annotations

import base64
import io
import logging
import threading
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from ...events import ControlEvent
from ..base import DiscoveredDevice, EventCallback, UnpluggedCallback
from ..model import DeviceModel
from .models import DEFAULT_VIRTUAL_MODEL, FAMILY, VIRTUAL_MODELS

if TYPE_CHECKING:
    from PIL import Image

    from ...config import Settings

logger = logging.getLogger(__name__)

MAX_IMAGE_BYTES = 512 * 1024
"""Upper bound of one stored PNG (a control keeps exactly one image, so memory is bounded)."""
MAX_ROTATE_STEPS = 16
"""A single rotate event is clamped to this many steps either way."""

Listener = Callable[[dict[str, Any]], None]


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def _number(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    return f if f == f and f not in (float("inf"), float("-inf")) else None


class VirtualBackend:
    """One virtual device (implements the :class:`DeviceBackend` protocol)."""

    family = FAMILY

    def __init__(self, model: DeviceModel | None = None) -> None:
        self.model: DeviceModel = model or DEFAULT_VIRTUAL_MODEL
        self.path: str | None = f"virtual:{self.model.config_name}"
        self.brightness = 100
        self._images: dict[str, bytes] = {}
        self._leds: dict[str, tuple[int, int, int]] = {}
        self._pressed: set[str] = set()
        self._event_cb: EventCallback | None = None
        self._unplugged_cb: UnpluggedCallback | None = None
        self._listeners: list[Listener] = []
        self._state_lock = threading.RLock()
        self._update_lock = threading.RLock()
        self._opened = False
        self._closed = False
        self._unplugged = False

    def __repr__(self) -> str:
        return f"VirtualBackend({self.model.id})"

    # --- lifecycle ----------------------------------------------------------------------------

    @property
    def is_open(self) -> bool:
        return self._opened and not self._closed and not self._unplugged

    @property
    def unplugged(self) -> bool:
        return self._unplugged

    def open(self) -> None:
        self._opened = True
        self._closed = False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._notify({"t": "bye", "reason": "closed"})

    def __enter__(self) -> VirtualBackend:
        self._update_lock.acquire()
        return self

    def __exit__(self, *exc: Any) -> None:
        self._update_lock.release()

    def request_unplug(self) -> None:
        """Behave as if the device was unplugged: the agent's reconnect loop opens a fresh backend
        (used by the browser's model selector)."""

        if self._unplugged:
            return
        self._unplugged = True
        self._notify({"t": "bye", "reason": "restart"})
        cb = self._unplugged_cb
        if cb is not None:
            cb()

    # --- output -------------------------------------------------------------------------------

    def set_image(self, control_id: str, image: Image.Image) -> None:
        ctl = self.model.control(control_id)
        if ctl is None or ctl.image is None:
            logger.debug("%s: %s takes no image; skipped", self.model.name, control_id)
            return
        buf = io.BytesIO()
        image.convert("RGB").save(buf, format="PNG")
        png = buf.getvalue()
        if len(png) > MAX_IMAGE_BYTES:
            logger.warning("Virtual image for %s too large (%d bytes); dropped", control_id, len(png))
            return
        with self._state_lock:
            if self._images.get(control_id) == png:
                return  # animation loops redraw unchanged keys: do not flood the browsers
            self._images[control_id] = png
        self._notify({"t": "image", "id": control_id, "png": base64.b64encode(png).decode("ascii")})

    def set_brightness(self, pct: int) -> None:
        value = int(_clamp(int(pct), 0, 100))
        with self._state_lock:
            if self.brightness == value:
                return
            self.brightness = value
        self._notify({"t": "brightness", "value": value})

    def set_led(self, control_id: str, rgb: tuple[int, int, int]) -> None:
        ctl = self.model.control(control_id)
        if ctl is None or ctl.led is None:
            logger.warning("set_led: %s has no LED on %s", control_id, self.model.name)
            return
        color = tuple(int(_clamp(int(c), 0, 255)) for c in rgb)[:3]
        if len(color) != 3:
            return
        with self._state_lock:
            if self._leds.get(control_id) == color:
                return
            self._leds[control_id] = color  # type: ignore[assignment]
        self._notify({"t": "led", "id": control_id, "rgb": list(color)})

    # --- state for the transport --------------------------------------------------------------

    def png_of(self, control_id: str) -> bytes | None:
        with self._state_lock:
            return self._images.get(control_id)

    def led_of(self, control_id: str) -> tuple[int, int, int] | None:
        with self._state_lock:
            return self._leds.get(control_id)

    def snapshot(self) -> dict[str, Any]:
        """Everything a freshly connected browser needs to draw the device."""

        with self._state_lock:
            images = {cid: base64.b64encode(png).decode("ascii") for cid, png in self._images.items()}
            leds = {cid: list(rgb) for cid, rgb in self._leds.items()}
            brightness = self.brightness
        return {
            "t": "snapshot",
            "model": self.model.to_dict(),
            "images": images,
            "leds": leds,
            "brightness": brightness,
            "models": [{"id": m.id, "name": m.name, "config_name": m.config_name} for m in VIRTUAL_MODELS],
        }

    def subscribe(self, listener: Listener) -> Callable[[], None]:
        """Register ``listener(message)`` (called from any thread); returns the unsubscribe function."""

        with self._state_lock:
            self._listeners.append(listener)

        def _unsubscribe() -> None:
            with self._state_lock:
                if listener in self._listeners:
                    self._listeners.remove(listener)

        return _unsubscribe

    def _notify(self, message: dict[str, Any]) -> None:
        with self._state_lock:
            listeners = list(self._listeners)
        for fn in listeners:
            try:
                fn(message)
            except Exception:
                logger.debug("Virtual listener failed", exc_info=True)

    # --- input --------------------------------------------------------------------------------

    def set_event_callback(self, callback: EventCallback | None) -> None:
        self._event_cb = callback

    def set_unplugged_callback(self, callback: UnpluggedCallback | None) -> None:
        self._unplugged_cb = callback
        if callback is not None and self._unplugged:
            callback()

    def parse_input(self, msg: Any) -> ControlEvent | None:
        """Validate a browser message ``{"id", "type", "value"}``; ``None`` = ignored.

        Unknown controls and input types the control does not have are ignored; ``rotate`` is
        rounded to whole steps and clamped, ``value`` is clamped to 0..1, ``touch`` to the
        control's pixels. A ``release`` without a prior ``press`` is ignored.
        """

        if not isinstance(msg, dict):
            return None
        cid, typ, val = msg.get("id"), msg.get("type"), msg.get("value")
        if not isinstance(cid, str) or not isinstance(typ, str):
            return None
        ctl = self.model.control(cid)
        if ctl is None:
            return None
        raw = {"virtual": True}
        if typ in ("press", "release"):
            if not ctl.has_input("press"):
                return None
            with self._state_lock:
                if typ == "press":
                    self._pressed.add(cid)
                elif cid in self._pressed:
                    self._pressed.discard(cid)
                else:
                    return None
            return ControlEvent(cid, typ, None, raw)  # type: ignore[arg-type]
        if typ == "rotate" and ctl.has_input("rotate"):
            n = _number(val)
            if n is None:
                return None
            steps = int(_clamp(round(n), -MAX_ROTATE_STEPS, MAX_ROTATE_STEPS))
            return ControlEvent(cid, "rotate", steps, raw) if steps else None
        if typ == "value" and ctl.has_input("value"):
            n = _number(val)
            return ControlEvent(cid, "value", _clamp(n, 0.0, 1.0), raw) if n is not None else None
        if typ == "touch" and ctl.has_input("touch"):
            w, h = ctl.image or (1, 1)
            xy = val if isinstance(val, (list, tuple)) and len(val) == 2 else None
            x, y = (_number(xy[0]), _number(xy[1])) if xy else (None, None)
            if x is None or y is None:
                return None
            return ControlEvent(cid, "touch", (int(_clamp(x, 0, w - 1)), int(_clamp(y, 0, h - 1))), raw)
        return None

    def inject(self, msg: Any) -> ControlEvent | None:
        """Deliver a browser input to the event callback as a hardware backend would."""

        ev = self.parse_input(msg)
        if ev is None:
            return None
        cb = self._event_cb
        if cb is not None and self.is_open:
            try:
                cb(ev)
            except Exception:
                logger.exception("Virtual event dispatch failed for %r", ev)
        return ev

    def release_controls(self, control_ids: set[str] | list[str]) -> None:
        """Release controls still pressed (a browser tab went away mid-press)."""

        for cid in list(control_ids):
            self.inject({"id": cid, "type": "release"})


class VirtualBackendFactory:
    """Registry entry of the virtual family. Never auto-detected: only selected by name."""

    family = FAMILY
    models = VIRTUAL_MODELS
    auto_detect = False

    def discover(self) -> list[DiscoveredDevice]:
        return []

    def open(self, settings: Settings) -> VirtualBackend:
        return self.open_model(self.model_named(settings.device.model))

    def open_model(self, model: DeviceModel) -> VirtualBackend:
        return VirtualBackend(model)

    @staticmethod
    def model_named(name: str | None) -> DeviceModel:
        for m in VIRTUAL_MODELS:
            if m.matches_name(name):
                return m
        return DEFAULT_VIRTUAL_MODEL

    def normalize_message(self, msg: dict[str, Any], model: DeviceModel | None = None) -> ControlEvent | None:
        return None
