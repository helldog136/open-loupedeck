"""Synthetic input for UI-driven test presses (same dispatch path as hardware).

:func:`build_synthetic_event` builds the :class:`ControlEvent` a backend would deliver for a press
/ turn of ``control_id`` (a control id such as ``key_0_0`` / ``knob_1``, or a legacy one such as
``touch_0`` / ``knobCL`` / ``btn_circle``, mapped on the model). :func:`build_synthetic_loupedeck_message`
is the older Loupedeck-shaped callback dict, kept for callers of ``runtime.simulate_raw_message``.
"""

from __future__ import annotations

from typing import Any

from .control_ids import control_to_legacy_id, driver_name_for_button, to_control_id
from .devices.model import DeviceModel, control_kind_from_id
from .devices.registry import default_model
from .events import ControlEvent

_SIMULATED_KINDS = ("key", "button", "knob")
"""Strips (touch areas) have no press to simulate."""


def _control(control_id: str, model: DeviceModel | None) -> tuple[str, str] | None:
    model = model or default_model()
    cid = to_control_id((control_id or "").strip(), model)
    if cid is None:
        return None
    kind = control_kind_from_id(cid)
    if kind not in _SIMULATED_KINDS:
        return None
    return cid, kind


def build_synthetic_event(
    control_id: str,
    *,
    direction: str | None = None,
    model: DeviceModel | None = None,
) -> ControlEvent | None:
    """The event a device delivers for a press of ``control_id`` (or a turn, for a knob with a
    ``direction``); ``None`` if unsupported (strips, unknown ids)."""

    hit = _control(control_id, model)
    if hit is None:
        return None
    cid, kind = hit
    raw: dict[str, Any] = {"synthetic": True, "control_id": (control_id or "").strip()}
    if kind == "knob" and direction in ("left", "right"):
        return ControlEvent(cid, "rotate", 1 if direction == "right" else -1, raw)
    return ControlEvent(cid, "press", None, raw)


def build_synthetic_loupedeck_message(
    control_id: str,
    *,
    direction: str | None = None,
    model: DeviceModel | None = None,
) -> dict[str, Any] | None:
    """Return a dict shaped like the Loupedeck driver callback payload, or ``None`` if unsupported."""

    model = model or default_model()
    hit = _control(control_id, model)
    if hit is None:
        return None
    cid, kind = hit
    if kind == "key":
        lid = control_to_legacy_id(cid, model)
        if lid is None:
            return None
        return {"action": "touchstart", "screen": "center", "key": int(lid[len("touch_") :])}
    if kind == "button":
        name = driver_name_for_button(cid)
        return {"action": "push", "state": "down", "id": name} if name else None
    lid = control_to_legacy_id(cid, model)
    if lid is None:
        return None
    if direction in ("left", "right"):
        return {"action": "rotate", "state": direction, "id": lid}
    return {"action": "push", "state": "down", "id": lid}
