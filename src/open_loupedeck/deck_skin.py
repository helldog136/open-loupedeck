"""Draw page images onto Loupedeck Live or Live S (different center grid geometry)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from PIL import Image, ImageColor

from .button_render import effective_graphic_source, key_size_for_control, render_tactile_key_image
from .control_ids import is_page_scoped_control
from .hardware.live_s_device import LoupedeckLiveS
from .key_media_cache import raw_graphic_needs_skin_animation
from .live_message import dynamic_display_overlay_entry, overlay_text_for_control

logger = logging.getLogger(__name__)

LIVE_S_MAX_TOUCH = 14

# Loupedeck protocol names for SET_COLOR on the four Live S physical buttons.
#
# Upstream foxxyz/loupedeck maps the four Live S LEDs to button ids 0–3, i.e. BUTTONS keys
# 0x07–0x0A (values 0, 1, 2, 3). python-loupedeck uses string names: 0x07 is "circle", then
# "1", "2", "3" for 0x08–0x0A. Do *not* use "1"–"4" (0x08–0x0B): that is the middle four of
# the eight Loupedeck Live side keys and shifts every Live S color to the wrong LED.
LIVE_S_PHYSICAL_BUTTON_LED_MAP: dict[str, str] = {
    "btn_circle": "circle",
    "btn_1": "1",
    "btn_2": "2",
    "btn_3": "3",
}
DEFAULT_LIVE_S_LED_RGB: tuple[int, int, int] = (32, 32, 40)


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


def _apply_live_s_physical_button_leds(deck: Any, gb: dict[str, Any]) -> None:
    """Drive RGB LEDs for the four hardware buttons (config ``button_color`` per ``btn_*``)."""

    if not isinstance(deck, LoupedeckLiveS):
        return
    for cid, proto_name in LIVE_S_PHYSICAL_BUTTON_LED_MAP.items():
        entry = _entry_for_control(gb, cid)
        rgb = DEFAULT_LIVE_S_LED_RGB
        if isinstance(entry, dict):
            parsed = _rgb_from_button_color(entry.get("button_color"))
            if parsed is not None:
                rgb = parsed
        try:
            deck.set_button_color(proto_name, rgb)
        except Exception:
            logger.exception(
                "set_button_color failed control_id=%s protocol_name=%s rgb=%s",
                cid,
                proto_name,
                rgb,
            )


def _blank_rgba(size: tuple[int, int]) -> Image.Image:
    return Image.new("RGBA", size, (0, 0, 0, 255))


def drawable_control_ids(deck: Any) -> list[str]:
    """All controls that support key/strip bitmaps for this hardware (canonical ids)."""

    if isinstance(deck, LoupedeckLiveS):
        # Only the 5×3 center grid (indices 0..14). Do not include btn_circle / btn_1..btn_3 here: they map to the
        # same set_key_image indices as touch_0..touch_3 and would paint after them, wiping those
        # cells with black when a button slot is empty. Physical side buttons need separate
        # framebuffer coordinates (not the touch grid); until those exist, skip hardware bitmaps for btn_*.
        return [f"touch_{i}" for i in range(LIVE_S_MAX_TOUCH + 1)]
    ids = [f"touch_{i}" for i in range(12)]
    ids += [f"btn_{i}" for i in range(1, 8)]
    ids += ["strip_left", "strip_right"]
    return ids


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
    return bool(entry.get("background") or (entry.get("text") or entry.get("label") or "").strip())


def _apply_rgba_to_control(deck: Any, control_id: str, img: Image.Image) -> None:
    if control_id.startswith("touch_"):
        n = int(control_id.split("_", 1)[1])
        if isinstance(deck, LoupedeckLiveS):
            if n > LIVE_S_MAX_TOUCH:
                logger.warning(
                    "Live S has touch keys 0..%s only; skipping %s",
                    LIVE_S_MAX_TOUCH,
                    control_id,
                )
                return
        else:
            if n > 11:
                logger.warning(
                    "Loupedeck Live has touch keys 0..11 only; skipping %s",
                    control_id,
                )
                return
        deck.set_key_image(str(n), img)
    elif control_id.startswith("btn_"):
        rest = control_id[4:]
        if rest == "circle":
            logger.debug("Skipping image for btn_circle (not supported by set_key_image)")
            return
        deck.set_key_image(rest, img)
    elif control_id in ("strip_left", "left"):
        if isinstance(deck, LoupedeckLiveS):
            logger.debug("Live S has no side strip displays; skip %s", control_id)
            return
        deck.set_left_image(img)
    elif control_id in ("strip_right", "right"):
        if isinstance(deck, LoupedeckLiveS):
            logger.debug("Live S has no side strip displays; skip %s", control_id)
            return
        deck.set_right_image(img)
    else:
        logger.debug("No drawable target for %s (knobs use colors only)", control_id)


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

    controls_n = len(drawable_control_ids(deck))
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
        type(deck).__name__,
    )

    with deck:
        for control_id in drawable_control_ids(deck):
            size = key_size_for_control(control_id)
            base = _entry_for_skin(gb, page_buttons, control_id)
            overlay = overlay_text_for_control(control_id, page_index, live_text)
            # Only apply runtime overlay when this key still has a live message in config; otherwise
            # stale cache entries could overwrite a saved button after PUT until the next tick.
            # Do not replace with a blank overlay (e.g. before HTTP fetch); keep YAML text/icons.
            if overlay is not None and base is not None and dynamic_display_overlay_entry(base):
                entry = dict(base)
                if str(overlay).strip():
                    entry["text"] = overlay
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
                _apply_rgba_to_control(deck, control_id, img)
            except Exception:
                logger.exception("Failed to draw %s", control_id)

        _apply_live_s_physical_button_leds(deck, gb)

        # Animation ticks (~10/s for GIF/video keys) use DEBUG; other redraws stay INFO.
        msg = f"{log_prefix} complete (drew {controls_n} controls)"
        if redraw_reason == "skin_animation":
            logger.debug(msg)
        else:
            logger.info(msg)
