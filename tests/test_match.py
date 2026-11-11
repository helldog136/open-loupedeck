from __future__ import annotations

import pytest

from open_loupedeck.devices.loupedeck.models import LOUPEDECK_LIVE, LOUPEDECK_LIVE_S
from open_loupedeck.events import ControlEvent
from open_loupedeck.match import actions_for_event, event_matches_rule, legacy_signature

S = LOUPEDECK_LIVE_S


def _press(cid: str) -> ControlEvent:
    return ControlEvent(cid, "press")


def test_legacy_touch_rule_matches_key_index_on_the_model_grid():
    rule = {"type": "touch", "key": 6, "edge": "down"}
    assert event_matches_rule(rule, _press("key_1_1"), S) is True  # 5 columns
    assert event_matches_rule(rule, ControlEvent("key_1_1", "release"), S) is False
    assert event_matches_rule(rule, _press("key_2_1"), S) is False
    assert event_matches_rule(rule, _press("key_2_1"), LOUPEDECK_LIVE) is True  # 4 columns


def test_legacy_button_rule_uses_driver_names_and_btn_ids():
    assert event_matches_rule({"type": "button", "id": "1"}, _press("button_1"), S) is True
    assert event_matches_rule({"type": "button", "id": "btn_1"}, _press("button_1"), S) is True
    assert event_matches_rule({"type": "button", "id": "circle"}, _press("button_0"), S) is True
    assert event_matches_rule({"type": "button", "id": "btn_1"}, ControlEvent("button_1", "release"), S) is True
    assert event_matches_rule({"type": "button", "id": "btn_1"}, _press("key_0_1"), S) is False


def test_legacy_knob_rule():
    rule = {"type": "knob", "id": "knobTL", "edge": "left"}
    assert event_matches_rule(rule, ControlEvent("knob_0", "rotate", -1), S) is True
    assert event_matches_rule(rule, ControlEvent("knob_0", "rotate", 1), S) is False
    assert legacy_signature(ControlEvent("knob_1", "press"), S) == ("button", "knobCL", "down")


def test_control_rule():
    assert event_matches_rule({"control": "key_0_0"}, _press("key_0_0"), S) is True
    assert event_matches_rule({"control": "touch_0"}, _press("key_0_0"), S) is True  # legacy id accepted
    assert event_matches_rule({"control": "key_0_0", "type": "release"}, _press("key_0_0"), S) is False
    rule = {"control": "knob_1", "type": "rotate", "direction": "right"}
    assert event_matches_rule(rule, ControlEvent("knob_1", "rotate", 1), S) is True
    assert event_matches_rule(rule, ControlEvent("knob_1", "rotate", -1), S) is False


def test_actions_for_event_first_match_wins():
    bindings = [
        {"match": {"type": "button", "id": "btn_1"}, "action": {"type": "a"}},
        {"match": {"type": "button", "id": "btn_1"}, "action": {"type": "b"}},
    ]
    assert actions_for_event(bindings, _press("button_1"), S) == [{"type": "a"}]


def test_actions_for_event_no_match_returns_empty_list():
    assert actions_for_event([], _press("button_1"), S) == []


def test_actions_for_event_rejects_non_mapping_action():
    bindings = [{"match": {"type": "button", "id": "btn_1"}, "action": "not-a-mapping"}]
    with pytest.raises(ValueError, match="mapping"):
        actions_for_event(bindings, _press("button_1"), S)
