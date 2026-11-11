"""Device model descriptors: pure data describing a piece of hardware (no driver imports).

A :class:`DeviceModel` says what a device *has*: a list of typed :class:`Control` objects, each
with a position in the model's abstract ``layout`` and its own capabilities (the inputs it emits,
the outputs it takes). Nothing else is device-wide except ``brightness``. See
``docs/devices-features.md``.

Control ids are stable and model-independent (they are the keys used in ``config.yaml``):

* display keys: ``key_<col>_<row>``, zero-based, column first (``key_0_0`` = top-left);
* everything else: ``knob_<n>``, ``button_<n>``, ``strip_<n>``, ``slider_<n>``, ``pedal_<n>``,
  zero-based in the model's declared order (by position: left to right, then top to bottom).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Literal

ControlKind = Literal["key", "button", "knob", "slider", "strip", "pedal"]
CONTROL_KINDS: tuple[str, ...] = ("key", "button", "knob", "slider", "strip", "pedal")

InputType = Literal["press", "rotate", "touch", "value"]
INPUT_TYPES: tuple[str, ...] = ("press", "rotate", "touch", "value")

LedType = Literal["rgb", "mono"]

_KEY_ID = re.compile(r"^key_(\d+)_(\d+)$")
_INDEXED_ID = re.compile(r"^(button|knob|slider|strip|pedal)_(\d+)$")


# --- ids --------------------------------------------------------------------------------------


def key_id(col: int, row: int) -> str:
    """Control id of the display key at ``(col, row)`` (zero-based)."""

    return f"key_{int(col)}_{int(row)}"


def parse_key_id(control_id: str) -> tuple[int, int] | None:
    """``(col, row)`` of a ``key_<col>_<row>`` id, else ``None``."""

    m = _KEY_ID.match(str(control_id or ""))
    return (int(m.group(1)), int(m.group(2))) if m else None


def indexed_id(kind: str, n: int) -> str:
    return f"{kind}_{int(n)}"


def parse_indexed_id(control_id: str) -> tuple[str, int] | None:
    """``(kind, n)`` of a ``knob_<n>`` / ``button_<n>`` / ... id, else ``None``."""

    m = _INDEXED_ID.match(str(control_id or ""))
    return (m.group(1), int(m.group(2))) if m else None


def control_kind_from_id(control_id: str) -> str | None:
    """Kind implied by a (model-independent) control id, ``None`` for anything else.

    Works for controls the connected device does not have (inactive config entries).
    """

    if parse_key_id(control_id) is not None:
        return "key"
    p = parse_indexed_id(control_id)
    return p[0] if p else None


def is_control_id(control_id: str) -> bool:
    return control_kind_from_id(control_id) is not None


# --- descriptors ------------------------------------------------------------------------------


@dataclass(frozen=True)
class Position:
    """Rectangle in layout units (the model's ``layout`` is the full device)."""

    x: float
    y: float
    w: float = 1.0
    h: float = 1.0

    @property
    def center(self) -> tuple[float, float]:
        return (self.x + self.w / 2.0, self.y + self.h / 2.0)

    def to_dict(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y, "w": self.w, "h": self.h}


@dataclass(frozen=True)
class Control:
    """One physical control and its own capabilities."""

    id: str
    kind: ControlKind
    name: str
    position: Position
    inputs: tuple[str, ...] = ()
    """Input types it emits: ``press`` (press + release), ``rotate``, ``touch``, ``value``."""
    image: tuple[int, int] | None = None
    """Output: pixel size of the image it shows, or ``None`` (no display)."""
    led: LedType | None = None
    """Output: an LED (``rgb`` | ``mono``), or ``None``."""
    default_led: tuple[int, int, int] | None = None
    """LED colour when the config sets none (``None`` = off)."""
    feedback_key: str | None = None
    """Display control showing feedback about this control; ``None`` = the nearest one."""

    def has_input(self, input_type: str) -> bool:
        return input_type in self.inputs

    @property
    def has_image(self) -> bool:
        return self.image is not None

    @property
    def has_led(self) -> bool:
        return self.led is not None

    def outputs_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if self.image is not None:
            out["image"] = {"width": self.image[0], "height": self.image[1]}
        if self.led is not None:
            out["led"] = {"type": self.led, "default": list(self.default_led) if self.default_led else None}
        return out

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "kind": self.kind,
            "name": self.name,
            "position": self.position.to_dict(),
            "inputs": list(self.inputs),
            "outputs": self.outputs_dict(),
        }
        if self.feedback_key is not None:
            d["feedback_key"] = self.feedback_key
        return d


