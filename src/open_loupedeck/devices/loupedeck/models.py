"""Descriptors of the Loupedeck models (pure data, no driver import).

Layout units: one display key is 1 x 1. Positions follow the hardware (front view):

* Live S: two knobs on the left (top, middle) above the round "circle" button, the 5 x 3 key grid,
  three round buttons on the right.
* Live: three knobs on each side, a 60 x 270 touch strip on each side of the 4 x 3 key grid, and
  a row of eight round buttons below (circle, 1..7, left to right).

The ``legacy_ids`` tables map the ids of configs written before ``config_version: 2``
(``touch_N``, ``knobTL``..., ``btn_circle``, ``btn_N``, ``strip_left``/``strip_right``).
"""

from __future__ import annotations

from ..model import Control, DeviceModel, Position, key_id

KEY_SIZE = (90, 90)
STRIP_SIZE = (60, 270)
LIVE_S_LED_DEFAULT = (32, 32, 40)

LEGACY_KNOB_IDS: tuple[str, ...] = ("knobTL", "knobCL", "knobBL", "knobTR", "knobCR", "knobBR")
"""Every legacy knob id (also the knob ids the python-loupedeck driver reports)."""

_KNOB_NAMES = {
    "knobTL": "Top-left knob",
    "knobCL": "Middle-left knob",
    "knobBL": "Bottom-left knob",
    "knobTR": "Top-right knob",
    "knobCR": "Middle-right knob",
    "knobBR": "Bottom-right knob",
}


def _keys(cols: int, rows: int, x0: float) -> tuple[Control, ...]:
    return tuple(
        Control(
            key_id(c, r),
            "key",
            f"Key {r * cols + c + 1}",
            Position(x0 + c, r),
            inputs=("press",),
            image=KEY_SIZE,
        )
        for r in range(rows)
        for c in range(cols)
    )


def _legacy_keys(cols: int, rows: int) -> tuple[tuple[str, str], ...]:
    return tuple((f"touch_{r * cols + c}", key_id(c, r)) for r in range(rows) for c in range(cols))


def _knob(n: int, legacy: str, x: float, y: float, feedback_key: str) -> Control:
    return Control(
        f"knob_{n}",
        "knob",
        _KNOB_NAMES[legacy],
        Position(x + 0.1, y + 0.1, 0.8, 0.8),
        inputs=("press", "rotate"),
        feedback_key=feedback_key,
    )


# --- Loupedeck Live S ------------------------------------------------------------------------

_LIVE_S_KNOBS = ("knobTL", "knobCL")

LOUPEDECK_LIVE_S = DeviceModel(
    id="loupedeck_live_s",
    family="loupedeck",
    name="Loupedeck Live S",
    layout=(7, 3),
    controls=(
        *_keys(5, 3, 1),
        # Each dial shows its feedback on the first key of its row (touch_0 / touch_5 before v2).
        _knob(0, "knobTL", 0, 0, key_id(0, 0)),
        _knob(1, "knobCL", 0, 1, key_id(0, 1)),
        Control(
            "button_0",
            "button",
            "Round button 1",
            Position(0.15, 2.15, 0.7, 0.7),
            inputs=("press",),
            led="rgb",
            default_led=LIVE_S_LED_DEFAULT,
        ),
        *(
            Control(
                f"button_{i}",
                "button",
                f"Round button {i + 1}",
                Position(6.15, i - 1 + 0.15, 0.7, 0.7),
                inputs=("press",),
                led="rgb",
                default_led=LIVE_S_LED_DEFAULT,
            )
            for i in range(1, 4)
        ),
    ),
    brightness=True,
    config_names=("live_s",),
    legacy_ids=(
        *_legacy_keys(5, 3),
        ("knobTL", "knob_0"),
        ("knobCL", "knob_1"),
        ("btn_circle", "button_0"),
        ("btn_1", "button_1"),
        ("btn_2", "button_2"),
        ("btn_3", "button_3"),
    ),
)

# --- Loupedeck Live --------------------------------------------------------------------------

LOUPEDECK_LIVE = DeviceModel(
    id="loupedeck_live",
    family="loupedeck",
    name="Loupedeck Live",
    layout=(8, 4),
    controls=(
        *_keys(4, 3, 2),
        # Each knob flashes its feedback on the key of its row next to it (not on the strip).
        _knob(0, "knobTL", 0, 0, key_id(0, 0)),
        _knob(1, "knobCL", 0, 1, key_id(0, 1)),
        _knob(2, "knobBL", 0, 2, key_id(0, 2)),
        _knob(3, "knobTR", 7, 0, key_id(3, 0)),
        _knob(4, "knobCR", 7, 1, key_id(3, 1)),
        _knob(5, "knobBR", 7, 2, key_id(3, 2)),
        Control("strip_0", "strip", "Left strip", Position(1, 0, 1, 3), inputs=("touch",), image=STRIP_SIZE),
        Control("strip_1", "strip", "Right strip", Position(6, 0, 1, 3), inputs=("touch",), image=STRIP_SIZE),
        # The eight round buttons have RGB LEDs in hardware, but they are not driven yet (no
        # Loupedeck Live to verify the LED protocol on): no output declared.
        Control("button_0", "button", "Circle button", Position(0.15, 3.15, 0.7, 0.7), inputs=("press",)),
        *(
            Control(f"button_{i}", "button", f"Button {i}", Position(i + 0.15, 3.15, 0.7, 0.7), inputs=("press",))
            for i in range(1, 8)
        ),
    ),
    brightness=True,
    config_names=("live",),
    legacy_ids=(
        *_legacy_keys(4, 3),
        *((k, f"knob_{i}") for i, k in enumerate(LEGACY_KNOB_IDS)),
        ("btn_circle", "button_0"),
        *((f"btn_{i}", f"button_{i}") for i in range(1, 8)),
        ("strip_left", "strip_0"),
        ("strip_right", "strip_1"),
    ),
)

LOUPEDECK_MODELS: tuple[DeviceModel, ...] = (LOUPEDECK_LIVE, LOUPEDECK_LIVE_S)

DEFAULT_MODEL = LOUPEDECK_LIVE_S
"""Model assumed when ``device.model`` is ``auto`` and no device is connected."""
