"""Stream Deck backend over a fake ``StreamDeck`` package (no hidapi, no hardware).

The fake decks mirror what python-elgato-streamdeck reports for each model (``deck_type()``,
``key_layout()``, counts, image formats). One test also runs the real library classes over its
``Dummy`` transport when the package is installed.
"""

from __future__ import annotations

import asyncio
import enum
import subprocess
import sys
import threading
import time
import types
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from open_loupedeck.config import DeviceConfig, Settings
from open_loupedeck.deck_skin import apply_page_skin
from open_loupedeck.devices.base import DeviceBackend
from open_loupedeck.devices.registry import DeviceRegistry, known_models, model_by_name
from open_loupedeck.devices.streamdeck import backend as sd
from open_loupedeck.devices.streamdeck.models import (
    STREAMDECK_MINI,
    STREAMDECK_MK2,
    STREAMDECK_MODELS,
    STREAMDECK_NEO,
    STREAMDECK_PEDAL,
    STREAMDECK_PLUS,
    STREAMDECK_XL,
)
from open_loupedeck.devices.virtual.backend import VirtualBackendFactory
from open_loupedeck.events import ControlEvent
from tests.fake_backend import FakeBackend, FakeFactory
from tests.test_device_agent import AgentHarness, _rec, _settle

DialEventType = enum.Enum("DialEventType", "TURN PUSH")
TouchscreenEventType = enum.Enum("TouchscreenEventType", "SHORT LONG DRAG")

# deck_type, (rows, cols), key count, dials, touch keys, visual, key size, touchscreen size, screen size
SPECS: dict[str, tuple[Any, ...]] = {
    "mini": ("Stream Deck Mini", (2, 3), 6, 0, 0, True, (80, 80), None, None),
    "original": ("Stream Deck Original", (3, 5), 15, 0, 0, True, (72, 72), None, None),
    "xl": ("Stream Deck XL", (4, 8), 32, 0, 0, True, (96, 96), None, None),
    "plus": ("Stream Deck +", (2, 4), 8, 4, 0, True, (120, 120), (800, 100), None),
    "neo": ("Stream Deck Neo", (2, 4), 8, 0, 2, True, (96, 96), None, (248, 58)),
    "pedal": ("Stream Deck Pedal", (1, 3), 3, 0, 0, False, (0, 0), None, None),
}
MODEL_OF_SPEC = {
    "mini": STREAMDECK_MINI,
    "original": STREAMDECK_MK2,
    "xl": STREAMDECK_XL,
    "plus": STREAMDECK_PLUS,
    "neo": STREAMDECK_NEO,
    "pedal": STREAMDECK_PEDAL,
}


