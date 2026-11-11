"""Flat ``bindings`` (optional, used when no page/global binding matched a press).

A rule matches a :class:`ControlEvent` either by control id (current form)::

    - match: {control: key_0_0}          # type defaults to press
      actions: [...]

or by the legacy Loupedeck form, still read as is (``type: touch, key: 0`` / ``type: button,
id: "1"`` / ``type: knob, id: knobTL, edge: left``), mapped on the device model.
"""

from __future__ import annotations

import logging
from typing import Any

from .control_ids import control_to_legacy_id, driver_name_for_button, to_control_id
from .devices.model import DeviceModel, control_kind_from_id
from .events import ControlEvent

logger = logging.getLogger(__name__)


def legacy_signature(ev: ControlEvent, model: DeviceModel) -> tuple[str, str, str] | None:
    """``(kind, id, edge)`` a legacy rule used for ``ev`` (``touch``/``button``/``knob``)."""

    kind = control_kind_from_id(ev.control_id)
    if ev.type in ("press", "release"):
        edge = "down" if ev.type == "press" else "up"
        if kind == "key":
            lid = control_to_legacy_id(ev.control_id, model)
            return ("touch", lid[len("touch_") :], edge) if lid else None
        if kind == "button":
            name = driver_name_for_button(ev.control_id)
            return ("button", name, edge) if name else None
        if kind == "knob":
            lid = control_to_legacy_id(ev.control_id, model)
            return ("button", lid, edge) if lid else None
        return None
    if ev.type == "rotate" and kind == "knob":
        lid = control_to_legacy_id(ev.control_id, model)
        return ("knob", lid, ev.direction or "") if lid else None
    return None


def event_matches_rule(match: dict[str, Any], ev: ControlEvent, model: DeviceModel) -> bool:
    if match.get("control") is not None:
        cid = to_control_id(str(match.get("control")), model)
        want_type = str(match.get("type") or "press")
        if cid != ev.control_id or want_type != ev.type:
            return False
        direction = match.get("direction")
        return direction is None or str(direction) == ev.direction

    sig = legacy_signature(ev, model)
    if sig is None:
        return False
    kind, ident, edge = sig
    m_type = match.get("type")
    if m_type != kind:
        return False
    if kind == "touch":
        want = match.get("key")
        if want is None:
            return False
        try:
            if int(want) != int(ident):
                return False
        except (TypeError, ValueError):
            return False
    else:
        want_id = match.get("id")
        if want_id is None:
            return False
        want_s = str(want_id)
        if want_s in ("btn_circle", "btn_0"):
            want_s = "circle"
        elif want_s.startswith("btn_") and want_s[4:].isdigit():
            want_s = want_s[4:]
        if want_s != str(ident):
            return False
    want_edge = match.get("edge")
    return want_edge is None or str(want_edge) == edge


def actions_for_event(bindings: list[dict[str, Any]], ev: ControlEvent, model: DeviceModel) -> list[dict[str, Any]]:
    """First matching binding wins; returns list of action dicts."""

    for b in bindings:
        if not isinstance(b, dict):
            continue
        match = b.get("match") or {}
        if not isinstance(match, dict) or not event_matches_rule(match, ev, model):
            continue
        if "actions" in b:
            acts = b["actions"]
            if isinstance(acts, list) and len(acts) > 0:
                logger.debug("Flat binding matched %s -> %s action(s)", match, len(acts))
                return list(acts)
            if acts is not None and not isinstance(acts, list):
                raise ValueError("bindings[].actions must be a list")
        if "action" in b:
            a = b["action"]
            if isinstance(a, dict):
                logger.debug("Flat binding matched %s -> single action", match)
                return [a]
            raise ValueError("bindings[].action must be a mapping")
        logger.debug("Flat binding matched %s but no actions", match)
        return []
    logger.debug("No flat binding for %s %s", ev.control_id, ev.type)
    return []
