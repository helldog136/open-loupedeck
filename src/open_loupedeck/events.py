"""Device-neutral input events (what every device backend delivers to the agent)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

Edge = Literal["down", "up", "left", "right"]
EventKind = Literal["button", "touch", "knob"]


@dataclass(frozen=True)
class NormalizedEvent:
    kind: EventKind
    """Logical control: physical button id string, touch cell index, or knob id."""

    id: str | int
    edge: Edge
    raw: dict[str, Any]


def __getattr__(name: str) -> Any:
    # Backward compatibility: the Loupedeck normaliser moved into the Loupedeck backend. Lazy, so
    # importing this module does not import the backend (and no import cycle is created).
    if name == "normalize_loupedeck_message":
        from .devices.loupedeck.events import normalize_loupedeck_message

        return normalize_loupedeck_message
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