class FakeDeck:
    """Plays a python-elgato-streamdeck deck object; records every call."""

    def __init__(self, spec: str = "original", path: str = "hid-1", serial: str = "SN1", **over: Any) -> None:
        (self.type, self.layout, self.keys, self.dials, self.touch_keys, self.visual, self.key_size, self.ts_size,
         self.screen_size) = SPECS[spec]  # fmt: skip
        for k, v in over.items():
            setattr(self, k, v)
        self.path = path
        self.serial = serial
        self.opened = False
        self.open_calls = 0
        self.closed = False
        self.plugged = True
        self.fail_open: Exception | None = None
        self.fail_write: Exception | None = None
        self.calls: list[tuple[Any, ...]] = []
        self.key_callback: Any = None
        self.dial_callback: Any = None
        self.touchscreen_callback: Any = None
        self.lock = threading.RLock()
        self.lock_depth = 0

    # identity / layout
    def deck_type(self) -> str:
        return self.type

    def key_layout(self) -> tuple[int, int]:
        return self.layout

    def key_count(self) -> int:
        return self.keys

    def dial_count(self) -> int:
        return self.dials

    def touch_key_count(self) -> int:
        return self.touch_keys

    def is_visual(self) -> bool:
        return self.visual

    def is_touch(self) -> bool:
        return self.ts_size is not None

    def _fmt(self, size: Any) -> dict[str, Any]:
        return {"size": size or (0, 0), "format": "JPEG", "flip": (False, False), "rotation": 0}

    def key_image_format(self) -> dict[str, Any]:
        return self._fmt(self.key_size)

    def touchscreen_image_format(self) -> dict[str, Any]:
        return self._fmt(self.ts_size)

    def screen_image_format(self) -> dict[str, Any]:
        return self._fmt(self.screen_size)

    def id(self) -> str:
        return self.path

    def get_serial_number(self) -> str:
        if not self.opened:
            raise RuntimeError("not open")
        return self.serial

    # lifecycle
    def open(self) -> None:
        self.open_calls += 1
        if self.fail_open is not None:
            raise self.fail_open
        self.opened = True

    def close(self) -> None:
        self.opened = False
        self.closed = True

    def is_open(self) -> bool:
        return self.opened

    def connected(self) -> bool:
        return self.plugged

    def __enter__(self) -> None:
        self.lock.acquire()
        self.lock_depth += 1

    def __exit__(self, *exc: Any) -> None:
        self.lock_depth -= 1
        self.lock.release()

    # output
    def _rec(self, *call: Any) -> None:
        if self.fail_write is not None:
            raise self.fail_write
        assert self.lock_depth > 0, "writes hold the deck's update lock"
        self.calls.append(call)

    def set_key_image(self, key: int, image: bytes) -> None:
        self._rec("key", key, image)

    def set_touchscreen_image(self, image: bytes, x: int = 0, y: int = 0, w: int = 0, h: int = 0) -> None:
        self._rec("touchscreen", image, x, y, w, h)

    def set_screen_image(self, image: bytes) -> None:
        self._rec("screen", image)

    def set_brightness(self, pct: int) -> None:
        self._rec("brightness", pct)

    def set_key_color(self, key: int, r: int, g: int, b: int) -> None:
        self._rec("color", key, r, g, b)

    def reset(self) -> None:
        self._rec("reset")

    # callbacks (the library calls them from its reader thread)
    def set_key_callback(self, cb: Any) -> None:
        self.key_callback = cb

    def set_dial_callback(self, cb: Any) -> None:
        self.dial_callback = cb

    def set_touchscreen_callback(self, cb: Any) -> None:
        self.touchscreen_callback = cb

    def key(self, index: int, pressed: bool) -> None:
        self.key_callback(self, index, pressed)

    def dial(self, index: int, kind: str, value: Any) -> None:
        self.dial_callback(self, index, DialEventType[kind], value)

    def touch(self, kind: str, value: dict[str, int]) -> None:
        self.touchscreen_callback(self, TouchscreenEventType[kind], value)


