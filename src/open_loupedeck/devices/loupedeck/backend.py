"""Loupedeck backend: wraps the python-loupedeck-live driver behind :class:`DeviceBackend`.

Everything driver-specific lives here: choosing the Live vs Live S driver class and baud rate,
the handshake (``is_loupedeck``), mapping control ids to the driver's key indices / strip calls
(RGB565 framebuffer pushes happen inside the driver), the button LED protocol names, the serial
reader thread (patched in :mod:`.patches`) and the unplug signal.
"""

from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING, Any

from Loupedeck.DeviceManager import DeviceManager
from Loupedeck.Devices.constants import BAUD_RATE
from Loupedeck.Devices.LoupedeckLive import LoupedeckLive

from ...control_ids import driver_name_for_button
from ...devices.model import parse_key_id
from ...events import ControlEvent
from ..base import DiscoveredDevice, EventCallback, UnpluggedCallback
from ..model import DeviceModel
from .discovery import HardwareHint, list_loupedeck_usb_ports, usb_hint_for_port
from .events import normalize_loupedeck_message
from .live_s import LoupedeckLiveS
from .models import LOUPEDECK_LIVE, LOUPEDECK_LIVE_S, LOUPEDECK_MODELS

if TYPE_CHECKING:
    from PIL import Image

    from ...config import Settings

logger = logging.getLogger(__name__)

FAMILY = "loupedeck"

_HINT_MODELS: dict[str, DeviceModel] = {"live": LOUPEDECK_LIVE, "live_s": LOUPEDECK_LIVE_S}


def model_for_driver(driver: Any) -> DeviceModel:
    """Live S driver class -> Live S descriptor; anything else is a Loupedeck Live."""

    return LOUPEDECK_LIVE_S if isinstance(driver, LoupedeckLiveS) else LOUPEDECK_LIVE


def led_protocol_name(control_id: str) -> str | None:
    """Driver name for SET_COLOR of a round button.

    Upstream foxxyz/loupedeck maps the four Live S LEDs to button ids 0–3, i.e. BUTTONS keys
    0x07–0x0A (values 0, 1, 2, 3). python-loupedeck uses string names: 0x07 is "circle", then
    "1", "2", "3" for 0x08–0x0A. Do *not* use "1"–"4" (0x08–0x0B) for the Live S: that is the
    middle four of the eight Loupedeck Live side keys and shifts every Live S color to the wrong
    LED. ``button_0`` -> ``circle``, ``button_N`` -> ``N``.
    """

    return driver_name_for_button(control_id)


class LoupedeckBackend:
    """One opened Loupedeck Live / Live S (implements :class:`~..base.DeviceBackend`)."""

    family = FAMILY

    def __init__(self, driver: Any, model: DeviceModel | None = None, *, baudrate: int | None = None) -> None:
        self.driver = driver
        self.model: DeviceModel = model or model_for_driver(driver)
        self.path: str | None = getattr(driver, "path", None)
        self.baudrate = baudrate
        self._event_cb: EventCallback | None = None
        self._unplugged_cb: UnpluggedCallback | None = None
        self._unplugged = False
        # Read by the patched serial reader (see patches._notify_serial_fatal).
        driver._open_loupedeck_on_fatal = self._on_serial_fatal

    def __repr__(self) -> str:
        return f"LoupedeckBackend({self.model.id}, path={self.path!r})"

    # --- lifecycle ----------------------------------------------------------------------------

    @property
    def is_open(self) -> bool:
        conn = getattr(self.driver, "connection", None)
        return conn is not None and bool(getattr(conn, "is_open", False))

    @property
    def unplugged(self) -> bool:
        return self._unplugged

    def open(self) -> None:
        self.driver.start()

    def close(self) -> None:
        self.driver.stop()

    def __enter__(self) -> LoupedeckBackend:
        self.driver.__enter__()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.driver.__exit__(*exc)

    # --- output -------------------------------------------------------------------------------

    def set_image(self, control_id: str, image: Image.Image) -> None:
        d = self.driver
        model = self.model
        ctl = model.control(control_id)
        if ctl is None or ctl.image is None:
            logger.debug("%s: %s takes no image; skipped", model.name, control_id)
            return
        if ctl.kind == "key":
            cols, _rows = model.grid_of_keys()
            col, row = parse_key_id(control_id) or (0, 0)
            d.set_key_image(str(row * cols + col), image)
        elif control_id == "strip_0":
            d.set_left_image(image)
        elif control_id == "strip_1":
            d.set_right_image(image)
        else:
            logger.debug("No drawable target for %s", control_id)

    def set_brightness(self, pct: int) -> None:
        self.driver.set_brightness(pct)

    def set_led(self, control_id: str, rgb: tuple[int, int, int]) -> None:
        ctl = self.model.control(control_id)
        name = led_protocol_name(control_id)
        if ctl is None or ctl.led is None or name is None:
            logger.warning("set_led: %s has no LED on %s", control_id, self.model.name)
            return
        self.driver.set_button_color(name, rgb)

    # --- input --------------------------------------------------------------------------------

    def set_event_callback(self, callback: EventCallback | None) -> None:
        self._event_cb = callback
        self.driver.set_callback(self._on_driver_message if callback is not None else None)

    def set_unplugged_callback(self, callback: UnpluggedCallback | None) -> None:
        self._unplugged_cb = callback
        if callback is not None and self._unplugged:
            callback()  # went away before anyone listened

    def _on_driver_message(self, _driver: Any, msg: dict[str, Any]) -> None:
        cb = self._event_cb
        if cb is None:
            return
        try:
            ev = normalize_loupedeck_message(msg, self.model)
            if ev is not None:
                cb(ev)
        except Exception:
            logger.exception("Loupedeck event dispatch failed for %r", msg)

    def _on_serial_fatal(self) -> None:
        self._unplugged = True
        cb = self._unplugged_cb
        if cb is not None:
            cb()


