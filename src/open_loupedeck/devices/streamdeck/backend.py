"""Stream Deck backend: wraps python-elgato-streamdeck behind :class:`DeviceBackend` (experimental).

The library (``StreamDeck`` package, MIT) and the native hidapi library it loads are imported
lazily, only when a Stream Deck is looked for: importing this module, the registry or the app
never needs them.

Library behaviour this backend relies on (python-elgato-streamdeck 0.10):

* ``DeviceManager()`` probes the hidapi native library and raises when it is missing;
  ``enumerate()`` returns one (unopened) deck object per attached Stream Deck, ``[]`` for none.
* Keys are numbered row by row from the top-left (the library already undoes the reversed column
  order of the first Original); on the Neo the two touch buttons follow the keys (8 and 9).
* ``open()`` starts a reader thread; key / dial / touchscreen callbacks run on that thread. When
  a read fails (unplug) the thread stops and closes the device, so ``is_open()`` turns false;
  ``connected()`` re-enumerates the bus.
* Images go through ``PILHelper.to_native_*_format``, which applies the model's rotation, flips
  and encoding (BMP / JPEG).
"""

from __future__ import annotations

import logging
import re
import threading
from typing import TYPE_CHECKING, Any

from ...events import ControlEvent
from ..base import DiscoveredDevice, EventCallback, UnpluggedCallback
from ..model import DeviceModel, key_id, parse_key_id
from .models import ANY_STREAMDECK, DECK_TYPES, FAMILY, STREAMDECK_MODELS, with_sizes

if TYPE_CHECKING:
    from PIL import Image

    from ...config import Settings

logger = logging.getLogger(__name__)

WATCH_INTERVAL_SEC = 1.0
"""How often the backend checks that the deck is still there (unplug detection)."""

STRIP_TARGETS = {"streamdeck_plus": "touchscreen", "streamdeck_neo": "screen"}
"""Which library display ``strip_0`` is on each model (touch strip / Neo info screen)."""

_SERIAL_PORT = re.compile(r"^(/dev/tty|/dev/cu\.|COM\d+$)", re.IGNORECASE)


class StreamDeckNotFound(RuntimeError):
    """No usable Stream Deck (none attached, none matching ``device.path``, or no hidapi).

    ``device_absent`` tells the registry that this backend saw nothing, so in ``auto`` mode the
    error of another backend (the Loupedeck one) is the one reported.
    """

    device_absent = True


# --- library access (lazy) -----------------------------------------------------------------------


def _device_manager() -> Any:
    try:
        from StreamDeck.DeviceManager import DeviceManager
    except ImportError as e:
        raise StreamDeckNotFound(
            "Stream Deck support needs the 'streamdeck' Python package (python-elgato-streamdeck)."
        ) from e
    try:
        return DeviceManager()
    except Exception as e:  # ProbeError: the hidapi native library is missing
        raise StreamDeckNotFound(
            f"Stream Deck support needs the hidapi library (hidapi.dll / libhidapi), see docs/streamdeck.md ({e})."
        ) from e


def _pil_helper() -> Any:
    from StreamDeck.ImageHelpers import PILHelper

    return PILHelper


def enumerate_decks() -> list[Any]:
    """Attached Stream Decks (unopened library objects); raises :class:`StreamDeckNotFound` when the
    library or hidapi is missing."""

    return list(_device_manager().enumerate())


# --- model mapping -------------------------------------------------------------------------------


def _deck_id(deck: Any) -> str:
    try:
        return str(deck.id())
    except Exception:
        return "?"


