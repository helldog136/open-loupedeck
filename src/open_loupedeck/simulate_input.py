"""Synthetic input for UI-driven test presses (same dispatch path as hardware).

:func:`build_synthetic_event` builds the device-neutral :class:`NormalizedEvent` a backend would
deliver for a press / turn of ``control_id``. :func:`build_synthetic_loupedeck_message` is the
older Loupedeck-shaped callback dict, kept for callers of ``runtime.simulate_raw_message``.
"""

from __future__ import annotations

import re
from typing import Any

from .events import NormalizedEvent
from .knob_pages import KNOB_ENCODER_IDS

_TOUCH = re.compile(r"^touch_(\d+)$")
_BTN_NUM = re.compile(r"^btn_(\d+)$")


def build_synthetic_loupedeck_message(
    control_id: str,
    *,
    direction: str | None = None,
) -> dict[str, Any] | None:
    """Return a dict shaped like the device callback payload, or ``None`` if unsupported."""

    cid = (control_id or "").strip()
    if not cid:
        return None
    low = cid.lower()
    if low in ("strip_left", "strip_right", "left", "right"):
        return None

    m = _TOUCH.match(cid)
    if m:
        return {
            "action": "touchstart",
            "screen": "center",
            "key": int(m.group(1)),
        }

    if cid == "btn_circle" or cid == "circle":
        return {"action": "push", "state": "down", "id": "circle"}
    if cid == "btn_0":
        return {"action": "push", "state": "down", "id": "btn_0"}

    m = _BTN_NUM.match(cid)
    if m:
        return {"action": "push", "state": "down", "id": m.group(1)}

    if cid in KNOB_ENCODER_IDS:
        if direction in ("left", "right"):
            return {"action": "rotate", "state": direction, "id": cid}
        return {"action": "push", "state": "down", "id": cid}

    return None


def build_synthetic_event(control_id: str, *, direction: str | None = None) -> NormalizedEvent | None:
    """The event a device delivers for a press of ``control_id`` (or a turn, for a knob with a
    ``direction``); ``None`` if unsupported. Button ids are the ones the Loupedeck backend reports
    (``circle``, ``1``...), which :func:`~open_loupedeck.control_ids.control_ids_for_lookup` maps
    to ``btn_*``."""

    cid = (control_id or "").strip()
    if not cid:
        return None
    low = cid.lower()
    if low in ("strip_left", "strip_right", "left", "right"):
        return None
    raw: dict[str, Any] = {"synthetic": True, "control_id": cid}
    m = _TOUCH.match(cid)
    if m:
        return NormalizedEvent(kind="touch", id=int(m.group(1)), edge="down", raw=raw)
    if cid == "btn_circle" or cid == "circle":
        return NormalizedEvent(kind="button", id="circle", edge="down", raw=raw)
    if cid == "btn_0":
        return NormalizedEvent(kind="button", id="btn_circle", edge="down", raw=raw)
    m = _BTN_NUM.match(cid)
    if m:
        return NormalizedEvent(kind="button", id=m.group(1), edge="down", raw=raw)
    if cid in KNOB_ENCODER_IDS:
        if direction in ("left", "right"):
            return NormalizedEvent(kind="knob", id=cid, edge=direction, raw=raw)  # type: ignore[arg-type]
        return NormalizedEvent(kind="button", id=cid, edge="down", raw=raw)
    return None
