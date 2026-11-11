"""Device abstraction: descriptors reproduce the hard-coded Loupedeck facts, registry, backend parity."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image

from open_loupedeck.button_render import key_size_for_control
from open_loupedeck.config import DeviceConfig, Settings
from open_loupedeck.devices.base import DeviceBackend, device_model_of
from open_loupedeck.devices.loupedeck import patches
from open_loupedeck.devices.loupedeck.backend import LoupedeckBackend, led_protocol_name, model_for_driver
from open_loupedeck.devices.loupedeck.events import normalize_loupedeck_message
from open_loupedeck.devices.loupedeck.live_s import LIVE_S_MAX_KEY, LoupedeckLiveS
from open_loupedeck.devices.loupedeck.models import LOUPEDECK_LIVE, LOUPEDECK_LIVE_S
from open_loupedeck.devices.model import CONTROL_KINDS, ControlSpec, DeviceModel, KeyGrid
from open_loupedeck.devices.registry import DeviceRegistry, known_models, model_by_name
from open_loupedeck.events import NormalizedEvent
from open_loupedeck.knob_pages import KNOB_ENCODER_IDS
from open_loupedeck.simulate_input import build_synthetic_loupedeck_message
from tests.fake_backend import FakeBackend, FakeFactory

# --- descriptors reproduce today's hard-coded facts ---------------------------------------------

# deck_skin.drawable_control_ids() before the device layer.
OLD_DRAWABLE_LIVE = (
    [f"touch_{i}" for i in range(12)] + [f"btn_{i}" for i in range(1, 8)] + ["strip_left", "strip_right"]
)
OLD_DRAWABLE_LIVE_S = [f"touch_{i}" for i in range(15)]
# knob_pages.feedback_touch_key_for_knob_page_name() before the device layer.
OLD_FEEDBACK_LIVE = {
    "knobTL": "touch_0",
    "knobCL": "touch_4",
    "knobBL": "touch_8",
    "knobTR": "touch_3",
    "knobCR": "touch_7",
    "knobBR": "touch_11",
}
OLD_FEEDBACK_LIVE_S = {"knobTL": "touch_0", "knobCL": "touch_5"}


def test_touch_key_counts_and_ids():
    assert LOUPEDECK_LIVE.grid.count == 12 and (LOUPEDECK_LIVE.grid.rows, LOUPEDECK_LIVE.grid.cols) == (3, 4)
    assert LOUPEDECK_LIVE_S.grid.count == 15 and (LOUPEDECK_LIVE_S.grid.rows, LOUPEDECK_LIVE_S.grid.cols) == (3, 5)
    assert LOUPEDECK_LIVE_S.grid.count - 1 == LIVE_S_MAX_KEY
    assert LOUPEDECK_LIVE_S.touch_ids() == [f"touch_{i}" for i in range(15)]


def test_drawable_controls_and_key_sizes_match_the_old_code():
    assert LOUPEDECK_LIVE.drawable_control_ids() == OLD_DRAWABLE_LIVE
    assert LOUPEDECK_LIVE_S.drawable_control_ids() == OLD_DRAWABLE_LIVE_S
    for m in (LOUPEDECK_LIVE, LOUPEDECK_LIVE_S):
        for cid in m.drawable_control_ids():
            assert m.key_size_for(cid) == key_size_for_control(cid), cid


def test_knob_neighbour_keys_match_the_old_mapping():
    assert dict(LOUPEDECK_LIVE.knob_feedback_keys) == OLD_FEEDBACK_LIVE
    assert dict(LOUPEDECK_LIVE_S.knob_feedback_keys) == OLD_FEEDBACK_LIVE_S
    for m in (LOUPEDECK_LIVE, LOUPEDECK_LIVE_S):
        assert set(m.knob_ids()) <= KNOB_ENCODER_IDS
        assert set(dict(m.knob_feedback_keys)) == set(m.knob_ids())
        for key in dict(m.knob_feedback_keys).values():
            assert m.grid.index_of(key) is not None


def test_controls_capabilities_and_ids_are_stable():
    assert LOUPEDECK_LIVE.knob_ids() == ["knobTL", "knobCL", "knobBL", "knobTR", "knobCR", "knobBR"]
    assert LOUPEDECK_LIVE_S.knob_ids() == ["knobTL", "knobCL"]
    assert LOUPEDECK_LIVE_S.led_button_ids() == ["btn_circle", "btn_1", "btn_2", "btn_3"]
    assert LOUPEDECK_LIVE.led_button_ids() == []  # the Live LEDs are not driven today
    assert LOUPEDECK_LIVE_S.capabilities.button_led and not LOUPEDECK_LIVE.capabilities.button_led
    assert LOUPEDECK_LIVE_S.page_buttons == ("btn_circle", "btn_1", "btn_2", "btn_3")
    assert LOUPEDECK_LIVE.page_buttons == ()
    assert LOUPEDECK_LIVE_S.default_button_rgb == (32, 32, 40)
    for m in (LOUPEDECK_LIVE, LOUPEDECK_LIVE_S):
        assert m.capabilities.brightness and m.capabilities.touch and m.capabilities.knobs
        assert all(c.kind in CONTROL_KINDS for c in m.controls)
        assert len({c.id for c in m.controls}) == len(m.controls)
    assert {c.id for c in LOUPEDECK_LIVE.controls} >= {"btn_circle", "strip_left", "strip_right"}
    assert LOUPEDECK_LIVE.config_name == "live" and LOUPEDECK_LIVE_S.config_name == "live_s"


def test_descriptor_serialises():
    d = LOUPEDECK_LIVE_S.to_dict()
    assert d["id"] == "loupedeck_live_s" and d["family"] == "loupedeck"
    assert d["grid"]["count"] == 15 and d["grid"]["key_size"] == [90, 90]
    assert d["grid"]["id_scheme"] == "touch_{index}"
    assert d["knob_feedback_keys"] == OLD_FEEDBACK_LIVE_S
    assert d["capabilities"]["button_led"] is True
    import json

    json.dumps(LOUPEDECK_LIVE.to_dict())


def test_grid_index_of():
    g = KeyGrid(rows=2, cols=3, key_size=(72, 72))
    assert g.index_of("touch_5") == 5
    assert g.index_of("touch_6") is None
    assert g.index_of("touch_x") is None
    assert g.index_of("btn_1") is None


def test_model_lookup_by_config_name_and_id():
    assert model_by_name("live") is LOUPEDECK_LIVE
    assert model_by_name("LIVE_S") is LOUPEDECK_LIVE_S
    assert model_by_name("loupedeck_live_s") is LOUPEDECK_LIVE_S
    assert model_by_name("auto") is None and model_by_name("") is None and model_by_name(None) is None
    assert {m.id for m in known_models()} >= {"loupedeck_live", "loupedeck_live_s"}


# --- registry with injected backends ------------------------------------------------------------

OTHER = DeviceModel(
    id="other_pad",
    family="other",
    name="Other pad",
    grid=KeyGrid(rows=2, cols=2, key_size=(72, 72)),
    controls=(ControlSpec("btn_a", "button", "A"),),
    config_names=("other",),
)


def _settings(model: str = "auto", path: str = "") -> Settings:
    return Settings(device=DeviceConfig(path=path, model=model))


def test_registry_discovery_collects_every_backend_and_survives_errors():
    a = FakeFactory("alpha", (LOUPEDECK_LIVE_S,), found=["/dev/a0", "/dev/a1"])
    b = FakeFactory("other", (OTHER,), found=["hid:1"])
    broken = FakeFactory("broken", (OTHER,))
    broken.discover = lambda: (_ for _ in ()).throw(OSError("boom"))  # type: ignore[method-assign]
    reg = DeviceRegistry([a, broken, b])
    found = reg.discover_devices()
    assert [(d.backend, d.path, d.model.id) for d in found] == [
        ("alpha", "/dev/a0", "loupedeck_live_s"),
        ("alpha", "/dev/a1", "loupedeck_live_s"),
        ("other", "hid:1", "other_pad"),
    ]
    assert found[0].to_dict() == {"backend": "alpha", "path": "/dev/a0", "model": "loupedeck_live_s"}


def test_registry_open_routes_by_model_and_auto_tries_in_order():
    a = FakeFactory("loupedeck", (LOUPEDECK_LIVE, LOUPEDECK_LIVE_S))
    b = FakeFactory("other", (OTHER,))
    reg = DeviceRegistry([a, b])

    dev = reg.open_backend(_settings("other"))
    assert dev.model is OTHER and len(b.opened) == 1 and not a.opened

    a.fail = RuntimeError("no loupedeck")
    dev = reg.open_backend(_settings("auto"))
    assert dev.model is OTHER and len(a.opened) == 1

    b.fail = RuntimeError("no other")
    with pytest.raises(RuntimeError, match="no other"):
        reg.open_backend(_settings("auto"))

    # a configured model only tries its own backend, and its error comes back unchanged
    with pytest.raises(RuntimeError, match="no loupedeck"):
        reg.open_backend(_settings("live_s"))


def test_registry_register_replaces_by_family_and_normalizes():
    reg = DeviceRegistry([FakeFactory("alpha", (LOUPEDECK_LIVE,))])
    reg.register(FakeFactory("other", (OTHER,)))
    reg.register(FakeFactory("other", (OTHER,)))
    assert [f.family for f in reg.factories()] == ["alpha", "other"]
    assert reg.model_by_name("other") is OTHER
    assert reg.normalize_message({"fake": "other", "key": 3}) == NormalizedEvent(
        "touch", 3, "down", {"fake": "other", "key": 3}
    )
    assert reg.normalize_message({"nothing": 1}) is None


def test_default_registry_normalizes_loupedeck_messages():
    from open_loupedeck.devices.registry import normalize_native_message

    msg = {"action": "rotate", "state": "left", "id": "knobTL"}
    assert normalize_native_message(msg) == normalize_loupedeck_message(msg)


# --- the Loupedeck backend over a fake driver ----------------------------------------------------


class FakeDriver:
    """Duck-typed python-loupedeck-live driver (no serial port)."""

    def __init__(self) -> None:
        self.path = "/dev/ttyACM9"
        self.connection = SimpleNamespace(is_open=True)
        self.calls: list[tuple[Any, ...]] = []
        self.callback: Any = None
        self.locked = 0

    def __enter__(self) -> None:
        self.locked += 1

    def __exit__(self, *exc: Any) -> None:
        self.locked -= 1

    def start(self) -> None:
        self.calls.append(("start",))

    def stop(self) -> None:
        self.calls.append(("stop",))

    def set_key_image(self, idx: str, _img: Any) -> None:
        self.calls.append(("key", idx))

    def set_left_image(self, _img: Any) -> None:
        self.calls.append(("left",))

    def set_right_image(self, _img: Any) -> None:
        self.calls.append(("right",))

    def set_brightness(self, pct: int) -> None:
        self.calls.append(("brightness", pct))

    def set_button_color(self, name: str, rgb: Any) -> None:
        self.calls.append(("color", name, rgb))

    def set_callback(self, cb: Any) -> None:
        self.callback = cb


IMG = Image.new("RGBA", (90, 90))


def test_backends_satisfy_the_protocol():
    assert isinstance(LoupedeckBackend(FakeDriver(), LOUPEDECK_LIVE_S), DeviceBackend)
    assert isinstance(FakeBackend(), DeviceBackend)
    assert device_model_of(FakeBackend()) is LOUPEDECK_LIVE_S
    assert device_model_of(None) is None and device_model_of(object()) is None


def test_model_for_driver_class():
    assert model_for_driver(LoupedeckLiveS.__new__(LoupedeckLiveS)) is LOUPEDECK_LIVE_S
    assert model_for_driver(FakeDriver()) is LOUPEDECK_LIVE


def test_set_key_image_maps_control_ids_like_the_old_deck_skin():
    drv = FakeDriver()
    live_s = LoupedeckBackend(drv, LOUPEDECK_LIVE_S)
    for cid in ("touch_0", "touch_14", "touch_15", "btn_circle", "btn_2", "strip_left", "strip_right", "knobTL"):
        live_s.set_key_image(cid, IMG)
    assert drv.calls == [("key", "0"), ("key", "14"), ("key", "2")]

    drv = FakeDriver()
    live = LoupedeckBackend(drv, LOUPEDECK_LIVE)
    for cid in ("touch_11", "touch_12", "btn_7", "btn_circle", "strip_left", "left", "strip_right"):
        live.set_key_image(cid, IMG)
    assert drv.calls == [("key", "11"), ("key", "7"), ("left",), ("left",), ("right",)]

    with pytest.raises(ValueError):
        live.set_key_image("touch_x", IMG)  # the old code raised too (caught by the skin loop)


def test_led_brightness_lifecycle_and_lock():
    drv = FakeDriver()
    b = LoupedeckBackend(drv, LOUPEDECK_LIVE_S)
    assert [led_protocol_name(c) for c in LOUPEDECK_LIVE_S.led_button_ids()] == ["circle", "1", "2", "3"]
    b.set_button_color("btn_circle", (1, 2, 3))
    b.set_button_color("btn_3", (4, 5, 6))
    b.set_button_color("knobTL", (7, 8, 9))  # no LED: ignored
    b.set_brightness(40)
    b.open()
    with b:
        assert drv.locked == 1
    assert drv.locked == 0
    b.close()
    assert drv.calls == [
        ("color", "circle", (1, 2, 3)),
        ("color", "3", (4, 5, 6)),
        ("brightness", 40),
        ("start",),
        ("stop",),
    ]
    assert b.is_open and b.path == "/dev/ttyACM9"
    drv.connection = None
    assert not b.is_open


SAMPLE_MESSAGES = [
    {"action": "push", "state": "down", "id": "circle"},
    {"action": "push", "state": "up", "id": "3"},
    {"action": "push", "state": "down", "id": "knobCL"},
    {"action": "push", "state": "down", "id": "btn_0"},
    {"action": "rotate", "state": "right", "id": "knobTL"},
    {"action": "rotate", "state": "left", "id": "knobCR"},
    {"action": "touchstart", "screen": "center", "key": 7, "x": 1, "y": 2, "id": 0},
    {"action": "touchend", "screen": "center", "key": 7, "x": 1, "y": 2, "id": 0},
    {"action": "touchstart", "screen": "left", "key": None, "id": 1},
    {"action": "touchmove", "screen": "center", "key": 3, "id": 2},
    {"action": "push", "state": "weird", "id": "1"},
]


def test_event_callback_delivers_the_same_normalized_events():
    drv = FakeDriver()
    b = LoupedeckBackend(drv, LOUPEDECK_LIVE_S)
    got: list[NormalizedEvent] = []
    b.set_event_callback(got.append)
    for msg in SAMPLE_MESSAGES:
        drv.callback(drv, msg)
    expected = [ev for ev in map(normalize_loupedeck_message, SAMPLE_MESSAGES) if ev is not None]
    assert got == expected
    assert [(e.kind, e.id, e.edge) for e in got] == [
        ("button", "circle", "down"),
        ("button", "3", "up"),
        ("button", "knobCL", "down"),
        ("button", "btn_circle", "down"),
        ("knob", "knobTL", "right"),
        ("knob", "knobCR", "left"),
        ("touch", 7, "down"),
        ("touch", 7, "up"),
    ]
    drv.callback(drv, {"action": "touchstart", "screen": "center", "key": "bad"})  # logged, not raised
    b.set_event_callback(None)
    assert drv.callback is None


def test_unplug_signal_from_the_serial_reader():
    drv = FakeDriver()
    b = LoupedeckBackend(drv, LOUPEDECK_LIVE_S)
    fired: list[str] = []
    patches._notify_serial_fatal(drv)  # before anyone listens: remembered
    assert b.unplugged
    b.set_unplugged_callback(lambda: fired.append("late"))
    assert fired == ["late"]
    patches._notify_serial_fatal(drv)
    assert fired == ["late", "late"]


def test_simulated_messages_normalize_like_hardware():
    from open_loupedeck.simulate_input import build_synthetic_event

    for cid, direction in [
        ("touch_3", None),
        ("btn_circle", None),
        ("circle", None),
        ("btn_0", None),
        ("btn_2", None),
        ("knobTL", None),
        ("knobCL", "left"),
        ("knobBR", "right"),
    ]:
        msg = build_synthetic_loupedeck_message(cid, direction=direction)
        ev = build_synthetic_event(cid, direction=direction)
        assert ev is not None and msg is not None
        want = normalize_loupedeck_message(msg)
        assert (ev.kind, ev.id, ev.edge) == (want.kind, want.id, want.edge), cid
    for cid in ("", "strip_left", "right", "nope"):
        assert build_synthetic_event(cid) is None
