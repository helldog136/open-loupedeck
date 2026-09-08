"""Build synthetic Loupedeck callback dicts for UI-driven test presses (same path as hardware)."""

from __future__ import annotations

import re
from typing import Any

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
