"""Draw page images onto the connected device, through its backend and model descriptor."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from PIL import Image, ImageColor

from .button_render import DEFAULT_KEY_SIZE, effective_graphic_source, render_tactile_key_image
from .control_ids import is_page_scoped_control
from .devices.base import device_model_of
from .key_media_cache import raw_graphic_needs_skin_animation
from .live_message import (
    dynamic_display_overlay_entry,
    overlay_text_for_control,
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


def _apply_physical_button_leds(deck: Any, gb: dict[str, Any]) -> None:
    """Drive the RGB LEDs of the model's ``led_button`` controls (config ``button_color`` per ``btn_*``)."""

    model = device_model_of(deck)
    if model is None or not model.capabilities.button_led:
        return
    default_rgb = model.default_button_rgb or (0, 0, 0)
    for cid in model.led_button_ids():
        entry = _entry_for_control(gb, cid)
        rgb = default_rgb
        if isinstance(entry, dict):
            parsed = _rgb_from_button_color(entry.get("button_color"))
            if parsed is not None:
                rgb = parsed
        try:
            deck.set_button_color(cid, rgb)
        except Exception:
            logger.exception("set_button_color failed control_id=%s rgb=%s", cid, rgb)


def _blank_rgba(size: tuple[int, int]) -> Image.Image:
    return Image.new("RGBA", size, (0, 0, 0, 255))


def drawable_control_ids(deck: Any) -> list[str]:
    """All controls that take a key/strip bitmap on this device (canonical ids, redraw order).

    From the model descriptor. On the Live S that is only the 5×3 centre grid: its physical
    buttons have no display (painting them through the touch grid would wipe touch_0..3).
    """

    model = device_model_of(deck)
    return model.drawable_control_ids() if model is not None else []


def _entry_for_control(buttons: dict[str, Any], control_id: str) -> dict[str, Any] | None:
    if control_id == "strip_left":
        raw = buttons.get("strip_left") or buttons.get("left")
    elif control_id == "strip_right":
        raw = buttons.get("strip_right") or buttons.get("right")
    else:
        raw = buttons.get(control_id)
    return raw if isinstance(raw, dict) else None


def _entry_for_skin(
    global_buttons: dict[str, Any],
    page_buttons: dict[str, Any],
    control_id: str,
) -> dict[str, Any] | None:
    """Touch keys use ``page_buttons``; knobs, side buttons, and strips use ``global_buttons``."""

    if is_page_scoped_control(control_id):
        return _entry_for_control(page_buttons, control_id)
    return _entry_for_control(global_buttons, control_id)


def page_needs_animated_skin(
    deck: Any,
    page: dict[str, Any],
    global_buttons: dict[str, Any],
    config_dir: Path,
) -> bool:
    """True if any drawable key on this page needs periodic redraw: a video/multi-frame GIF, or a
    configured ``idle_animation`` (see ``button_render.py``)."""

    raw_buttons = page.get("buttons")
    page_buttons: dict[str, Any] = raw_buttons if isinstance(raw_buttons, dict) else {}
    gb = global_buttons if isinstance(global_buttons, dict) else {}
    for control_id in drawable_control_ids(deck):
        entry = _entry_for_skin(gb, page_buttons, control_id)
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
    global_buttons: dict[str, Any] | None = None,
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

    Every drawable key/strip slot is updated: assigned buttons show their graphic; unassigned or
    non-visual entries are cleared to black so previous pages do not leave ghost images.
    Knobs, side buttons, and strips use ``global_buttons``; touch cells use the current page.
    ``live_text`` maps storage keys (see ``overlay_text_for_control``) to resolved display strings.
    """

    raw_buttons = page.get("buttons")
    page_buttons: dict[str, Any] = raw_buttons if isinstance(raw_buttons, dict) else {}
    gb = global_buttons if isinstance(global_buttons, dict) else {}

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
        list(page_buttons.keys()),
        list(gb.keys()),
        model.id if model is not None else type(deck).__name__,
    )

    with deck:
        for control_id in controls:
            size = model.key_size_for(control_id) if model is not None else DEFAULT_KEY_SIZE
            base = _entry_for_skin(gb, page_buttons, control_id)
            overlay = overlay_text_for_control(control_id, page_index, live_text)
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
                deck.set_key_image(control_id, img)
            except Exception:
                logger.exception("Failed to draw %s", control_id)

        _apply_physical_button_leds(deck, gb)

        # Animation ticks (~10/s for GIF/video keys) use DEBUG; other redraws stay INFO.
        msg = f"{log_prefix} complete (drew {controls_n} controls)"
        if redraw_reason == "skin_animation":
            logger.debug(msg)
        else:
            logger.info(msg)
