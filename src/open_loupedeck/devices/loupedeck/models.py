"""Descriptors of the Loupedeck models (pure data, no driver import)."""

from __future__ import annotations

from ..model import Capabilities, ControlSpec, DeviceModel, KeyGrid

KEY_SIZE = (90, 90)
STRIP_SIZE = (60, 270)

_KNOB_NAMES = {
    "knobTL": "Top-left knob",
    "knobCL": "Middle-left knob",
    "knobBL": "Bottom-left knob",
    "knobTR": "Top-right knob",
    "knobCR": "Middle-right knob",
    "knobBR": "Bottom-right knob",
}


def _knobs(*ids: str) -> tuple[ControlSpec, ...]:
    return tuple(ControlSpec(k, "knob", _KNOB_NAMES[k]) for k in ids)


LOUPEDECK_LIVE = DeviceModel(
    id="loupedeck_live",
    family="loupedeck",
    name="Loupedeck Live",
    grid=KeyGrid(rows=3, cols=4, key_size=KEY_SIZE),
    controls=(
        *_knobs("knobTL", "knobCL", "knobBL", "knobTR", "knobCR", "knobBR"),
        ControlSpec("btn_circle", "button", "Circle button"),
        # Historical behaviour kept as is: btn_1..btn_7 are redrawn with a key-sized image, which
        # the driver sends to set_key_image("1".."7") (see LoupedeckBackend.set_key_image).
        *(ControlSpec(f"btn_{i}", "button", f"Button {i}", KEY_SIZE) for i in range(1, 8)),
        ControlSpec("strip_left", "strip", "Left strip", STRIP_SIZE),
        ControlSpec("strip_right", "strip", "Right strip", STRIP_SIZE),
    ),
    capabilities=Capabilities(brightness=True, button_led=False, touch=True, knobs=True),
    config_names=("live",),
    # Each knob flashes its feedback on the touch key of its row, in the column next to it.
    knob_feedback_keys=(
        ("knobTL", "touch_0"),
        ("knobCL", "touch_4"),
        ("knobBL", "touch_8"),
        ("knobTR", "touch_3"),
        ("knobCR", "touch_7"),
        ("knobBR", "touch_11"),
    ),
)

LOUPEDECK_LIVE_S = DeviceModel(
    id="loupedeck_live_s",
    family="loupedeck",
    name="Loupedeck Live S",
    grid=KeyGrid(rows=3, cols=5, key_size=KEY_SIZE),
    controls=(
        *_knobs("knobTL", "knobCL"),
        ControlSpec("btn_circle", "led_button", "Round button 1"),
        ControlSpec("btn_1", "led_button", "Round button 2"),
        ControlSpec("btn_2", "led_button", "Round button 3"),
        ControlSpec("btn_3", "led_button", "Round button 4"),
    ),
    capabilities=Capabilities(brightness=True, button_led=True, touch=True, knobs=True),
    config_names=("live_s",),
    # Top dial -> touch_0, lower dial -> touch_5 (first column of rows 1 and 2).
    knob_feedback_keys=(("knobTL", "touch_0"), ("knobCL", "touch_5")),
    page_buttons=("btn_circle", "btn_1", "btn_2", "btn_3"),
    default_button_rgb=(32, 32, 40),
)

LOUPEDECK_MODELS: tuple[DeviceModel, ...] = (LOUPEDECK_LIVE, LOUPEDECK_LIVE_S)
