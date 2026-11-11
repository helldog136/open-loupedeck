"""Descriptors of the virtual models (pure data, no import beyond the model layer).

Layout units: one display key is 1 x 1.

* ``virtual_15`` mirrors the Loupedeck Live S (same control ids and positions), so configs written
  for a Live S work unchanged.
* ``virtual_mega`` is the example of ``docs/devices-features.md``: 64 keys (8 x 8), 12 buttons,
  6 knobs and one slider.
* ``virtual_mini`` is a small deck: 3 x 2 keys and nothing else.
"""

from __future__ import annotations

from ..loupedeck.models import LOUPEDECK_LIVE_S
from ..model import Control, DeviceModel, Position, key_id

FAMILY = "virtual"
LED_DEFAULT = (32, 32, 40)


def _keys(cols: int, rows: int, x0: float, size: tuple[int, int]) -> tuple[Control, ...]:
    return tuple(
        Control(
            key_id(c, r),
            "key",
            f"Key {r * cols + c + 1}",
            Position(x0 + c, r),
            inputs=("press",),
            image=size,
        )
        for r in range(rows)
        for c in range(cols)
    )


def _button(n: int, x: float, y: float) -> Control:
    return Control(
        f"button_{n}",
        "button",
        f"Button {n + 1}",
        Position(x, y, 0.7, 0.7),
        inputs=("press",),
        led="rgb",
        default_led=LED_DEFAULT,
    )


def _knob(n: int, x: float, y: float, feedback_key: str | None = None) -> Control:
    return Control(
        f"knob_{n}",
        "knob",
        f"Knob {n + 1}",
        Position(x, y, 0.8, 0.8),
        inputs=("press", "rotate"),
        feedback_key=feedback_key,
    )


# --- virtual_15 (Live S look-alike) -----------------------------------------------------------

VIRTUAL_15 = DeviceModel(
    id="virtual_15",
    family=FAMILY,
    name="Virtual 15",
    layout=(7, 3),
    controls=(
        *_keys(5, 3, 1, (90, 90)),
        _knob(0, 0.1, 0.1, key_id(0, 0)),
        _knob(1, 0.1, 1.1, key_id(0, 1)),
        _button(0, 0.15, 2.15),
        *(_button(i, 6.15, i - 1 + 0.15) for i in range(1, 4)),
    ),
    brightness=True,
    config_names=("virtual", "virtual_15"),
    legacy_ids=LOUPEDECK_LIVE_S.legacy_ids,
)

# --- virtual_mega -----------------------------------------------------------------------------

VIRTUAL_MEGA = DeviceModel(
    id="virtual_mega",
    family=FAMILY,
    name="Virtual Mega",
    layout=(13, 9.2),
    controls=(
        *_keys(8, 8, 2, (72, 72)),
        *(_knob(i, 0.6, 1.1 + 2.5 * i) for i in range(3)),
        *(_knob(3 + i, 10.9, 1.1 + 2.5 * i) for i in range(3)),
        *(_button(i, 0.65 + i * 1.0, 8.3) for i in range(12)),
        Control("slider_0", "slider", "Slider", Position(12.2, 1.0, 0.6, 6.0), inputs=("value",)),
    ),
    brightness=True,
    config_names=("virtual_mega",),
)

# --- virtual_mini -----------------------------------------------------------------------------

VIRTUAL_MINI = DeviceModel(
    id="virtual_mini",
    family=FAMILY,
    name="Virtual Mini",
    layout=(3, 2),
    controls=_keys(3, 2, 0, (96, 96)),
    brightness=True,
    config_names=("virtual_mini",),
)

VIRTUAL_MODELS: tuple[DeviceModel, ...] = (VIRTUAL_15, VIRTUAL_MEGA, VIRTUAL_MINI)

DEFAULT_VIRTUAL_MODEL = VIRTUAL_15
"""Model used for ``device.model: virtual`` / ``--virtual`` without a model name."""
