from __future__ import annotations

import pytest

from open_loupedeck.events import NormalizedEvent
from open_loupedeck.match import actions_for_event, event_matches_rule


def _touch(idx: int, edge: str = "down") -> NormalizedEvent:
    return NormalizedEvent(kind="touch", id=idx, edge=edge, raw={})


def _button(bid: str, edge: str = "down") -> NormalizedEvent:
    return NormalizedEvent(kind="button", id=bid, edge=edge, raw={})


def test_touch_rule_matches_key_and_edge():
    rule = {"type": "touch", "key": 3, "edge": "down"}
    assert event_matches_rule(rule, _touch(3)) is True
    assert event_matches_rule(rule, _touch(3, edge="up")) is False
    assert event_matches_rule(rule, _touch(4)) is False


def test_rule_without_edge_matches_any_edge():
    rule = {"type": "button", "id": "btn_1"}
    assert event_matches_rule(rule, _button("btn_1", edge="down")) is True
    assert event_matches_rule(rule, _button("btn_1", edge="up")) is True


def test_wrong_kind_never_matches():
    rule = {"type": "button", "id": "btn_1"}
    assert event_matches_rule(rule, _touch(1)) is False


def test_actions_for_event_first_match_wins():
    bindings = [
        {"match": {"type": "button", "id": "btn_1"}, "action": {"type": "a"}},
        {"match": {"type": "button", "id": "btn_1"}, "action": {"type": "b"}},
    ]
    assert actions_for_event(bindings, _button("btn_1")) == [{"type": "a"}]


def test_actions_for_event_no_match_returns_empty_list():
    assert actions_for_event([], _button("btn_1")) == []


def test_actions_for_event_rejects_non_mapping_action():
    bindings = [{"match": {"type": "button", "id": "btn_1"}, "action": "not-a-mapping"}]
    with pytest.raises(ValueError, match="mapping"):
        actions_for_event(bindings, _button("btn_1"))
