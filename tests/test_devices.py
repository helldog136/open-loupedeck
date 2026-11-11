"""Device abstraction: model descriptors (controls, positions, capabilities), registry, backend."""

from __future__ import annotations

import json
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
from open_loupedeck.devices.model import CONTROL_KINDS, Control, DeviceModel, Position, key_id
from open_loupedeck.devices.registry import DeviceRegistry, config_model, known_models, model_by_name, resolve_model
from open_loupedeck.events import ControlEvent
from open_loupedeck.knob_pages import feedback_key_for_knob
from open_loupedeck.simulate_input import build_synthetic_loupedeck_message
from tests.fake_backend import FakeBackend, FakeFactory

# --- descriptors keep today's Loupedeck facts -----------------------------------------------------

# knob_pages.feedback_touch_key_for_knob_page_name() before the feature model (legacy ids).
OLD_FEEDBACK_LIVE = {
    "knobTL": "touch_0",
    "knobCL": "touch_4",
    "knobBL": "touch_8",
    "knobTR": "touch_3",
    "knobCR": "touch_7",
    "knobBR": "touch_11",
}
OLD_FEEDBACK_LIVE_S = {"knobTL": "touch_0", "knobCL": "touch_5"}


@pytest.mark.parametrize("model", [LOUPEDECK_LIVE, LOUPEDECK_LIVE_S], ids=lambda m: m.id)
def test_descriptor_is_consistent(model):
    assert model.problems() == []
    assert all(c.kind in CONTROL_KINDS for c in model.controls)
    assert model.brightness is True


def test_key_grids():
    assert LOUPEDECK_LIVE.grid_of_keys() == (4, 3) and len(LOUPEDECK_LIVE.keys()) == 12
    assert LOUPEDECK_LIVE_S.grid_of_keys() == (5, 3) and len(LOUPEDECK_LIVE_S.keys()) == 15
    assert len(LOUPEDECK_LIVE_S.keys()) - 1 == LIVE_S_MAX_KEY
    keys_s = LOUPEDECK_LIVE_S.keys()  # row by row, like the old touch indices
    assert [c.id for c in keys_s] == list(LOUPEDECK_LIVE_S.legacy_map().values())[:15]
    assert [c.id for c in LOUPEDECK_LIVE_S.controls_of_kind("key")][:6] == [
        "key_0_0",
        "key_1_0",
        "key_2_0",
        "key_3_0",
        "key_4_0",
        "key_0_1",
    ]
    for m in (LOUPEDECK_LIVE, LOUPEDECK_LIVE_S):
        for k in m.controls_of_kind("key"):
            assert k.image == (90, 90) and k.inputs == ("press",) and k.led is None


def test_live_s_layout():
    m = LOUPEDECK_LIVE_S
    assert m.layout == (7, 3)
    assert m.ids_of_kind("knob") == ["knob_0", "knob_1"]
    assert m.ids_of_kind("button") == ["button_0", "button_1", "button_2", "button_3"]
    assert m.ids_of_kind("strip") == []
    # Two knobs on the left, the circle button under them, three round buttons on the right.
    k0, k1, b0 = m.control("knob_0"), m.control("knob_1"), m.control("button_0")
    assert k0.position.x < 1 and k1.position.x < 1 and b0.position.x < 1
    assert k0.position.y < k1.position.y < b0.position.y
    keys_x = [k.position.x for k in m.controls_of_kind("key")]
    for i in (1, 2, 3):
        b = m.control(f"button_{i}")
        assert b.position.x > max(keys_x) and b.led == "rgb" and b.default_led == (32, 32, 40)
        assert b.image is None and b.inputs == ("press",)
    assert [m.control(f"button_{i}").position.y for i in (1, 2, 3)] == sorted(
        m.control(f"button_{i}").position.y for i in (1, 2, 3)
    )
    assert [c.id for c in m.image_controls()] == [c.id for c in m.controls_of_kind("key")]  # no other display
    assert [c.id for c in m.led_controls()] == ["button_0", "button_1", "button_2", "button_3"]


def test_live_layout():
    m = LOUPEDECK_LIVE
    assert m.ids_of_kind("knob") == [f"knob_{i}" for i in range(6)]
    assert m.ids_of_kind("button") == [f"button_{i}" for i in range(8)]
    assert m.ids_of_kind("strip") == ["strip_0", "strip_1"]
    assert m.control("strip_0").image == (60, 270) and m.control("strip_0").inputs == ("touch",)
    assert m.image_size("strip_1") == key_size_for_control("strip_1") == (60, 270)
    assert m.image_size("key_3_2") == key_size_for_control("key_3_2") == (90, 90)
    # Buttons: a row under the screen, circle first; no LED output declared (not driven).
    assert [m.control(f"button_{i}").position.y for i in range(8)] == [3.15] * 8
    assert m.led_controls() == []
    assert [c.id for c in m.image_controls()][-2:] == ["strip_0", "strip_1"]


