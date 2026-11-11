"""Device model descriptors: pure data describing a piece of hardware (no driver imports).

A :class:`DeviceModel` says what a device *has* (key grid, knobs, buttons, strips), what it *can
do* (brightness, button LEDs, ...) and the few layout facts the agent needs (which touch key
shows a knob's feedback, which physical buttons select deck pages). Control ids are the config
keys used in ``config.yaml`` (``touch_N``, ``knobTL``, ``btn_circle``, ``strip_left``...): they are
stable across backends and must never change for an existing model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

ControlKind = Literal["button", "knob", "strip", "led_button"]
CONTROL_KINDS: tuple[str, ...] = ("button", "knob", "strip", "led_button")


@dataclass(frozen=True)
class ControlSpec:
    """One control outside the key grid (knob, physical button, side strip)."""

    id: str
    kind: ControlKind
    name: str
    size: tuple[int, int] | None = None
    """Pixel size of the image drawn for this control, or ``None`` when it takes no image."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "name": self.name,
            "size": list(self.size) if self.size else None,
        }


@dataclass(frozen=True)
class KeyGrid:
    """The grid of display keys (touch cells on a Loupedeck), numbered row by row from 0."""

    rows: int
    cols: int
    key_size: tuple[int, int]
    id_prefix: str = "touch_"
    """Control id of key ``n`` is ``f"{id_prefix}{n}"``."""

    @property
    def count(self) -> int:
        return self.rows * self.cols

    def control_id(self, index: int) -> str:
        return f"{self.id_prefix}{int(index)}"

    def control_ids(self) -> list[str]:
        return [self.control_id(i) for i in range(self.count)]

    def index_of(self, control_id: str) -> int | None:
        """Key index of ``control_id`` (``None`` when it is not a key of this grid)."""

        if not control_id.startswith(self.id_prefix):
            return None
        try:
            n = int(control_id[len(self.id_prefix) :])
        except ValueError:
            return None
        return n if 0 <= n < self.count else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "rows": self.rows,
            "cols": self.cols,
            "count": self.count,
            "key_size": list(self.key_size),
            "id_scheme": f"{self.id_prefix}{{index}}",
            "ids": self.control_ids(),
        }


@dataclass(frozen=True)
class Capabilities:
    brightness: bool = True
    button_led: bool = False
    touch: bool = False
    knobs: bool = False

    def to_dict(self) -> dict[str, bool]:
        return {
            "brightness": self.brightness,
            "button_led": self.button_led,
            "touch": self.touch,
            "knobs": self.knobs,
        }


@dataclass(frozen=True)
class DeviceModel:
    """Descriptor of one hardware model. Pure data: safe to import anywhere."""

    id: str
    """Stable model id, e.g. ``loupedeck_live_s``."""
    family: str
    """Backend family that drives it, e.g. ``loupedeck``."""
    name: str
    """Display name, e.g. ``Loupedeck Live S``."""
    grid: KeyGrid
    controls: tuple[ControlSpec, ...] = ()
    capabilities: Capabilities = field(default_factory=Capabilities)
    config_names: tuple[str, ...] = ()
    """Values of ``device.model`` in ``config.yaml`` that select this model (first = canonical)."""
    knob_feedback_keys: tuple[tuple[str, str], ...] = ()
    """``(knob id, key control id)``: the key next to each knob, where its feedback is drawn."""
    page_buttons: tuple[str, ...] = ()
    """Physical buttons that select deck page 0, 1, 2... directly (in that order)."""
    default_button_rgb: tuple[int, int, int] | None = None
    """LED colour of an ``led_button`` without ``button_color`` in the config."""

    # --- lookups ------------------------------------------------------------------------------

    @property
    def config_name(self) -> str:
        """Canonical ``device.model`` value (``live``, ``live_s``); the model id if it has none."""

        return self.config_names[0] if self.config_names else self.id

    def matches_name(self, name: str | None) -> bool:
        n = (name or "").strip().lower()
        return bool(n) and (n == self.id or n in self.config_names)

    def touch_ids(self) -> list[str]:
        return self.grid.control_ids()

    def control(self, control_id: str) -> ControlSpec | None:
        for c in self.controls:
            if c.id == control_id:
                return c
        return None

    def controls_of_kind(self, *kinds: str) -> list[ControlSpec]:
        return [c for c in self.controls if c.kind in kinds]

    def knob_ids(self) -> list[str]:
        return [c.id for c in self.controls_of_kind("knob")]

    def led_button_ids(self) -> list[str]:
        return [c.id for c in self.controls_of_kind("led_button")]

    def has_control(self, control_id: str) -> bool:
        return self.grid.index_of(control_id) is not None or self.control(control_id) is not None

    def drawable_control_ids(self) -> list[str]:
        """Every control that takes an image, keys first (the order of a full redraw)."""

        return self.touch_ids() + [c.id for c in self.controls if c.size is not None]

    def key_size_for(self, control_id: str) -> tuple[int, int]:
        """Image size for ``control_id`` (the grid key size for keys and unknown ids)."""

        spec = self.control(control_id)
        if spec is not None and spec.size is not None:
            return spec.size
        return self.grid.key_size

    def feedback_touch_key(self, knob_id: str) -> str | None:
        return dict(self.knob_feedback_keys).get(knob_id)

    # --- serialisation ------------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "family": self.family,
            "name": self.name,
            "config_name": self.config_name,
            "grid": self.grid.to_dict(),
            "controls": [c.to_dict() for c in self.controls],
            "capabilities": self.capabilities.to_dict(),
            "knob_feedback_keys": dict(self.knob_feedback_keys),
            "page_buttons": list(self.page_buttons),
            "default_button_rgb": list(self.default_button_rgb) if self.default_button_rgb else None,
        }
