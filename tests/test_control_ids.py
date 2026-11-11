"""Control ids: legacy <-> model control ids, and the driver ids the Loupedeck backend reports.

The Live S physical page buttons arrive as bare driver ids ("circle", "1", "2", "3"); they must
map to ``button_0..3`` (the old ``btn_circle``, ``btn_1..3``), whatever the spelling.
"""

from __future__ import annotations

import pytest

from open_loupedeck.control_ids import (
    control_to_legacy_id,
    driver_name_for_button,
    is_legacy_id,
    legacy_to_control_id,
    to_control_id,
)
from open_loupedeck.devices.loupedeck.events import normalize_loupedeck_message
from open_loupedeck.devices.loupedeck.models import LOUPEDECK_LIVE, LOUPEDECK_LIVE_S
from open_loupedeck.devices.model import control_kind_from_id, key_id, parse_indexed_id, parse_key_id
from open_loupedeck.events import ControlEvent

MODELS = (LOUPEDECK_LIVE, LOUPEDECK_LIVE_S)


def test_id_helpers():
    assert key_id(3, 2) == "key_3_2" and parse_key_id("key_3_2") == (3, 2)
    assert parse_key_id("key_3") is None and parse_key_id("touch_3") is None
    assert parse_indexed_id("knob_12") == ("knob", 12) and parse_indexed_id("knobTL") is None
    assert [control_kind_from_id(c) for c in ("key_0_0", "knob_1", "button_0", "strip_1", "slider_0", "pedal_2")] == [
        "key",
        "knob",
        "button",
        "strip",
        "slider",
        "pedal",
    ]
    assert control_kind_from_id("touch_0") is None and control_kind_from_id("btn_circle") is None
    assert is_legacy_id("touch_0") and is_legacy_id("knobTL") and is_legacy_id("btn_0") and is_legacy_id("left")
    assert not is_legacy_id("key_0_0") and not is_legacy_id("knob_0")


def test_touch_ids_follow_each_grid():
    # Live S: 5 columns; Live: 4 columns (row by row, as the old touch indices).
    assert legacy_to_control_id("touch_0", LOUPEDECK_LIVE_S) == "key_0_0"
    assert legacy_to_control_id("touch_5", LOUPEDECK_LIVE_S) == "key_0_1"
    assert legacy_to_control_id("touch_14", LOUPEDECK_LIVE_S) == "key_4_2"
    assert legacy_to_control_id("touch_5", LOUPEDECK_LIVE) == "key_1_1"
    assert legacy_to_control_id("touch_11", LOUPEDECK_LIVE) == "key_3_2"
    assert legacy_to_control_id("touch_12", LOUPEDECK_LIVE) is None  # beyond the 4 x 3 grid
    assert legacy_to_control_id("touch_15", LOUPEDECK_LIVE_S) is None


def test_other_legacy_ids_are_the_same_on_every_model():
    for m in MODELS:
        assert legacy_to_control_id("knobTL", m) == "knob_0"
        assert legacy_to_control_id("knobCL", m) == "knob_1"
        assert legacy_to_control_id("btn_circle", m) == "button_0"
        assert legacy_to_control_id("btn_0", m) == "button_0"  # old alias
        assert legacy_to_control_id("btn_3", m) == "button_3"
    # Only on the Live, but readable with a Live S config (kept, inactive there).
    assert legacy_to_control_id("knobBR", LOUPEDECK_LIVE_S) == "knob_5"
    assert legacy_to_control_id("btn_7", LOUPEDECK_LIVE_S) == "button_7"
    assert legacy_to_control_id("strip_left", LOUPEDECK_LIVE_S) == "strip_0"
    assert legacy_to_control_id("right", LOUPEDECK_LIVE) == "strip_1"
    assert legacy_to_control_id("btn_0", LOUPEDECK_LIVE_S, aliases=False) is None
    assert legacy_to_control_id("nonsense", LOUPEDECK_LIVE_S) is None


@pytest.mark.parametrize("model", MODELS, ids=lambda m: m.id)
def test_round_trip_every_control_with_a_legacy_id(model):
    for c in model.controls:
        lid = control_to_legacy_id(c.id, model)
        assert lid is not None, c.id
        assert legacy_to_control_id(lid, model) == c.id
        assert to_control_id(lid, model) == c.id and to_control_id(c.id, model) == c.id
    for legacy, cid in model.legacy_ids:
        assert legacy_to_control_id(legacy, model) == cid and control_to_legacy_id(cid, model) == legacy


def test_driver_names():
    assert driver_name_for_button("button_0") == "circle"
    assert driver_name_for_button("button_3") == "3"
    assert driver_name_for_button("knob_0") is None


@pytest.mark.parametrize(
    ("msg", "event"),
    [
        ({"action": "push", "state": "down", "id": "1"}, ControlEvent("button_1", "press")),
        ({"action": "push", "state": "down", "id": "3"}, ControlEvent("button_3", "press")),
        ({"action": "push", "state": "down", "id": "circle"}, ControlEvent("button_0", "press")),
        ({"action": "push", "state": "up", "id": "btn_0"}, ControlEvent("button_0", "release")),
        ({"action": "push", "state": "down", "id": "knobCL"}, ControlEvent("knob_1", "press")),
        ({"action": "rotate", "state": "left", "id": "knobTL"}, ControlEvent("knob_0", "rotate", -1)),
        ({"action": "rotate", "state": "right", "id": "knobCL"}, ControlEvent("knob_1", "rotate", 1)),
        ({"action": "touchstart", "screen": "center", "key": 10}, ControlEvent("key_0_2", "press")),
        ({"action": "touchend", "screen": "center", "key": 14}, ControlEvent("key_4_2", "release")),
    ],
)
def test_live_s_driver_messages(msg, event):
    ev = normalize_loupedeck_message(msg, LOUPEDECK_LIVE_S)
    assert ev == event
    assert ev.raw == msg


def test_live_driver_messages_use_its_grid_and_strips():
    assert normalize_loupedeck_message({"action": "touchstart", "screen": "center", "key": 10}, LOUPEDECK_LIVE) == (
        ControlEvent("key_2_2", "press")
    )
    assert normalize_loupedeck_message({"action": "push", "state": "down", "id": "7"}, LOUPEDECK_LIVE) == (
        ControlEvent("button_7", "press")
    )
    ev = normalize_loupedeck_message({"action": "touchstart", "screen": "left", "x": 5, "y": 9}, LOUPEDECK_LIVE)
    assert ev == ControlEvent("strip_0", "touch", (5, 9))
    # The Live S has no strips: its side screen areas are ignored (as before).
    assert normalize_loupedeck_message({"action": "touchstart", "screen": "left"}, LOUPEDECK_LIVE_S) is None
    assert normalize_loupedeck_message({"action": "push", "state": "maybe", "id": "1"}, LOUPEDECK_LIVE) is None
    assert normalize_loupedeck_message({"action": "dance"}, LOUPEDECK_LIVE) is None


def test_rotation_direction():
    assert ControlEvent("knob_0", "rotate", 1).direction == "right"
    assert ControlEvent("knob_0", "rotate", -2).direction == "left"
    assert ControlEvent("key_0_0", "press").direction is None