class FakeLib:
    """Installs a fake ``StreamDeck`` package in ``sys.modules``."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.decks: list[FakeDeck] = []
        self.probe_error: Exception | None = None
        self.native: list[tuple[str, tuple[int, int], str]] = []
        lib = self

        class DeviceManager:
            def __init__(self, transport: str | None = None) -> None:
                if lib.probe_error is not None:
                    raise lib.probe_error

            def enumerate(self) -> list[FakeDeck]:
                return list(lib.decks)

        def native(kind: str) -> Any:
            def to_native(deck: Any, image: Image.Image) -> bytes:
                lib.native.append((kind, image.size, image.mode))
                return f"{kind}:{image.size[0]}x{image.size[1]}".encode()

            return to_native

        pkg = types.ModuleType("StreamDeck")
        pkg.__path__ = []  # type: ignore[attr-defined]
        dm = types.ModuleType("StreamDeck.DeviceManager")
        dm.DeviceManager = DeviceManager  # type: ignore[attr-defined]
        helpers = types.ModuleType("StreamDeck.ImageHelpers")
        helpers.__path__ = []  # type: ignore[attr-defined]
        pil = types.ModuleType("StreamDeck.ImageHelpers.PILHelper")
        pil.to_native_key_format = native("key")  # type: ignore[attr-defined]
        pil.to_native_touchscreen_format = native("touchscreen")  # type: ignore[attr-defined]
        pil.to_native_screen_format = native("screen")  # type: ignore[attr-defined]
        helpers.PILHelper = pil  # type: ignore[attr-defined]
        pkg.DeviceManager = dm  # type: ignore[attr-defined]
        pkg.ImageHelpers = helpers  # type: ignore[attr-defined]
        for name, mod in (
            ("StreamDeck", pkg),
            ("StreamDeck.DeviceManager", dm),
            ("StreamDeck.ImageHelpers", helpers),
            ("StreamDeck.ImageHelpers.PILHelper", pil),
        ):
            monkeypatch.setitem(sys.modules, name, mod)


@pytest.fixture()
def lib(monkeypatch: pytest.MonkeyPatch) -> FakeLib:
    return FakeLib(monkeypatch)


def _settings(model: str = "auto", path: str = "") -> Settings:
    return Settings(device=DeviceConfig(model=model, path=path))


def _backend(spec: str = "original", **kw: Any) -> tuple[sd.StreamDeckBackend, FakeDeck]:
    deck = FakeDeck(spec, **kw)
    deck.open()
    b = sd.StreamDeckBackend(deck, watch_interval=kw.get("watch", 0.02))
    return b, deck


def _wait(cond: Any, timeout: float = 2.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return cond()


# --- models -------------------------------------------------------------------------------------


@pytest.mark.parametrize("model", STREAMDECK_MODELS, ids=lambda m: m.id)
def test_model_is_consistent(model):
    assert model.problems() == []
    assert model.family == "streamdeck"
    assert model.name.endswith("(experimental)")
    assert model.config_names and model.config_names[0] == model.id
    rects = [(c.id, c.position) for c in model.controls]
    for i, (a, pa) in enumerate(rects):
        for b, pb in rects[i + 1 :]:
            overlap = pa.x < pb.x + pb.w and pb.x < pa.x + pa.w and pa.y < pb.y + pb.h and pb.y < pa.y + pa.h
            assert not overlap, f"{a} overlaps {b}"
    for c in model.controls:
        if c.kind != "key":
            fk = model.feedback_key_for(c.id)
            assert fk is None or model.control(fk).has_image


def test_model_contents():
    def kinds(m):
        return {k: len(m.controls_of_kind(k)) for k in ("key", "button", "knob", "strip", "pedal")}

    assert kinds(STREAMDECK_MINI) == {"key": 6, "button": 0, "knob": 0, "strip": 0, "pedal": 0}
    assert STREAMDECK_MINI.grid_of_keys() == (3, 2) and STREAMDECK_MINI.image_size("key_2_1") == (80, 80)
    assert STREAMDECK_MK2.grid_of_keys() == (5, 3) and STREAMDECK_MK2.image_size("key_4_2") == (72, 72)
    assert STREAMDECK_XL.grid_of_keys() == (8, 4) and STREAMDECK_XL.image_size("key_7_3") == (96, 96)
    assert kinds(STREAMDECK_PLUS) == {"key": 8, "button": 0, "knob": 4, "strip": 1, "pedal": 0}
    assert STREAMDECK_PLUS.image_size("key_3_1") == (120, 120)
    assert STREAMDECK_PLUS.control("strip_0").inputs == ("touch",)
    assert STREAMDECK_PLUS.image_size("strip_0") == (800, 100)
    assert [STREAMDECK_PLUS.feedback_key_for(f"knob_{n}") for n in range(4)] == [f"key_{n}_1" for n in range(4)]
    assert all(STREAMDECK_PLUS.control(f"knob_{n}").inputs == ("press", "rotate") for n in range(4))
    assert kinds(STREAMDECK_NEO) == {"key": 8, "button": 2, "knob": 0, "strip": 1, "pedal": 0}
    assert STREAMDECK_NEO.image_size("strip_0") == (248, 58) and STREAMDECK_NEO.control("strip_0").inputs == ()
    assert [c.led for c in STREAMDECK_NEO.controls_of_kind("button")] == ["rgb", "rgb"]
    assert kinds(STREAMDECK_PEDAL) == {"key": 0, "button": 0, "knob": 0, "strip": 0, "pedal": 3}
    assert STREAMDECK_PEDAL.image_controls() == [] and not STREAMDECK_PEDAL.brightness
    assert all(c.inputs == ("press",) for c in STREAMDECK_PEDAL.controls)


def test_registry_knows_the_models_by_name():
    ids = {m.id for m in known_models()}
    assert {m.id for m in STREAMDECK_MODELS} <= ids
    assert model_by_name("streamdeck") is STREAMDECK_MK2  # any deck; 5 x 3 key coordinates
    assert model_by_name("streamdeck_original") is STREAMDECK_MK2
    assert model_by_name("streamdeck_plus") is STREAMDECK_PLUS


@pytest.mark.parametrize("spec", list(SPECS))
def test_deck_type_maps_to_the_model(spec):
    assert sd.model_for_deck(FakeDeck(spec)) == MODEL_OF_SPEC[spec]


def test_image_sizes_come_from_the_library():
    m = sd.model_for_deck(FakeDeck("plus", key_size=(112, 112), ts_size=(1200, 100)))
    assert m.id == "streamdeck_plus" and m.image_size("key_0_0") == (112, 112)
    assert m.image_size("strip_0") == (1200, 100)
    assert m.control("knob_0") == STREAMDECK_PLUS.control("knob_0")
    # nothing usable reported -> the documented sizes
    assert sd.model_for_deck(FakeDeck("xl", key_size=(0, 0))) is STREAMDECK_XL


def test_unknown_or_inconsistent_decks_are_not_supported():
    assert sd.model_for_deck(FakeDeck("xl", type="Stream Deck Studio")) is None
    assert sd.model_for_deck(FakeDeck("xl", layout=(4, 9), keys=36)) is None
    assert sd.model_for_deck(FakeDeck("plus", dials=6)) is None


# --- ids and events -------------------------------------------------------------------------------


def test_key_indices_are_row_by_row():
    for model in (STREAMDECK_MINI, STREAMDECK_MK2, STREAMDECK_XL, STREAMDECK_PLUS, STREAMDECK_NEO):
        cols, rows = model.grid_of_keys()
        for i in range(cols * rows):
            ev = sd.key_event(model, i, True)
            assert ev.control_id == f"key_{i % cols}_{i // cols}" and ev.type == "press"
    assert sd.key_event(STREAMDECK_MK2, 5, False) == ControlEvent("key_0_1", "release")
    assert sd.key_event(STREAMDECK_MK2, 15, True) is None
    assert sd.key_event(STREAMDECK_NEO, 8, True).control_id == "button_0"
    assert sd.key_event(STREAMDECK_NEO, 9, True).control_id == "button_1"
    assert sd.key_event(STREAMDECK_NEO, 10, True) is None
    assert [sd.key_event(STREAMDECK_PEDAL, i, True).control_id for i in range(3)] == ["pedal_0", "pedal_1", "pedal_2"]
    assert sd.key_event(STREAMDECK_PEDAL, 3, True) is None


def test_callbacks_become_events():
    b, deck = _backend("plus")
    got: list[ControlEvent] = []
    b.set_event_callback(got.append)
    b.open()
    try:
        deck.key(6, True)
        deck.key(6, False)
        deck.dial(1, "TURN", 2)
        deck.dial(1, "TURN", -1)
        deck.dial(1, "TURN", 0)  # no movement: nothing
        deck.dial(3, "PUSH", True)
        deck.dial(3, "PUSH", False)
        deck.dial(7, "PUSH", True)  # unknown dial
        deck.touch("SHORT", {"x": 410, "y": 50})
        deck.touch("LONG", {"x": 5000, "y": -3})  # clamped to the strip
        deck.touch("DRAG", {"x": 100, "y": 20, "x_out": 300, "y_out": 30})
    finally:
        b.close()
    assert [(e.control_id, e.type, e.value) for e in got] == [
        ("key_2_1", "press", None),
        ("key_2_1", "release", None),
        ("knob_1", "rotate", 2),
        ("knob_1", "rotate", -1),
        ("knob_3", "press", None),
        ("knob_3", "release", None),
        ("strip_0", "touch", (410, 50)),
        ("strip_0", "touch", (799, 0)),
        ("strip_0", "touch", (100, 20)),
    ]
    assert got[2].direction == "right" and got[3].direction == "left"
    assert got[-1].raw["x_out"] == 300 and got[-1].raw["event"] == "DRAG"


def test_callbacks_are_wired_per_model_and_errors_are_contained():
    b, deck = _backend("original")
    b.open()
    assert deck.key_callback is not None and deck.dial_callback is None and deck.touchscreen_callback is None

    def boom(_ev: ControlEvent) -> None:
        raise ValueError("agent bug")

    b.set_event_callback(boom)
    deck.key(0, True)  # logged, never raised into the library's reader thread
    b.close()
    assert deck.key_callback is None
    b2, deck2 = _backend("neo")
    b2.open()
    assert deck2.dial_callback is None and deck2.touchscreen_callback is None  # the info screen has no touch
    b2.close()


def test_normalize_message_round_trip():
    f = sd.StreamDeckBackendFactory()
    for ev in (
        sd.key_event(STREAMDECK_XL, 9, True),
        sd.dial_event(STREAMDECK_PLUS, 2, "TURN", -3),
        sd.touch_event(STREAMDECK_PLUS, "SHORT", {"x": 12, "y": 34}),
    ):
        model = STREAMDECK_PLUS if ev.control_id.startswith(("knob", "strip")) else STREAMDECK_XL
        assert f.normalize_message(ev.raw, model) == ev
    assert f.normalize_message({"action": "push", "id": "1"}, STREAMDECK_MK2) is None
    assert f.normalize_message({"streamdeck": "key", "index": 0}, None) is None
    assert DeviceRegistry([f]).normalize_message({"streamdeck": "key", "index": 4}, STREAMDECK_MINI) == ControlEvent(
        "key_1_1", "press"
    )


# --- output ---------------------------------------------------------------------------------------


def test_set_image_converts_to_the_native_format(lib: FakeLib):
    b, deck = _backend("original")
    b.set_image("key_3_1", Image.new("RGBA", (72, 72), (255, 0, 0, 128)))
    assert lib.native == [("key", (72, 72), "RGB")]
    assert deck.calls == [("key", 8, b"key:72x72")]  # row 1 * 5 cols + col 3
    b.set_image("key_0_0", Image.new("RGB", (90, 90)))  # wrong size: resized first
    assert lib.native[-1] == ("key", (72, 72), "RGB") and deck.calls[-1][1] == 0
    b.set_image("knob_0", Image.new("RGB", (72, 72)))  # no such control: skipped
    b.set_image("key_9_9", Image.new("RGB", (72, 72)))
    assert len(deck.calls) == 2

    plus, pdeck = _backend("plus")
    plus.set_image("strip_0", Image.new("RGBA", (800, 100)))
    plus.set_image("key_1_0", Image.new("RGBA", (120, 120)))
    assert pdeck.calls == [("touchscreen", b"touchscreen:800x100", 0, 0, 800, 100), ("key", 1, b"key:120x120")]

    neo, ndeck = _backend("neo")
    neo.set_image("strip_0", Image.new("RGBA", (248, 58)))
    neo.set_image("button_0", Image.new("RGBA", (96, 96)))  # LED only
    assert ndeck.calls == [("screen", b"screen:248x58")]

    pedal, peddeck = _backend("pedal")
    pedal.set_image("pedal_0", Image.new("RGBA", (10, 10)))
    assert peddeck.calls == []


def test_transparent_pixels_are_drawn_black(lib: FakeLib):
    img = Image.new("RGBA", (72, 72), (255, 255, 255, 0))
    out = sd._flatten(img, (72, 72))
    assert out.mode == "RGB" and out.getpixel((0, 0)) == (0, 0, 0)


def test_skin_draws_every_display_of_the_model(lib: FakeLib, tmp_path: Path):
    plus, deck = _backend("plus")
    apply_page_skin(plus, {"name": "A", "controls": {"key_0_0": {"text": "hi"}}}, tmp_path, {})
    keys = [c[1] for c in deck.calls if c[0] == "key"]
    assert keys == list(range(8))
    assert [c[0] for c in deck.calls].count("touchscreen") == 1
    assert ("key", (120, 120), "RGB") in lib.native and ("touchscreen", (800, 100), "RGB") in lib.native


def test_brightness_and_leds():
    b, deck = _backend("xl")
    b.set_brightness(55)
    b.set_brightness(150)
    b.set_brightness(-4)
    assert deck.calls == [("brightness", 55), ("brightness", 100), ("brightness", 0)]
    b.set_led("key_0_0", (1, 2, 3))  # no LED: warning only
    assert len(deck.calls) == 3

    neo, ndeck = _backend("neo")
    neo.set_led("button_0", (255, 0, 0))
    neo.set_led("button_1", (0, 300, -1))
    assert ndeck.calls == [("color", 8, 255, 0, 0), ("color", 9, 0, 255, 0)]  # touch buttons follow the keys

    pedal, pdeck = _backend("pedal")
    pedal.set_brightness(40)  # no screen
    assert pdeck.calls == []


def test_backend_satisfies_the_protocol_and_locks():
    b, deck = _backend("mini")
    assert isinstance(b, DeviceBackend)
    assert b.path == "hid-1" and b.model is STREAMDECK_MINI and b.experimental
    with b:
        assert deck.lock_depth == 1
    assert deck.lock_depth == 0


# --- lifecycle and unplug -------------------------------------------------------------------------


def test_close_resets_the_deck_and_is_idempotent():
    b, deck = _backend("original")
    b.open()
    assert b.is_open
    b.close()
    b.close()
    assert deck.calls == [("reset",)] and deck.closed and not b.is_open
    b.set_brightness(10)  # after close: ignored
    assert deck.calls == [("reset",)]


def test_unplug_is_detected_and_signalled_once():
    b, deck = _backend("plus")
    fired: list[int] = []
    b.set_unplugged_callback(lambda: fired.append(1))
    b.open()
    assert not b.unplugged
    deck.plugged = False  # the library's connected() no longer finds the deck
    assert _wait(lambda: fired == [1])
    time.sleep(0.05)
    assert fired == [1] and b.unplugged and not b.is_open
    late: list[int] = []
    b.set_unplugged_callback(lambda: late.append(1))  # registered after the fact: fired at once
    assert late == [1]
    b.close()
    assert ("reset",) not in deck.calls and deck.closed  # nothing is written to a gone device


def test_reader_thread_closing_the_deck_counts_as_unplug():
    b, deck = _backend("xl")
    fired = threading.Event()
    b.set_unplugged_callback(fired.set)
    b.open()
    deck.opened = False  # the library closes the device when a read fails
    assert fired.wait(2.0)


def test_failed_write_on_a_gone_deck_signals_unplug(lib: FakeLib):
    b, deck = _backend("original", watch=60)
    fired: list[int] = []
    b.set_unplugged_callback(lambda: fired.append(1))
    b.open()
    deck.fail_write = OSError("write failed")
    b.set_brightness(30)  # still connected: logged only
    assert fired == []
    deck.plugged = False
    b.set_image("key_0_0", Image.new("RGB", (72, 72)))
    assert fired == [1] and b.unplugged
    b.close()


# --- discovery and opening ------------------------------------------------------------------------


def test_discovery_with_zero_one_two_decks(lib: FakeLib):
    f = sd.StreamDeckBackendFactory()
    assert f.discover() == []
    lib.decks = [FakeDeck("xl", path="a")]
    assert [d.to_dict() for d in f.discover()] == [{"backend": "streamdeck", "path": "a", "model": "streamdeck_xl"}]
    lib.decks.append(FakeDeck("neo", path="b"))
    assert [(d.path, d.model.id) for d in f.discover()] == [("a", "streamdeck_xl"), ("b", "streamdeck_neo")]
    assert not any(d.opened for d in lib.decks)  # discovery never opens a deck


def test_discovery_without_hidapi_or_without_the_package(lib: FakeLib, monkeypatch: pytest.MonkeyPatch):
    lib.decks = [FakeDeck()]
    lib.probe_error = RuntimeError("Probe failed to find any functional HID backend.")
    assert sd.StreamDeckBackendFactory().discover() == []
    with pytest.raises(sd.StreamDeckNotFound, match="hidapi"):
        sd.open_streamdeck(_settings())
    monkeypatch.setitem(sys.modules, "StreamDeck.DeviceManager", None)  # package not installed
    assert sd.StreamDeckBackendFactory().discover() == []
    with pytest.raises(sd.StreamDeckNotFound, match="streamdeck"):
        sd.open_streamdeck(_settings())


def test_open_with_no_deck_is_a_device_absent_error(lib: FakeLib):
    with pytest.raises(sd.StreamDeckNotFound) as err:
        sd.StreamDeckBackendFactory().open(_settings())
    assert err.value.device_absent
    lib.decks = [FakeDeck("xl", type="Stream Deck Studio")]  # unsupported model only
    with pytest.raises(sd.StreamDeckNotFound):
        sd.open_streamdeck(_settings())


def test_open_one_deck(lib: FakeLib):
    lib.decks = [FakeDeck("plus", path="p1")]
    b = sd.open_streamdeck(_settings())
    assert b.model.id == "streamdeck_plus" and b.path == "p1" and lib.decks[0].opened


def test_busy_deck_reports_the_elgato_software(lib: FakeLib):
    lib.decks = [FakeDeck("xl")]
    lib.decks[0].fail_open = OSError("Could not open HID device.")
    with pytest.raises(RuntimeError, match="Elgato") as err:
        sd.open_streamdeck(_settings())
    assert not getattr(err.value, "device_absent", False)


def test_device_path_selects_by_hid_path_or_serial(lib: FakeLib):
    a, b = FakeDeck("xl", path="hid-a", serial="AAA"), FakeDeck("mini", path="hid-b", serial="BBB")
    lib.decks = [a, b]
    assert sd.open_streamdeck(_settings(path="hid-b")).deck is b and not a.opened
    b.opened = False
    got = sd.open_streamdeck(_settings(path="BBB"))
    assert got.deck is b and a.closed and not a.opened  # a was opened to read its serial, then closed
    with pytest.raises(sd.StreamDeckNotFound, match="ZZZ"):
        sd.open_streamdeck(_settings(path="ZZZ"))
    a.open_calls = b.open_calls = 0
    for port in ("/dev/ttyACM0", "COM5", "/dev/cu.usbmodem1"):  # a Loupedeck path: never a Stream Deck
        with pytest.raises(sd.StreamDeckNotFound):
            sd.open_streamdeck(_settings(path=port))
    assert a.open_calls == b.open_calls == 0


def test_device_model_prefers_that_model_among_several(lib: FakeLib):
    lib.decks = [FakeDeck("xl", path="x"), FakeDeck("mini", path="m")]
    assert sd.open_streamdeck(_settings("streamdeck_mini")).model.id == "streamdeck_mini"
    for d in lib.decks:
        d.opened = False
    assert sd.open_streamdeck(_settings("streamdeck")).model.id == "streamdeck_xl"  # any: the first one
    for d in lib.decks:
        d.opened = False
    lib.decks = [FakeDeck("xl", path="x")]
    assert sd.open_streamdeck(_settings("streamdeck_plus")).model.id == "streamdeck_xl"  # the only deck


# --- registry rules -------------------------------------------------------------------------------


def test_auto_prefers_a_loupedeck_and_keeps_its_error(lib: FakeLib):
    from open_loupedeck.devices.loupedeck.models import LOUPEDECK_LIVE_S

    loupe = FakeFactory("loupedeck", (LOUPEDECK_LIVE_S,))
    reg = DeviceRegistry([loupe, sd.StreamDeckBackendFactory(), VirtualBackendFactory()])
    lib.decks = [FakeDeck("xl")]
    assert isinstance(reg.open_backend(_settings()), FakeBackend)  # a connected Loupedeck wins
    assert not lib.decks[0].opened  # the Stream Deck was not even opened
    loupe.fail = RuntimeError("No Loupedeck found. Check device.path")
    assert reg.open_backend(_settings()).model.id == "streamdeck_xl"  # no Loupedeck: the Stream Deck
    lib.decks = []
    with pytest.raises(RuntimeError, match="No Loupedeck found"):  # nothing at all: the Loupedeck hint
        reg.open_backend(_settings())
    lib.decks = [FakeDeck("xl")]
    lib.decks[0].fail_open = OSError("busy")
    with pytest.raises(RuntimeError, match="Elgato"):  # a deck is there but busy: say so
        reg.open_backend(_settings())


def test_device_model_names_the_streamdeck_backend(lib: FakeLib):
    from open_loupedeck.devices.loupedeck.models import LOUPEDECK_LIVE_S

    loupe = FakeFactory("loupedeck", (LOUPEDECK_LIVE_S,))
    reg = DeviceRegistry([loupe, sd.StreamDeckBackendFactory()])
    lib.decks = [FakeDeck("neo")]
    assert reg.open_backend(_settings("streamdeck_neo")).model.id == "streamdeck_neo"
    assert reg.open_backend(_settings("streamdeck")).model.id == "streamdeck_neo"
    assert loupe.opened == []
    lib.decks = []
    with pytest.raises(sd.StreamDeckNotFound):
        reg.open_backend(_settings("streamdeck_xl"))


def test_importing_the_app_never_imports_the_library():
    code = (
        "import sys, open_loupedeck.app, open_loupedeck.web_app\n"
        "from open_loupedeck.devices import registry\n"
        "registry.known_models(); registry.model_by_name('streamdeck_xl')\n"
        "import open_loupedeck.devices.streamdeck.backend\n"
        "print(sorted(m for m in sys.modules if m.split('.')[0] == 'StreamDeck'))\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
        env={**__import__("os").environ, "PYTHONPATH": str(Path(__file__).resolve().parent.parent / "src")},
    )
    assert out.stdout.strip() == "[]"


# --- the real library (when installed), over its Dummy transport ----------------------------------


def test_real_library_classes_match_the_models():
    pytest.importorskip("StreamDeck")
    from StreamDeck.Devices.StreamDeckMini import StreamDeckMini
    from StreamDeck.Devices.StreamDeckNeo import StreamDeckNeo
    from StreamDeck.Devices.StreamDeckOriginal import StreamDeckOriginal
    from StreamDeck.Devices.StreamDeckOriginalV2 import StreamDeckOriginalV2
    from StreamDeck.Devices.StreamDeckPedal import StreamDeckPedal
    from StreamDeck.Devices.StreamDeckPlus import StreamDeckPlus
    from StreamDeck.Devices.StreamDeckXL import StreamDeckXL
    from StreamDeck.Transport.Dummy import Dummy

    for cls, model in (
        (StreamDeckMini, STREAMDECK_MINI),
        (StreamDeckOriginal, STREAMDECK_MK2),
        (StreamDeckOriginalV2, STREAMDECK_MK2),
        (StreamDeckXL, STREAMDECK_XL),
        (StreamDeckPlus, STREAMDECK_PLUS),
        (StreamDeckNeo, STREAMDECK_NEO),
        (StreamDeckPedal, STREAMDECK_PEDAL),
    ):
        deck = cls(Dummy.Device(0x0FD9, 0x0001))
        assert sd.model_for_deck(deck) == model, cls.__name__
        deck.device.open()  # the transport only: no reader thread
        b = sd.StreamDeckBackend(deck)
        writes: list[Any] = []
        deck.device.write = lambda payload, w=writes: w.append(len(payload)) or True  # type: ignore[method-assign]
        for c in model.image_controls():
            b.set_image(c.id, Image.new("RGBA", c.image, (10, 200, 30, 255)))  # real PILHelper + encoder
        assert bool(writes) == bool(model.image_controls()), cls.__name__
        b.set_brightness(50)
        for cid in model.ids_of_kind("button"):
            b.set_led(cid, (1, 2, 3))
        b._closed = True  # skip close(): it would reset through the Dummy transport
        deck.device.close()


# --- full agent ----------------------------------------------------------------------------------


def _plus_config() -> dict[str, Any]:
    return {
        "config_version": 2,
        "device": {"model": "streamdeck_plus"},
        "brightness": 45,
        "knob_page_feedback": {"duration_sec": 0},
        "global": {"strip_0": {"text": "strip"}},
        "pages": [
            {
                "name": "A",
                "controls": {
                    "key_1_0": {"text": "go", "actions": [_rec("key_1_0")]},
                    "knob_2": {"rotate": {"left": _rec("left"), "right": _rec("right")}, "press": _rec("push")},
                },
            }
        ],
    }


def test_full_agent_with_a_stream_deck_plus(lib: FakeLib, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import open_loupedeck.app as app_mod

    first, deck = _backend("plus", path="hid-first")
    second_deck = FakeDeck("plus", path="hid-second")
    second_deck.open()
    second = sd.StreamDeckBackend(second_deck, watch_interval=0.02)
    monkeypatch.setattr(app_mod, "open_backend", lambda _settings: second)
    h = AgentHarness(tmp_path, _plus_config(), first)  # type: ignore[arg-type]
    h.runtime.no_device = False

    async def go() -> None:
        task = await h.start()
        assert ("brightness", 45) in deck.calls
        # input arrives on the library's reader thread
        threads = [
            threading.Thread(target=fn)
            for fn in (
                lambda: (deck.key(1, True), deck.key(1, False)),
                lambda: deck.dial(2, "TURN", 1),
                lambda: deck.dial(2, "TURN", -2),
                lambda: (deck.dial(2, "PUSH", True), deck.dial(2, "PUSH", False)),
                lambda: deck.touch("SHORT", {"x": 1, "y": 1}),  # nothing bound to touches
            )
        ]
        for th in threads:
            th.start()
            th.join()
            await _settle()
        deck.plugged = False  # unplug: the watchdog signals it, the agent reconnects
        for _ in range(60):
            if h.runtime.deck is second:
                break
            await asyncio.sleep(0.1)
        await _settle()
        await AgentHarness.stop(task)

    asyncio.run(go())
    assert h.recorded == ["key_1_0", "right", "left", "push"]
    assert h.runtime.deck is second and first.unplugged and deck.closed
    assert ("brightness", 45) in second_deck.calls and "deck_reconnect" in h.redraws
    assert second_deck.closed and ("reset",) in second_deck.calls  # closed on shutdown


def test_full_agent_with_a_pedal(tmp_path: Path):
    raw = {
        "config_version": 2,
        "device": {"model": "streamdeck_pedal"},
        "global": {"pedal_1": {"actions": [_rec("centre")]}},
        "pages": [{"name": "A", "controls": {"pedal_0": {"actions": [_rec("left")]}}}],
    }
    dev = FakeBackend(STREAMDECK_PEDAL, path="hid-pedal")
    h = AgentHarness(tmp_path, raw, dev)

    async def go() -> None:
        task = await h.start()
        for cid in ("pedal_0", "pedal_1", "pedal_2"):
            dev.press(cid)
            await _settle()
        await AgentHarness.stop(task)

    asyncio.run(go())
    assert h.recorded == ["left", "centre"]
    assert dev.images == []  # nothing to draw on a pedal


def test_status_reports_the_experimental_notice(tmp_path: Path):
    from fastapi.testclient import TestClient

    from open_loupedeck.config_state import ConfigState
    from open_loupedeck.runtime_refs import AgentRuntimeRefs
    from open_loupedeck.web_app import create_web_app

    path = tmp_path / "config.yaml"
    state = ConfigState(path)
    rt = AgentRuntimeRefs()
    b, _deck = _backend("xl", path="hid-xl")
    b.open()
    rt.deck = b
    client = TestClient(create_web_app(path, state, asyncio.Lock(), runtime=rt))
    try:
        usb = client.get("/api/status").json()["usb"]
        assert usb["connected"] and usb["path"] == "hid-xl" and usb["experimental"] is True
        assert usb["name"] == "Stream Deck XL (experimental)" and "experimental" in usb["notice"]
        assert client.get("/api/device_model").json()["model"]["id"] == "streamdeck_xl"
        assert client.get("/api/config").status_code == 200
        rt.deck = FakeBackend()
        assert "experimental" not in client.get("/api/status").json()["usb"]
    finally:
        b.close()
