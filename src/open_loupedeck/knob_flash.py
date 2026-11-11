"""Brief feedback text on the touch key next to an encoder (knobs have no screen of their own).

Drawn after a knob turn / push ("Volume +5") or, for legacy ``knob_pages``, after cycling a knob
page. Rapid turns re-draw the text and push back the restore: only the latest flash on a key
restores the skin, so the text does not flicker while the knob keeps turning.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from .button_render import DEFAULT_KEY_SIZE, render_tactile_key_image
from .devices.base import device_model_of
from .devices.model import DeviceModel
from .knob_pages import feedback_duration_sec, feedback_key_for_knob

logger = logging.getLogger(__name__)

FEEDBACK_ENTRY_BASE = {"background": "#1a1f2e", "text_color": "#e8ecf4"}

# display control id -> generation of the latest flash drawn on it.
_generation: dict[str, int] = {}


def _single_line_label(text: str, max_len: int = 80) -> str:
    s = " ".join((text or "").split())
    return s[:max_len] if s else ""


async def flash_knob_feedback(
    deck: Any,
    config_dir: Path,
    raw_config: dict[str, Any],
    device_model: DeviceModel | str | None,
    knob_id: str,
    text: str,
    redraw_skin: Callable[..., Awaitable[None]],
    duration_sec: float | None = None,
) -> str | None:
    """Draw ``text`` on the display control mapped to ``knob_id``, then restore the skin.

    The control is the knob's ``feedback_key`` on the device's model (``device_model`` when the
    backend has none). ``duration_sec`` overrides the global ``knob_page_feedback.duration_sec``;
    0 disables the feedback. Returns the control id drawn on (``None`` if nothing was drawn).
    """

    model = device_model_of(deck) or device_model
    touch_cid = feedback_key_for_knob(knob_id, model)
    if touch_cid is None:
        return None
    line = _single_line_label(text)
    if not line:
        return None
    duration = feedback_duration_sec(raw_config) if duration_sec is None else float(duration_sec)
    if duration <= 0:
        return None

    gen = _generation.get(touch_cid, 0) + 1
    _generation[touch_cid] = gen

    dm = device_model_of(deck)
    size = (dm.image_size(touch_cid) if dm is not None else None) or DEFAULT_KEY_SIZE

    def _draw() -> None:
        with deck:
            im = render_tactile_key_image({**FEEDBACK_ENTRY_BASE, "text": line}, config_dir, size=size)
            if im is not None:
                deck.set_image(touch_cid, im)

    try:
        await asyncio.to_thread(_draw)
    except Exception:
        logger.exception("Knob feedback draw failed")
        return None

    await asyncio.sleep(duration)
    if _generation.get(touch_cid) != gen:
        return touch_cid  # a newer flash owns the key and will restore it

    try:
        await redraw_skin("knob_feedback_restore")
    except Exception:
        logger.exception("redraw_skin after knob feedback failed")
    return touch_cid


async def flash_knob_page_name(
    deck: Any,
    config_dir: Path,
    raw_config: dict[str, Any],
    device_model: DeviceModel | str | None,
    knob_id: str,
    page_name: str,
    redraw_skin: Callable[..., Awaitable[None]],
) -> None:
    """Legacy ``knob_pages``: show the knob page name after a push cycled it."""

    await flash_knob_feedback(deck, config_dir, raw_config, device_model, knob_id, page_name, redraw_skin)
