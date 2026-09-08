"""Normalize Loupedeck callback dicts into matchable events."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Literal

logger = logging.getLogger(__name__)


Edge = Literal["down", "up", "left", "right"]
EventKind = Literal["button", "touch", "knob"]


@dataclass(frozen=True)
class NormalizedEvent:
    kind: EventKind
    """Logical control: physical button id string, touch cell index, or knob id."""

    id: str | int
    edge: Edge
    raw: dict[str, Any]


def normalize_loupedeck_message(msg: dict[str, Any]) -> NormalizedEvent | None:
    """Map python-loupedeck-live callback payload to NormalizedEvent."""

    action = msg.get("action")
    ident = msg.get("id")
    logger.debug("Raw Loupedeck message action=%s id=%s keys=%s", action, ident, list(msg.keys()))

    if action == "push":
        state = msg.get("state")
        if state not in ("down", "up"):
            return None
        bid = str(ident)
        if bid == "btn_0":
            bid = "btn_circle"
        ev = NormalizedEvent(
            kind="button",
            id=bid,
            edge=state,  # type: ignore[assignment]
            raw=msg,
        )
        logger.debug("Normalized button %s %s", ev.id, ev.edge)
        return ev

    if action == "rotate":
        state = msg.get("state")
        if state not in ("left", "right"):
            return None
        ev = NormalizedEvent(
            kind="knob",
            id=str(ident),
            edge=state,  # type: ignore[assignment]
            raw=msg,
        )
        logger.debug("Normalized knob %s %s", ev.id, ev.edge)
        return ev

    if action in ("touchstart", "touchend"):
        screen = msg.get("screen")
        key = msg.get("key")
        if screen != "center" or key is None:
            return None
        edge: Edge = "down" if action == "touchstart" else "up"
        ev = NormalizedEvent(
            kind="touch",
            id=int(key),
            edge=edge,
            raw=msg,
        )
        logger.debug("Normalized touch key=%s %s", key, edge)
        return ev

    logger.debug("Unrecognized Loupedeck message (ignored): %s", msg)
    return None
