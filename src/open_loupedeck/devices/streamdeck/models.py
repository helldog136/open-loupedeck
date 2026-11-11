"""Descriptors of the Elgato Stream Deck models (pure data, no driver import).

Layout units: one display key is 1 x 1. Positions follow the hardware (front view):

* Mini: 3 x 2 keys. Original / MK.2: 5 x 3 keys. XL: 8 x 4 keys.
* Stream Deck +: 4 x 2 keys, the 800 x 100 touch strip below them, four push dials at the bottom.
* Neo: 4 x 2 keys; below them a touch button on each side of the small info screen. The touch
  buttons carry an RGB LED (``set_key_color`` in the library), the info screen only shows an image.
* Pedal: three pedals (left, centre, right), press only, no display.

The pixel sizes are the ones python-elgato-streamdeck documents for each model (its
``KEY_PIXEL_WIDTH`` / ``TOUCHSCREEN_PIXEL_WIDTH`` / ``SCREEN_PIXEL_WIDTH`` constants); the backend
reads the real ones from the library when a deck is opened (:func:`with_sizes`).

Every model is experimental: none was tested on hardware yet (see ``docs/streamdeck.md``).
"""

from __future__ import annotations

import dataclasses

from ..model import Control, DeviceModel, Position, key_id

FAMILY = "streamdeck"
LED_DEFAULT = (32, 32, 40)


def _keys(cols: int, rows: int, size: tuple[int, int]) -> tuple[Control, ...]:
    return tuple(
        Control(
            key_id(c, r),
            "key",
            f"Key {r * cols + c + 1}",
            Position(c, r),
            inputs=("press",),
            image=size,
        )
        for r in range(rows)
        for c in range(cols)
    )


STREAMDECK_MINI = DeviceModel(
    id="streamdeck_mini",
    family=FAMILY,
    name="Stream Deck Mini (experimental)",
    layout=(3, 2),
    controls=_keys(3, 2, (80, 80)),
    brightness=True,
    config_names=("streamdeck_mini",),
)

STREAMDECK_MK2 = DeviceModel(
    id="streamdeck_mk2",
    family=FAMILY,
    name="Stream Deck MK.2 (experimental)",
    layout=(5, 3),
    controls=_keys(5, 3, (72, 72)),
    brightness=True,
    # ``streamdeck`` = any Stream Deck (the backend opens whichever model is attached); its key
    # coordinates refer to the 5 x 3 grid, like the Loupedeck Live S.
    config_names=("streamdeck_mk2", "streamdeck_original", "streamdeck"),
)

STREAMDECK_XL = DeviceModel(
    id="streamdeck_xl",
    family=FAMILY,
    name="Stream Deck XL (experimental)",
    layout=(8, 4),
    controls=_keys(8, 4, (96, 96)),
    brightness=True,
    config_names=("streamdeck_xl",),
)

STREAMDECK_PLUS = DeviceModel(
    id="streamdeck_plus",
    family=FAMILY,
    name="Stream Deck + (experimental)",
    layout=(4, 3.8),
    controls=(
        *_keys(4, 2, (120, 120)),
        Control("strip_0", "strip", "Touch strip", Position(0, 2.15, 4, 0.5), inputs=("touch",), image=(800, 100)),
        # Feedback about a dial goes to the key right above it (the strip is one shared display).
        *(
            Control(
                f"knob_{n}",
                "knob",
                f"Dial {n + 1}",
                Position(n + 0.1, 2.85, 0.8, 0.8),
                inputs=("press", "rotate"),
                feedback_key=key_id(n, 1),
            )
            for n in range(4)
        ),
    ),
    brightness=True,
    config_names=("streamdeck_plus",),
)

STREAMDECK_NEO = DeviceModel(
    id="streamdeck_neo",
    family=FAMILY,
    name="Stream Deck Neo (experimental)",
    layout=(4, 2.7),
    controls=(
        *_keys(4, 2, (96, 96)),
        Control(
            "button_0",
            "button",
            "Left touch button",
            Position(0.15, 2.1, 0.7, 0.5),
            inputs=("press",),
            led="rgb",
            default_led=LED_DEFAULT,
        ),
        Control("strip_0", "strip", "Info screen", Position(1, 2.1, 2, 0.47), image=(248, 58)),
        Control(
            "button_1",
            "button",
            "Right touch button",
            Position(3.15, 2.1, 0.7, 0.5),
            inputs=("press",),
            led="rgb",
            default_led=LED_DEFAULT,
        ),
    ),
    brightness=True,
    config_names=("streamdeck_neo",),
)

STREAMDECK_PEDAL = DeviceModel(
    id="streamdeck_pedal",
    family=FAMILY,
    name="Stream Deck Pedal (experimental)",
    layout=(3.4, 1.6),
    controls=(
        Control("pedal_0", "pedal", "Left pedal", Position(0, 0.2, 1, 1.4), inputs=("press",)),
        Control("pedal_1", "pedal", "Centre pedal", Position(1.1, 0, 1.2, 1.6), inputs=("press",)),
        Control("pedal_2", "pedal", "Right pedal", Position(2.4, 0.2, 1, 1.4), inputs=("press",)),
    ),
    brightness=False,
    config_names=("streamdeck_pedal",),
)

STREAMDECK_MODELS: tuple[DeviceModel, ...] = (
    STREAMDECK_MINI,
    STREAMDECK_MK2,
    STREAMDECK_XL,
    STREAMDECK_PLUS,
    STREAMDECK_NEO,
    STREAMDECK_PEDAL,
)

ANY_STREAMDECK = "streamdeck"
"""``device.model`` value that opens whichever Stream Deck is attached."""

DECK_TYPES: dict[str, DeviceModel] = {
    "Stream Deck Mini": STREAMDECK_MINI,
    "Stream Deck Original": STREAMDECK_MK2,
    "Stream Deck XL": STREAMDECK_XL,
    "Stream Deck +": STREAMDECK_PLUS,
    "Stream Deck Neo": STREAMDECK_NEO,
    "Stream Deck Pedal": STREAMDECK_PEDAL,
}
"""python-elgato-streamdeck ``deck_type()`` -> model. The library reports the Original, the
Original V2 and every MK.2 variant as ``Stream Deck Original`` (same 5 x 3 keys)."""


def with_sizes(
    model: DeviceModel,
    key_size: tuple[int, int] | None = None,
    strip_size: tuple[int, int] | None = None,
) -> DeviceModel:
    """``model`` with the key / strip pixel sizes the library reports (unchanged when it agrees or
    reports nothing usable). Ids, positions and names never change."""

    def ok(size: tuple[int, int] | None) -> bool:
        return size is not None and len(size) == 2 and int(size[0]) > 0 and int(size[1]) > 0

    controls = []
    changed = False
    for c in model.controls:
        size = key_size if c.kind == "key" else strip_size if c.kind == "strip" else None
        if c.image is not None and ok(size) and tuple(size) != c.image:  # type: ignore[arg-type]
            c = dataclasses.replace(c, image=(int(size[0]), int(size[1])))  # type: ignore[index]
            changed = True
        controls.append(c)
    return dataclasses.replace(model, controls=tuple(controls)) if changed else model
