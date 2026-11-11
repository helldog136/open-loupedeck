"""Device-neutral input events (what every device backend delivers to the agent)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

EventType = Literal["press", "release", "rotate", "touch", "value"]
EVENT_TYPES: tuple[str, ...] = ("press", "release", "rotate", "touch", "value")


@dataclass(frozen=True)
class ControlEvent:
    """One input on one control (``control_id`` is a model control id such as ``key_0_0``).

    ``value`` depends on ``type``: ``rotate`` -> signed steps (+1 = clockwise / right, -1 = left);
    ``touch`` -> ``(x, y)`` in the control's pixels (or ``None``); ``value`` -> 0..1; ``press`` /
    ``release`` -> ``None``.
    """

    control_id: str
    type: EventType
    value: Any = None
    raw: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @property
    def direction(self) -> str | None:
        """``left`` / ``right`` for a rotation, else ``None``."""

        if self.type != "rotate":
            return None
        try:
            return "right" if float(self.value or 0) > 0 else "left"
        except (TypeError, ValueError):
            return None


def __getattr__(name: str) -> Any:
    # Backward compatibility: the Loupedeck normaliser moved into the Loupedeck backend. Lazy, so
    # importing this module does not import the backend (and no import cycle is created).
    if name == "normalize_loupedeck_message":
        from .devices.loupedeck.events import normalize_loupedeck_message

        return normalize_loupedeck_message
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
