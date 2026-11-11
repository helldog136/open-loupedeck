"""Draw page images onto the connected device, through its backend and model descriptor.

Every control with an ``image`` output gets the image of its binding (page binding, else global;
see :mod:`.bindings`), every control with an ``led`` output the colour of its binding's
``button_color`` (else the control's default LED colour).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from PIL import Image, ImageColor

from .bindings import page_bindings, resolve_in
from .button_render import DEFAULT_KEY_SIZE, effective_graphic_source, render_tactile_key_image
from .devices.base import device_model_of
from .key_media_cache import raw_graphic_needs_skin_animation
from .live_message import (
    dynamic_display_overlay_entry,
    spotify_state_entry,
    spotify_state_params_from_entry,
)
from .look_defaults import proposed_entry

logger = logging.getLogger(__name__)


def _rgb_from_button_color(raw: Any) -> tuple[int, int, int] | None:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    try:
        t = ImageColor.getrgb(s)
        return (int(t[0]), int(t[1]), int(t[2]))
    except Exception:
        return None


def _apply_leds(deck: Any, page: dict[str, Any], gb: dict[str, Any], page_index: int) -> None:
    """Drive the LEDs of the model's controls with an ``led`` output (``button_color``)."""

    model = device_model_of(deck)
    if model is None:
        return
    for ctl in model.led_controls():
        b = resolve_in(page, gb, ctl.id, page_index)
        rgb = ctl.default_led or (0, 0, 0)
        if b is not None:
            parsed = _rgb_from_button_color(b.entry.get("button_color"))
            if parsed is not None:
                rgb = parsed
        try:
            deck.set_led(ctl.id, rgb)
        except Exception:
            logger.exception("set_led failed control_id=%s rgb=%s", ctl.id, rgb)


def _blank_rgba(size: tuple[int, int]) -> Image.Image:
    return Image.new("RGBA", size, (0, 0, 0, 255))


def drawable_control_ids(deck: Any) -> list[str]:
    """All controls with an ``image`` output on this device (redraw order: keys first).

    From the model descriptor. On the Live S that is only the 5×3 key grid: its round buttons
    have no display.
    """

    model = device_model_of(deck)
    return [c.id for c in model.image_controls()] if model is not None else []


def _entry_for_skin(page: dict[str, Any], gb: dict[str, Any], control_id: str, page_index: int):
    b = resolve_in(page, gb, control_id, page_index)
    return (b.entry, b.storage_key) if b is not None else (None, None)


def page_needs_animated_skin(
    deck: Any,
    page: dict[str, Any],
    global_bindings: dict[str, Any],
    config_dir: Path,
) -> bool:
    """True if any drawable key on this page needs periodic redraw: a video/multi-frame GIF, or a
    configured ``idle_animation`` (see ``button_render.py``)."""

    gb = global_bindings if isinstance(global_bindings, dict) else {}
    for control_id in drawable_control_ids(deck):
        entry, _sk = _entry_for_skin(page, gb, control_id, 0)
        if not isinstance(entry, dict):
            continue
        raw = effective_graphic_source(entry)
        if raw and raw_graphic_needs_skin_animation(str(raw), config_dir):
            return True
        if str(entry.get("idle_animation") or "none").strip().lower() != "none":
            return True
    return False


def _has_visual(entry: dict[str, Any]) -> bool:
    if dynamic_display_overlay_entry(entry):
        return True
    if effective_graphic_source(entry):
        return True
    if bool(entry.get("background") or (entry.get("text") or entry.get("label") or "").strip()):
        return True
    return proposed_entry(entry) is not None


def apply_page_skin(
    deck: Any,
    page: dict[str, Any],
    config_dir: Path,
    global_bindings: dict[str, Any] | None = None,
    *,
    page_index: int = 0,
    live_text: dict[str, str] | None = None,
    redraw_id: int | None = None,
    redraw_reason: str | None = None,
    animation_frame: int | None = None,
    press_animation_start: dict[str, int] | None = None,
    current_tick: int = 0,
) -> None:
    """Synchronous: call via asyncio.to_thread; uses deck update lock.

    Every control with an image output is updated: bound controls show their graphic; unbound or
    non-visual ones are cleared to black so previous pages do not leave ghost images. Bindings
    come from ``page`` (``controls``), else ``global_bindings``. ``live_text`` maps binding
    storage keys (``p<page>:<id>`` / ``g:<id>``) to resolved display strings.
    """

    gb = global_bindings if isinstance(global_bindings, dict) else {}
    page_controls = page_bindings(page)

    model = device_model_of(deck)
    controls = drawable_control_ids(deck)
    controls_n = len(controls)
    log_prefix = f"apply_page_skin id={redraw_id}" if redraw_id is not None else "apply_page_skin"
    logger.debug(
        "%s reason=%r page=%r page_index=%s overlay_cache=%s controls=%s page_keys=%s global_keys=%s deck=%s",
        log_prefix,
        redraw_reason,
        page.get("name"),
        page_index,
        len(live_text) if live_text else 0,
        controls_n,
        list(page_controls.keys()),
        list(gb.keys()),
        model.id if model is not None else type(deck).__name__,
    )

    with deck:
        for control_id in controls:
            size = (model.image_size(control_id) if model is not None else None) or DEFAULT_KEY_SIZE
            base, sk = _entry_for_skin(page, gb, control_id, page_index)
            overlay = live_text.get(sk) if (live_text and sk is not None) else None
            # Only apply runtime overlay when this key still has a live message in config; otherwise
            # stale cache entries could overwrite a saved button after PUT until the next tick.
            # Do not replace with a blank overlay (e.g. before HTTP fetch); keep YAML text/icons.
            if overlay is not None and base is not None and dynamic_display_overlay_entry(base):
                entry = dict(base)
                if str(overlay).strip():
                    entry["text"] = overlay
            elif (
                overlay in ("playing", "paused")
                and base is not None
                and spotify_state_params_from_entry(base) is not None
            ):
                entry = spotify_state_entry(proposed_entry(base) or base, str(overlay))
            else:
                entry = base
            img: Image.Image | None = None
            if entry is not None and _has_visual(entry):
                press_elapsed = None
                if press_animation_start and control_id in press_animation_start:
                    press_elapsed = current_tick - press_animation_start[control_id]
                try:
                    img = render_tactile_key_image(
                        entry,
                        config_dir,
                        size=size,
                        animation_frame=animation_frame,
                        press_elapsed_frames=press_elapsed,
                    )
                except Exception:
                    logger.exception("Failed to render key graphics for %s", control_id)
                    img = None
                if img is None:
                    img = _blank_rgba(size)
            else:
                img = _blank_rgba(size)

            try:
                deck.set_image(control_id, img)
            except Exception:
                logger.exception("Failed to draw %s", control_id)

        _apply_leds(deck, page, gb, page_index)

        # Animation ticks (~10/s for GIF/video keys) use DEBUG; other redraws stay INFO.
        msg = f"{log_prefix} complete (drew {controls_n} controls)"
        if redraw_reason == "skin_animation":
            logger.debug(msg)
        else:
            logger.info(msg)
