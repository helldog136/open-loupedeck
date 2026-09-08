"""Regression coverage for hardware-id -> config-key normalization.

This is the exact contract that was broken for Loupedeck Live S physical page
buttons: the device reports bare button ids ("1", "2", "3", "circle"), and
anything comparing against them (YAML lookup, or app.py's automatic page-switch
shortcut) must go through this normalization rather than compare raw ids.
"""

from __future__ import annotations

from open_loupedeck.control_ids import control_ids_for_lookup, is_page_scoped_control
from open_loupedeck.events import NormalizedEvent


def _button(raw_id: str, edge: str = "down") -> NormalizedEvent:
    return NormalizedEvent(kind="button", id=raw_id, edge=edge, raw={})


def _touch(idx: int, edge: str = "down") -> NormalizedEvent:
    return NormalizedEvent(kind="touch", id=idx, edge=edge, raw={})


def _knob(kid: str, edge: str) -> NormalizedEvent:
    return NormalizedEvent(kind="knob", id=kid, edge=edge, raw={})


def test_bare_numeric_button_ids_normalize_to_btn_prefix():
    # Loupedeck Live S reports its physical buttons as bare "1"/"2"/"3".
    assert control_ids_for_lookup(_button("1")) == ["btn_1"]
    assert control_ids_for_lookup(_button("2")) == ["btn_2"]
    assert control_ids_for_lookup(_button("3")) == ["btn_3"]


def test_circle_button_normalizes_to_btn_circle():
    assert control_ids_for_lookup(_button("circle")) == ["btn_circle"]
    assert control_ids_for_lookup(_button("btn_0")) == ["btn_circle"]


def test_already_prefixed_button_id_is_left_alone():
    assert control_ids_for_lookup(_button("btn_1")) == ["btn_1"]


def test_touch_ids_get_touch_prefix():
    assert control_ids_for_lookup(_touch(10)) == ["touch_10"]


def test_knob_lookup_tries_edge_specific_key_before_bare_id():
    assert control_ids_for_lookup(_knob("knobTL", "left")) == ["knobTL_left", "knobTL"]


def test_is_page_scoped_control_only_true_for_touch_keys():
    assert is_page_scoped_control("touch_0") is True
    assert is_page_scoped_control("btn_1") is False
    assert is_page_scoped_control("knobTL") is False