def test_knob_feedback_keys_match_the_old_mapping():
    for model, old in ((LOUPEDECK_LIVE, OLD_FEEDBACK_LIVE), (LOUPEDECK_LIVE_S, OLD_FEEDBACK_LIVE_S)):
        legacy = model.legacy_map()
        for knob, touch in old.items():
            assert model.feedback_key_for(legacy[knob]) == legacy[touch]
            assert feedback_key_for_knob(knob, model) == legacy[touch]  # legacy knob ids still work
    assert feedback_key_for_knob("knobCL", "auto") == "key_0_1"  # auto -> Live S
    assert feedback_key_for_knob("knob_4", "live") == "key_3_1"
    assert feedback_key_for_knob("knob_5", "live_s") is None  # no such knob on the Live S


def test_feedback_defaults_to_the_nearest_display():
    pad = DeviceModel(
        id="pad",
        family="test",
        name="Pad",
        layout=(3, 1),
        controls=(
            Control(key_id(0, 0), "key", "A", Position(0, 0), ("press",), image=(72, 72)),
            Control(key_id(1, 0), "key", "B", Position(1, 0), ("press",), image=(72, 72)),
            Control("knob_0", "knob", "K", Position(2, 0), ("rotate",)),
            Control("button_0", "button", "Btn", Position(2.5, 0, 0.5, 1), ("press",)),
        ),
    )
    assert pad.problems() == []
    assert pad.feedback_key_for("knob_0") == "key_1_0"
    assert pad.nearest_display("key_1_0").id == "key_0_0"  # never itself
    assert pad.feedback_key_for("nope") is None
    lonely = DeviceModel("l", "test", "L", (1, 1), (Control("knob_0", "knob", "K", Position(0, 0), ("rotate",)),))
    assert lonely.feedback_key_for("knob_0") is None  # no display: the UI shows a toast instead


def test_problems_catch_bad_descriptors():
    bad = DeviceModel(
        id="bad",
        family="test",
        name="Bad",
        layout=(2, 1),
        controls=(
            Control("knob_1", "knob", "K", Position(0, 0)),
            Control("knob_0", "knob", "K", Position(1, 0), feedback_key="key_0_0"),
            Control("button_0", "key", "B", Position(5, 0)),
        ),
        legacy_ids=(("btn_x", "button_9"),),
    )
    text = " | ".join(bad.problems())
    assert "not numbered by position" in text and "unknown feedback_key" in text
    assert "does not match kind" in text and "outside the layout" in text and "unknown control" in text


def test_descriptor_serialises():
    d = LOUPEDECK_LIVE_S.to_dict()
    assert d["id"] == "loupedeck_live_s" and d["family"] == "loupedeck" and d["config_name"] == "live_s"
    assert d["layout"] == {"width": 7, "height": 3} and d["brightness"] is True
    assert d["grid"] == {"cols": 5, "rows": 3, "count": 15}
    # Knobs: explicit feedback_key; buttons: the nearest display (button press feedback).
    assert d["feedback_keys"] == {
        "knob_0": "key_0_0",
        "knob_1": "key_0_1",
        "button_0": "key_0_2",
        "button_1": "key_4_0",
        "button_2": "key_4_1",
        "button_3": "key_4_2",
    }
    c0 = next(c for c in d["controls"] if c["id"] == "key_0_0")
    assert c0 == {
        "id": "key_0_0",
        "kind": "key",
        "name": "Key 1",
        "position": {"x": 1, "y": 0, "w": 1.0, "h": 1.0},
        "inputs": ["press"],
        "outputs": {"image": {"width": 90, "height": 90}},
    }
    assert d["legacy_ids"]["touch_14"] == "key_4_2" and d["legacy_ids"]["btn_circle"] == "button_0"
    json.dumps(LOUPEDECK_LIVE.to_dict())
    assert "capabilities" not in d and "page_buttons" not in d and "default_button_rgb" not in d


def test_model_lookup_by_config_name_and_id():
    assert model_by_name("live") is LOUPEDECK_LIVE
    assert model_by_name("LIVE_S") is LOUPEDECK_LIVE_S
    assert model_by_name("loupedeck_live_s") is LOUPEDECK_LIVE_S
    assert model_by_name("auto") is None and model_by_name("") is None and model_by_name(None) is None
    assert {m.id for m in known_models()} >= {"loupedeck_live", "loupedeck_live_s"}
    assert config_model("auto") is LOUPEDECK_LIVE_S and config_model("live") is LOUPEDECK_LIVE
    assert resolve_model("auto", FakeBackend(LOUPEDECK_LIVE)) is LOUPEDECK_LIVE  # the device wins
    assert resolve_model("live", None) is LOUPEDECK_LIVE and resolve_model(None, None) is LOUPEDECK_LIVE_S


# --- registry with injected backends ------------------------------------------------------------