def base_model_for_deck(deck: Any) -> DeviceModel | None:
    """The descriptor of a library deck object (by ``deck_type()``), checked against what the
    library reports (key grid, key / dial / touch-button counts); ``None`` = unsupported."""

    model = DECK_TYPES.get(str(deck.deck_type()))
    if model is None:
        return None
    keys = model.controls_of_kind("key")
    try:
        rows, cols = deck.key_layout()
        key_count = int(deck.key_count())
        dials = int(deck.dial_count())
        touch_keys = int(deck.touch_key_count()) if hasattr(deck, "touch_key_count") else 0
    except Exception:
        logger.debug("Stream Deck %s: layout query failed", _deck_id(deck), exc_info=True)
        return None
    pedals = model.controls_of_kind("pedal")
    if pedals:
        ok = key_count == len(pedals)
    else:
        ok = (int(cols), int(rows)) == model.grid_of_keys() and key_count == len(keys)
    ok = ok and dials == len(model.controls_of_kind("knob"))
    ok = ok and touch_keys == len(model.controls_of_kind("button"))
    if not ok:
        logger.warning(
            "%s reports an unexpected layout (rows=%s cols=%s keys=%s dials=%s); not supported",
            deck.deck_type(),
            rows,
            cols,
            key_count,
            dials,
        )
        return None
    return model


def model_for_deck(deck: Any) -> DeviceModel | None:
    """:func:`base_model_for_deck` with the pixel sizes the library reports for this deck."""

    model = base_model_for_deck(deck)
    if model is None or not deck.is_visual():
        return model
    key_size = _size_of(deck, "key_image_format")
    target = STRIP_TARGETS.get(model.id)
    strip_size = _size_of(deck, f"{target}_image_format") if target else None
    return with_sizes(model, key_size, strip_size)


def _size_of(deck: Any, method: str) -> tuple[int, int] | None:
    try:
        size = getattr(deck, method)()["size"]
        return (int(size[0]), int(size[1]))
    except Exception:
        return None


# --- events --------------------------------------------------------------------------------------


