"""Map hardware events to stable control id strings used in page.buttons."""

from __future__ import annotations

from .events import NormalizedEvent


def is_page_scoped_control(control_id: str) -> bool:
    """True for center touch cells only (``touch_*``). Knobs, side buttons, strips use ``global_buttons``."""

    return control_id.startswith("touch_")


def control_ids_for_lookup(ev: NormalizedEvent) -> list[str]:
    """Ordered keys to try when resolving page.buttons (most specific first)."""

    if ev.kind == "touch":
        return [f"touch_{int(ev.id)}"]

    if ev.kind == "button":
        bid = str(ev.id)
        # Canonical lower-left Live S key is btn_circle (never btn_0); normalize defensively.
        if bid == "btn_0":
            bid = "btn_circle"
        if bid.startswith("btn_"):
            return [bid]
        if bid == "circle":
            return ["btn_circle"]
        return [f"btn_{bid}"]

    if ev.kind == "knob":
        kid = str(ev.id)
        edge = str(ev.edge)
        return [f"{kid}_{edge}", kid]

    return []