OTHER = DeviceModel(
    id="other_pad",
    family="other",
    name="Other pad",
    layout=(3, 2),
    controls=(
        *(
            Control(key_id(c, r), "key", "K", Position(c, r), ("press",), image=(72, 72))
            for r in range(2)
            for c in range(2)
        ),
        Control("button_0", "button", "A", Position(2, 0), ("press",)),
    ),
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
    assert reg.normalize_message({"fake": "other", "key": 3}) == ControlEvent("key_3_0", "press")
    assert reg.normalize_message({"nothing": 1}) is None


def test_default_registry_normalizes_loupedeck_messages():
    from open_loupedeck.devices.registry import normalize_native_message

    msg = {"action": "rotate", "state": "left", "id": "knobTL"}
    assert normalize_native_message(msg) == normalize_loupedeck_message(msg) == ControlEvent("knob_0", "rotate", -1)
    touch = {"action": "touchstart", "screen": "center", "key": 5}
    assert normalize_native_message(touch, LOUPEDECK_LIVE).control_id == "key_1_1"
    assert normalize_native_message(touch).control_id == "key_0_1"  # default model: Live S


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


def test_set_image_maps_control_ids_to_the_driver():
    drv = FakeDriver()
    live_s = LoupedeckBackend(drv, LOUPEDECK_LIVE_S)
    for cid in ("key_0_0", "key_4_2", "key_0_1", "key_5_0", "button_0", "strip_0", "knob_0", "touch_0"):
        live_s.set_image(cid, IMG)
    assert drv.calls == [("key", "0"), ("key", "14"), ("key", "5")]  # driver indices, row by row

    drv = FakeDriver()
    live = LoupedeckBackend(drv, LOUPEDECK_LIVE)
    for cid in ("key_3_2", "key_0_1", "key_4_0", "button_7", "button_0", "strip_0", "strip_1"):
        live.set_image(cid, IMG)
    # The round buttons take no image any more (the old code painted btn_1..7 over touch keys 1..7).
    assert drv.calls == [("key", "11"), ("key", "4"), ("left",), ("right",)]


def test_led_brightness_lifecycle_and_lock():
    drv = FakeDriver()
    b = LoupedeckBackend(drv, LOUPEDECK_LIVE_S)
    assert [led_protocol_name(c.id) for c in LOUPEDECK_LIVE_S.led_controls()] == ["circle", "1", "2", "3"]
    b.set_led("button_0", (1, 2, 3))
    b.set_led("button_3", (4, 5, 6))
    b.set_led("knob_0", (7, 8, 9))  # no LED: ignored
    LoupedeckBackend(drv, LOUPEDECK_LIVE).set_led("button_1", (9, 9, 9))  # not declared on the Live
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


def test_event_callback_delivers_control_events():
    drv = FakeDriver()
    b = LoupedeckBackend(drv, LOUPEDECK_LIVE_S)
    got: list[ControlEvent] = []
    b.set_event_callback(got.append)
    for msg in SAMPLE_MESSAGES:
        drv.callback(drv, msg)
    expected = [ev for ev in (normalize_loupedeck_message(m, LOUPEDECK_LIVE_S) for m in SAMPLE_MESSAGES) if ev]
    assert got == expected
    assert [(e.control_id, e.type, e.value) for e in got] == [
        ("button_0", "press", None),
        ("button_3", "release", None),
        ("knob_1", "press", None),
        ("button_0", "press", None),
        ("knob_0", "rotate", 1),
        ("knob_4", "rotate", -1),  # a Live knob: inactive on a Live S, still a valid event
        ("key_2_1", "press", None),
        ("key_2_1", "release", None),
    ]
    drv.callback(drv, {"action": "touchstart", "screen": "center", "key": "bad"})  # logged, not raised
    b.set_event_callback(None)
    assert drv.callback is None


def test_live_backend_events_use_its_own_grid():
    drv = FakeDriver()
    b = LoupedeckBackend(drv, LOUPEDECK_LIVE)
    got: list[ControlEvent] = []
    b.set_event_callback(got.append)
    drv.callback(drv, {"action": "touchstart", "screen": "center", "key": 7})
    drv.callback(drv, {"action": "touchstart", "screen": "right", "x": 3, "y": 4})
    assert got == [ControlEvent("key_3_1", "press"), ControlEvent("strip_1", "touch", (3, 4))]


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

    for model in (LOUPEDECK_LIVE_S, LOUPEDECK_LIVE):
        for cid, direction in [
            ("touch_3", None),
            ("key_1_2", None),
            ("btn_circle", None),
            ("circle", None),
            ("btn_0", None),
            ("btn_2", None),
            ("button_2", None),
            ("knobTL", None),
            ("knob_1", None),
            ("knobCL", "left"),
            ("knobBR", "right"),
            ("knob_0", "right"),
        ]:
            msg = build_synthetic_loupedeck_message(cid, direction=direction, model=model)
            ev = build_synthetic_event(cid, direction=direction, model=model)
            assert ev is not None and msg is not None, cid
            assert ev == normalize_loupedeck_message(msg, model), cid
        for cid in ("", "strip_left", "strip_0", "right", "nope"):
            assert build_synthetic_event(cid, model=model) is None
    assert build_synthetic_event("touch_5").control_id == "key_0_1"  # default model: Live S
    assert build_synthetic_event("touch_5", model=LOUPEDECK_LIVE).control_id == "key_1_1"