# --- opening ------------------------------------------------------------------------------------


def _resolve_device_class(model: str, hint: HardwareHint | str) -> type[LoupedeckLive] | None:
    m = model.lower()
    if m == "live":
        return LoupedeckLive
    if m == "live_s":
        return LoupedeckLiveS
    if m == "auto":
        if hint == "live_s":
            return LoupedeckLiveS
        if hint == "live":
            return LoupedeckLive
    return None


def open_loupedeck(settings: Settings) -> LoupedeckBackend:
    """Open serial port with correct Live vs Live S driver; prefer USB VID/PID discovery."""

    bauds = [settings.device.baudrate] if settings.device.baudrate is not None else [BAUD_RATE, 256000, 115200]

    model = settings.device.model or "auto"
    candidates: list[tuple[str, type[LoupedeckLive]]] = []
    seen: set[tuple[str, str]] = set()

    def add(path: str, cls: type[LoupedeckLive]) -> None:
        key = (path, cls.__name__)
        if key in seen:
            return
        seen.add(key)
        candidates.append((path, cls))

    def add_for(path: str, hint: HardwareHint | str) -> None:
        rc = _resolve_device_class(model, hint)
        if rc is not None:
            add(path, rc)
        else:
            add(path, LoupedeckLiveS)
            add(path, LoupedeckLive)

    if settings.device.path:
        p = settings.device.path
        add_for(p, usb_hint_for_port(p))
    else:
        usb_list = list_loupedeck_usb_ports()
        if usb_list:
            for path, hint in usb_list:
                add_for(path, hint)
        else:
            logger.warning(
                "No USB serial port with Loupedeck vendor ID (0x2ec2) found. "
                "Plug in the device; on Linux use udev + dialout; on Windows install the USB serial driver "
                "if needed; set device.path manually (e.g. COM5, /dev/ttyACM0)."
            )
            for path in DeviceManager.list():
                add_for(path, usb_hint_for_port(path))

    if not candidates:
        hint = "Set device.path in config (e.g. COM5 on Windows, /dev/ttyACM0 on Linux)."
        if sys.platform != "win32":
            hint += " On Linux you can list ports: ls -l /dev/serial/by-id/"
        raise RuntimeError("No serial ports to try. " + hint)

    last_err: Exception | None = None
    for path, cls in candidates:
        for baud in bauds:
            try:
                deck = cls(path=path, baudrate=baud, timeout=1)
                if deck.is_loupedeck():
                    logger.info("Loupedeck open: %s as %s @ %s baud", path, cls.__name__, baud)
                    return LoupedeckBackend(deck, baudrate=baud)
            except Exception as e:
                last_err = e
                logger.debug("Try %s %s @ %s: %s", cls.__name__, path, baud, e)
                continue

    msg = open_failure_message(last_err)
    raise RuntimeError(msg) from last_err


def open_failure_message(last_err: Exception | None) -> str:
    base = (
        "No Loupedeck found. Check device.path, device.model, device.baudrate; "
        "stop the official Loupedeck app if it is running."
    )
    if last_err is None:
        return base
    err_s = str(last_err)
    if "Permission denied" in err_s or "Errno 13" in err_s:
        return (
            f"{base}\n\n"
            f"Permission denied on the serial port ({last_err}).\n"
            "- Add your user to group dialout: sudo usermod -aG dialout $USER\n"
            "- Log out and log back in (or reboot), then retry.\n"
            "- Install the udev rule from this repo: udev/99-loupedeck.rules → /etc/udev/rules.d/\n"
            "  then: sudo udevadm control --reload-rules && sudo udevadm trigger\n"
            "  and unplug/replug the Loupedeck.\n"
        )
    return f"{base}\n\nLast error: {last_err}"


# --- registry entry -----------------------------------------------------------------------------


class LoupedeckBackendFactory:
    """Registry entry for the Loupedeck family (see :mod:`..registry`)."""

    family = FAMILY
    models = LOUPEDECK_MODELS

    def discover(self) -> list[DiscoveredDevice]:
        return [DiscoveredDevice(FAMILY, path, _HINT_MODELS.get(hint)) for path, hint in list_loupedeck_usb_ports()]

    def open(self, settings: Settings) -> LoupedeckBackend:
        return open_loupedeck(settings)

    def normalize_message(self, msg: dict[str, Any], model: DeviceModel | None = None) -> ControlEvent | None:
        if model is not None and model.family != FAMILY:
            return None
        return normalize_loupedeck_message(msg, model)