def key_event(model: DeviceModel, index: int, pressed: bool) -> ControlEvent | None:
    """Library key index -> event: keys row by row, then the touch buttons (Neo), or the pedals."""

    raw = {"streamdeck": "key", "index": int(index), "pressed": bool(pressed)}
    typ = "press" if pressed else "release"
    pedals = model.ids_of_kind("pedal")
    if pedals:
        return ControlEvent(pedals[index], typ, None, raw) if 0 <= index < len(pedals) else None  # type: ignore[arg-type]
    cols, rows = model.grid_of_keys()
    if 0 <= index < cols * rows:
        return ControlEvent(key_id(index % cols, index // cols), typ, None, raw)  # type: ignore[arg-type]
    n = index - cols * rows
    buttons = model.ids_of_kind("button")
    if 0 <= n < len(buttons):
        return ControlEvent(f"button_{n}", typ, None, raw)  # type: ignore[arg-type]
    return None


def dial_event(model: DeviceModel, dial: int, kind: str, value: Any) -> ControlEvent | None:
    """``PUSH`` -> press / release of ``knob_<dial>``; ``TURN`` -> rotate by the signed steps the
    library reports (positive = clockwise = right)."""

    cid = f"knob_{int(dial)}"
    if not model.has_control(cid):
        return None
    raw = {"streamdeck": "dial", "index": int(dial), "event": kind, "value": value}
    if kind == "PUSH":
        return ControlEvent(cid, "press" if value else "release", None, raw)
    if kind == "TURN":
        try:
            steps = int(value)
        except (TypeError, ValueError):
            return None
        return ControlEvent(cid, "rotate", steps, raw) if steps else None
    return None


def touch_event(model: DeviceModel, kind: str, value: Any) -> ControlEvent | None:
    """Touch strip event (``SHORT`` / ``LONG`` tap, ``DRAG``) -> ``touch`` on ``strip_0`` at the
    touch point in strip pixels (a drag reports where it started; its end is in ``raw``)."""

    ctl = model.control("strip_0")
    if ctl is None or not ctl.has_input("touch") or not isinstance(value, dict):
        return None
    try:
        x, y = int(value["x"]), int(value["y"])
    except (KeyError, TypeError, ValueError):
        return None
    w, h = ctl.image or (1, 1)
    x, y = min(max(x, 0), w - 1), min(max(y, 0), h - 1)
    raw = {**value, "streamdeck": "touch", "event": kind}
    return ControlEvent("strip_0", "touch", (x, y), raw)


def normalize_streamdeck_message(msg: dict[str, Any], model: DeviceModel | None) -> ControlEvent | None:
    """A native message dict (the ``raw`` of this backend's events) -> event; ``None`` otherwise."""

    if model is None or model.family != FAMILY or not isinstance(msg, dict):
        return None
    what = msg.get("streamdeck")
    try:
        if what == "key":
            return key_event(model, int(msg["index"]), bool(msg.get("pressed", True)))
        if what == "dial":
            return dial_event(model, int(msg["index"]), str(msg.get("event")), msg.get("value"))
        if what == "touch":
            return touch_event(model, str(msg.get("event") or "SHORT"), msg)
    except (KeyError, TypeError, ValueError):
        return None
    return None


def _enum_name(v: Any) -> str:
    return str(getattr(v, "name", v))


# --- backend -------------------------------------------------------------------------------------


class StreamDeckBackend:
    """One opened Stream Deck (implements :class:`~..base.DeviceBackend`)."""

    family = FAMILY
    experimental = True
    """Not tested on hardware yet: the status page and the log say so."""

    def __init__(self, deck: Any, model: DeviceModel | None = None, *, watch_interval: float = WATCH_INTERVAL_SEC):
        self.deck = deck
        found = model or model_for_deck(deck)
        if found is None:
            raise StreamDeckNotFound(f"Unsupported Stream Deck: {deck.deck_type()}")
        self.model: DeviceModel = found
        self.path: str | None = _deck_id(deck)
        self._event_cb: EventCallback | None = None
        self._unplugged_cb: UnpluggedCallback | None = None
        self._unplugged = False
        self._closed = False
        self._started = False
        self._state_lock = threading.Lock()
        self._stop = threading.Event()
        self._watch_interval = watch_interval
        self._watcher: threading.Thread | None = None

    def __repr__(self) -> str:
        return f"StreamDeckBackend({self.model.id}, path={self.path!r})"

    # --- lifecycle ----------------------------------------------------------------------------

    @property
    def is_open(self) -> bool:
        if self._closed or self._unplugged:
            return False
        try:
            return bool(self.deck.is_open())
        except Exception:
            return False

    @property
    def unplugged(self) -> bool:
        return self._unplugged

    def open(self) -> None:
        """The deck itself is opened by the factory; this wires the callbacks and the watchdog."""

        if self._started:
            return
        self._started = True
        if not self.deck.is_open():
            self.deck.open()
        self.deck.set_key_callback(self._on_key)
        if self.model.controls_of_kind("knob"):
            self.deck.set_dial_callback(self._on_dial)
        if self.model.control("strip_0") is not None and self.model.control("strip_0").has_input("touch"):  # type: ignore[union-attr]
            self.deck.set_touchscreen_callback(self._on_touch)
        logger.warning(
            "%s opened (%s). Stream Deck support is experimental and untested on hardware: "
            "please report what works and what does not (docs/streamdeck.md).",
            self.model.name,
            self.path,
        )
        self._watcher = threading.Thread(target=self._watch, name="streamdeck-watch", daemon=True)
        self._watcher.start()

    def close(self) -> None:
        with self._state_lock:
            if self._closed:
                return
            self._closed = True
        self._stop.set()
        w = self._watcher
        if w is not None and w is not threading.current_thread():
            w.join(timeout=2.0)
        deck = self.deck
        for setter in ("set_key_callback", "set_dial_callback", "set_touchscreen_callback"):
            try:
                getattr(deck, setter)(None)
            except Exception:
                logger.debug("Stream Deck %s(None) failed", setter, exc_info=True)
        if not self._unplugged:
            try:
                with deck:
                    deck.reset()  # back to the Elgato standby screen instead of stale images
            except Exception:
                logger.debug("Stream Deck reset on close failed", exc_info=True)
        try:
            deck.close()
        except Exception:
            logger.debug("Stream Deck close failed", exc_info=True)

    def __enter__(self) -> StreamDeckBackend:
        self.deck.__enter__()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.deck.__exit__(*exc)

    # --- output -------------------------------------------------------------------------------

    def set_image(self, control_id: str, image: Image.Image) -> None:
        ctl = self.model.control(control_id)
        if ctl is None or ctl.image is None:
            logger.debug("%s: %s takes no image; skipped", self.model.name, control_id)
            return
        rgb = _flatten(image, ctl.image)
        helper = _pil_helper()
        deck = self.deck
        if ctl.kind == "key":
            col, row = parse_key_id(control_id) or (0, 0)
            cols, _rows = self.model.grid_of_keys()
            native = helper.to_native_key_format(deck, rgb)
            self._write(lambda: deck.set_key_image(row * cols + col, native))
            return
        target = STRIP_TARGETS.get(self.model.id) if control_id == "strip_0" else None
        if target == "touchscreen":
            w, h = ctl.image
            native = helper.to_native_touchscreen_format(deck, rgb)
            self._write(lambda: deck.set_touchscreen_image(native, 0, 0, w, h))
        elif target == "screen":
            native = helper.to_native_screen_format(deck, rgb)
            self._write(lambda: deck.set_screen_image(native))
        else:
            logger.debug("No drawable target for %s", control_id)

    def set_brightness(self, pct: int) -> None:
        if not self.model.brightness:
            return
        level = min(max(int(pct), 0), 100)
        self._write(lambda: self.deck.set_brightness(level))

    def set_led(self, control_id: str, rgb: tuple[int, int, int]) -> None:
        ctl = self.model.control(control_id)
        buttons = self.model.ids_of_kind("button")
        if ctl is None or ctl.led is None or control_id not in buttons:
            logger.warning("set_led: %s has no LED on %s", control_id, self.model.name)
            return
        cols, rows = self.model.grid_of_keys()
        index = cols * rows + buttons.index(control_id)  # touch buttons follow the keys
        r, g, b = (min(max(int(c), 0), 255) for c in rgb[:3])
        self._write(lambda: self.deck.set_key_color(index, r, g, b))

    def _write(self, fn: Any) -> None:
        if self._closed or self._unplugged:
            return
        try:
            with self.deck:
                fn()
        except Exception as e:
            if self._deck_alive():
                logger.warning("Stream Deck write failed: %s", e)
            else:
                self._signal_unplugged()

    # --- input --------------------------------------------------------------------------------

    def set_event_callback(self, callback: EventCallback | None) -> None:
        self._event_cb = callback

    def set_unplugged_callback(self, callback: UnpluggedCallback | None) -> None:
        self._unplugged_cb = callback
        if callback is not None and self._unplugged:
            callback()  # went away before anyone listened

    def _dispatch(self, ev: ControlEvent | None) -> None:
        cb = self._event_cb
        if ev is None or cb is None or self._closed:
            return
        try:
            cb(ev)
        except Exception:
            logger.exception("Stream Deck event dispatch failed for %r", ev)

    def _on_key(self, _deck: Any, index: int, pressed: bool) -> None:
        self._dispatch(key_event(self.model, int(index), bool(pressed)))

    def _on_dial(self, _deck: Any, dial: int, kind: Any, value: Any) -> None:
        self._dispatch(dial_event(self.model, int(dial), _enum_name(kind), value))

    def _on_touch(self, _deck: Any, kind: Any, value: Any) -> None:
        self._dispatch(touch_event(self.model, _enum_name(kind), value))

    # --- unplug -------------------------------------------------------------------------------

    def _deck_alive(self) -> bool:
        try:
            return bool(self.deck.is_open()) and bool(self.deck.connected())
        except Exception:
            return False

    def _watch(self) -> None:
        while not self._stop.wait(self._watch_interval):
            if self._closed:
                return
            if not self._deck_alive():
                self._signal_unplugged()
                return

    def _signal_unplugged(self) -> None:
        with self._state_lock:
            if self._unplugged or self._closed:
                return
            self._unplugged = True
        self._stop.set()
        logger.info("Stream Deck %s disconnected", self.path)
        cb = self._unplugged_cb
        if cb is not None:
            try:
                cb()
            except Exception:
                logger.exception("Stream Deck unplug callback failed")


def _flatten(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    """RGB copy of ``image`` at ``size`` (transparency over black: the library encodes BMP/JPEG)."""

    from PIL import Image as PILImage

    img = image if image.size == tuple(size) else image.resize(tuple(size))
    if img.mode in ("RGBA", "LA", "P"):
        rgba = img.convert("RGBA")
        out = PILImage.new("RGB", rgba.size, (0, 0, 0))
        out.paste(rgba, mask=rgba.getchannel("A"))
        return out
    return img.convert("RGB")


# --- opening -------------------------------------------------------------------------------------


def _wanted_model(name: str | None) -> DeviceModel | None:
    n = (name or "").strip().lower()
    if not n or n in ("auto", ANY_STREAMDECK):
        return None
    for m in STREAMDECK_MODELS:
        if m.matches_name(n):
            return m
    return None


def _serial_of(deck: Any) -> str | None:
    try:
        return str(deck.get_serial_number()).strip()
    except Exception:
        return None


def open_streamdeck(settings: Settings) -> StreamDeckBackend:
    """Open a Stream Deck per ``settings.device``.

    ``device.model``: a Stream Deck model is preferred when several decks are attached (another
    one is still opened if it is the only deck); ``streamdeck`` / ``auto`` take any.
    ``device.path``: the deck's HID path (``deck.id()``) or its serial number; a serial-port name
    (a Loupedeck path) never selects a Stream Deck.
    """

    decks = enumerate_decks()
    found: list[tuple[Any, DeviceModel]] = []
    for deck in decks:
        model = model_for_deck(deck)
        if model is None:
            logger.warning("Stream Deck %r (%s) is not supported yet; skipped", deck.deck_type(), _deck_id(deck))
            continue
        found.append((deck, model))
    if not found:
        raise StreamDeckNotFound("No Stream Deck found.")

    wanted = _wanted_model(settings.device.model)
    if wanted is not None:
        found.sort(key=lambda dm: dm[1].id != wanted.id)  # stable: the wanted model first

    path = (settings.device.path or "").strip()
    by_serial = False
    if path:
        exact = [dm for dm in found if _deck_id(dm[0]) == path]
        if exact:
            found = exact
        elif _SERIAL_PORT.match(path):
            raise StreamDeckNotFound(f"device.path {path!r} is a serial port, not a Stream Deck.")
        else:
            by_serial = True

    last_err: Exception | None = None
    for deck, model in found:
        try:
            deck.open()
        except Exception as e:
            last_err = e
            logger.debug("Stream Deck %s: open failed: %s", _deck_id(deck), e)
            continue
        if by_serial and _serial_of(deck) != path:
            try:
                deck.close()
            except Exception:
                logger.debug("Stream Deck close failed", exc_info=True)
            continue
        if wanted is not None and model.id != wanted.id:
            logger.warning("device.model is %s but the attached deck is a %s", wanted.id, model.name)
        logger.info("Stream Deck open: %s (%s)", model.name, _deck_id(deck))
        return StreamDeckBackend(deck, model)

    if last_err is None:
        raise StreamDeckNotFound(f"No Stream Deck with path or serial number {path!r}.")
    raise RuntimeError(open_failure_message(last_err)) from last_err


def open_failure_message(last_err: Exception | None) -> str:
    return (
        "A Stream Deck is attached but could not be opened. Quit the Elgato Stream Deck software "
        "(it keeps the device to itself); on Linux install udev/70-streamdeck.rules "
        f"(see docs/streamdeck.md).\n\nLast error: {last_err}"
    )


# --- registry entry ------------------------------------------------------------------------------


class StreamDeckBackendFactory:
    """Registry entry of the Stream Deck family (auto-detected after the Loupedeck one)."""

    family = FAMILY
    models = STREAMDECK_MODELS

    def discover(self) -> list[DiscoveredDevice]:
        try:
            decks = enumerate_decks()
        except StreamDeckNotFound as e:
            logger.debug("Stream Deck discovery: %s", e)
            return []
        return [DiscoveredDevice(FAMILY, _deck_id(d), model_for_deck(d)) for d in decks]

    def open(self, settings: Settings) -> StreamDeckBackend:
        return open_streamdeck(settings)

    def normalize_message(self, msg: dict[str, Any], model: DeviceModel | None = None) -> ControlEvent | None:
        return normalize_streamdeck_message(msg, model)