@dataclass(frozen=True)
class DeviceModel:
    """Descriptor of one hardware (or virtual) model. Pure data: safe to import anywhere."""

    id: str
    """Stable model id, e.g. ``loupedeck_live_s``."""
    family: str
    """Backend family that drives it, e.g. ``loupedeck``."""
    name: str
    """Display name, e.g. ``Loupedeck Live S``."""
    layout: tuple[float, float]
    """Abstract size ``(width, height)`` in layout units (control positions use the same units)."""
    controls: tuple[Control, ...] = ()
    brightness: bool = True
    """The screen brightness can be set (the only device-wide capability)."""
    config_names: tuple[str, ...] = ()
    """Values of ``device.model`` in ``config.yaml`` that select this model (first = canonical)."""
    legacy_ids: tuple[tuple[str, str], ...] = field(default=(), repr=False)
    """``(legacy config id, control id)`` pairs, read by the config migration (``touch_N``...)."""

    # --- names --------------------------------------------------------------------------------

    @property
    def config_name(self) -> str:
        """Canonical ``device.model`` value (``live``, ``live_s``); the model id if it has none."""

        return self.config_names[0] if self.config_names else self.id

    def matches_name(self, name: str | None) -> bool:
        n = (name or "").strip().lower()
        return bool(n) and (n == self.id or n in self.config_names)

    # --- lookups ------------------------------------------------------------------------------

    def control(self, control_id: str) -> Control | None:
        for c in self.controls:
            if c.id == control_id:
                return c
        return None

    def has_control(self, control_id: str) -> bool:
        return self.control(control_id) is not None

    def controls_of_kind(self, *kinds: str) -> list[Control]:
        return [c for c in self.controls if c.kind in kinds]

    def keys(self) -> list[Control]:
        """Display keys, row by row (``key_0_0``, ``key_1_0``...)."""

        keys = self.controls_of_kind("key")
        return sorted(keys, key=lambda c: (parse_key_id(c.id) or (0, 0))[::-1])

    def ids_of_kind(self, *kinds: str) -> list[str]:
        return [c.id for c in self.controls_of_kind(*kinds)]

    def grid_of_keys(self) -> tuple[int, int]:
        """``(cols, rows)`` of the display key grid (``(0, 0)`` without keys)."""

        cr = [parse_key_id(c.id) for c in self.controls_of_kind("key")]
        pts = [p for p in cr if p is not None]
        if not pts:
            return (0, 0)
        return (max(p[0] for p in pts) + 1, max(p[1] for p in pts) + 1)

    def image_controls(self) -> list[Control]:
        """Every control that shows an image, keys first (the order of a full redraw)."""

        keys = [c for c in self.keys() if c.has_image]
        return keys + [c for c in self.controls if c.has_image and c.kind != "key"]

    def led_controls(self) -> list[Control]:
        return [c for c in self.controls if c.has_led]

    def image_size(self, control_id: str) -> tuple[int, int] | None:
        c = self.control(control_id)
        return c.image if c is not None else None

    def nearest_display(self, control_id: str) -> Control | None:
        """The image control closest (by position centres) to ``control_id``, never itself."""

        src = self.control(control_id)
        if src is None:
            return None
        sx, sy = src.position.center
        best: tuple[float, int, Control] | None = None
        for i, c in enumerate(self.image_controls()):
            if c.id == src.id:
                continue
            cx, cy = c.position.center
            d = math.hypot(cx - sx, cy - sy)
            if best is None or (d, i) < best[:2]:
                best = (d, i, c)
        return best[2] if best else None

    def feedback_key_for(self, control_id: str) -> str | None:
        """Where feedback about ``control_id`` is drawn: its ``feedback_key``, else the nearest
        display control; ``None`` = no visual feedback on the device."""

        c = self.control(control_id)
        if c is None:
            return None
        if c.feedback_key is not None:
            return c.feedback_key if self.has_control(c.feedback_key) else None
        near = self.nearest_display(control_id)
        return near.id if near is not None else None

    def legacy_map(self) -> dict[str, str]:
        return dict(self.legacy_ids)

    def legacy_id_of(self, control_id: str) -> str | None:
        for legacy, cid in self.legacy_ids:
            if cid == control_id:
                return legacy
        return None

    # --- checks -------------------------------------------------------------------------------

    def problems(self) -> list[str]:
        """Consistency problems of this descriptor (empty = valid); used by the tests."""

        out: list[str] = []
        ids = [c.id for c in self.controls]
        if len(ids) != len(set(ids)):
            out.append("duplicate control ids")
        for c in self.controls:
            if control_kind_from_id(c.id) != c.kind:
                out.append(f"{c.id}: id does not match kind {c.kind}")
            if any(i not in INPUT_TYPES for i in c.inputs):
                out.append(f"{c.id}: unknown input type")
            p = c.position
            if p.x < 0 or p.y < 0 or p.x + p.w > self.layout[0] + 1e-9 or p.y + p.h > self.layout[1] + 1e-9:
                out.append(f"{c.id}: outside the layout")
            if c.feedback_key is not None and not self.has_control(c.feedback_key):
                out.append(f"{c.id}: unknown feedback_key {c.feedback_key}")
        for kind in CONTROL_KINDS:
            if kind == "key":
                keys = [(parse_key_id(c.id) or (-1, -1), c.position) for c in self.controls_of_kind("key")]
                for (col, row), p in keys:
                    for (ocol, orow), o in keys:
                        if (row == orow and ocol < col and o.x >= p.x) or (col == ocol and orow < row and o.y >= p.y):
                            out.append(f"key_{col}_{row}: position does not follow its column/row")
                continue
            ctl = self.controls_of_kind(kind)
            by_pos = sorted(ctl, key=lambda c: (c.position.x, c.position.y))
            if [c.id for c in by_pos] != [indexed_id(kind, i) for i in range(len(ctl))]:
                out.append(f"{kind} ids are not numbered by position (left to right, then top to bottom)")
        for legacy, cid in self.legacy_ids:
            if not self.has_control(cid):
                out.append(f"legacy id {legacy} -> unknown control {cid}")
        return out

    # --- serialisation ------------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        cols, rows = self.grid_of_keys()
        return {
            "id": self.id,
            "family": self.family,
            "name": self.name,
            "config_name": self.config_name,
            "config_names": list(self.config_names),
            "layout": {"width": self.layout[0], "height": self.layout[1]},
            "brightness": self.brightness,
            "grid": {"cols": cols, "rows": rows, "count": cols * rows},
            "controls": [c.to_dict() for c in self.controls],
            "feedback_keys": {
                c.id: self.feedback_key_for(c.id) for c in self.controls if c.kind != "key" and not c.has_image
            },
            "legacy_ids": dict(self.legacy_ids),
        }
