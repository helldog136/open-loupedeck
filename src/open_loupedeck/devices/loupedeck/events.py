"""Normalize python-loupedeck-live callback dicts into :class:`ControlEvent` (Loupedeck only).

The driver reports buttons by protocol name (``circle``, ``1``..``7``, ``knobTL``... for a knob
push), rotations by knob name and touches by key index on the centre screen (or ``left`` /
``right`` screens on the Live). Ids are mapped through the model's legacy-id table.
"""

from __future__ import annotations

import logging
from typing import Any

from ...control_ids import legacy_to_control_id
from ...devices.model import DeviceModel, is_control_id
from ...events import ControlEvent
from .models import DEFAULT_MODEL

logger = logging.getLogger(__name__)


def _legacy_button_id(ident: Any) -> str:
    bid = str(ident)
    if bid in ("circle", "btn_0", "0"):
        return "btn_circle"
    if bid.isdigit():
        return f"btn_{bid}"
    return bid  # knobTL..., btn_N, or already a control id


def _control_id(legacy_or_cid: str, model: DeviceModel) -> str | None:
    if is_control_id(legacy_or_cid):
        return legacy_or_cid
    return legacy_to_control_id(legacy_or_cid, model)


def normalize_loupedeck_message(msg: dict[str, Any], model: DeviceModel | None = None) -> ControlEvent | None:
    """Map a python-loupedeck-live callback payload to a :class:`ControlEvent` on ``model``.

    ``model`` defaults to the Live S (used for synthetic messages without a connected device).
    """

    model = model or DEFAULT_MODEL
    action = msg.get("action")
    ident = msg.get("id")
    logger.debug("Raw Loupedeck message action=%s id=%s keys=%s", action, ident, list(msg.keys()))

    if action == "push":
        state = msg.get("state")
        if state not in ("down", "up"):
            return None
        cid = _control_id(_legacy_button_id(ident), model)
        if cid is None:
            logger.debug("Loupedeck push from unknown control %r (ignored)", ident)
            return None
        ev = ControlEvent(cid, "press" if state == "down" else "release", None, msg)
        logger.debug("Normalized %s %s", ev.control_id, ev.type)
        return ev

    if action == "rotate":
        state = msg.get("state")
        if state not in ("left", "right"):
            return None
        cid = _control_id(str(ident), model)
        if cid is None:
            logger.debug("Loupedeck rotation from unknown control %r (ignored)", ident)
            return None
        ev = ControlEvent(cid, "rotate", 1 if state == "right" else -1, msg)
        logger.debug("Normalized %s rotate %s", ev.control_id, state)
        return ev

    if action in ("touchstart", "touchend"):
        screen = msg.get("screen")
        key = msg.get("key")
        if screen == "center" and key is not None:
            cid = _control_id(f"touch_{int(key)}", model)
            if cid is None:
                return None
            ev = ControlEvent(cid, "press" if action == "touchstart" else "release", None, msg)
            logger.debug("Normalized touch %s %s", ev.control_id, ev.type)
            return ev
        if screen in ("left", "right") and action == "touchstart":
            cid = _control_id(f"strip_{screen}", model)
            if cid is None or not model.has_control(cid):
                return None
            return ControlEvent(cid, "touch", (msg.get("x"), msg.get("y")), msg)
        return None

    logger.debug("Unrecognized Loupedeck message (ignored): %s", msg)
    return None
