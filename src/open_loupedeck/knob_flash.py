"""Brief page-name overlay on one touch key when an encoder’s knob page is cycled."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from .button_render import render_tactile_key_image
from .knob_pages import feedback_duration_sec, feedback_touch_key_for_knob_page_name

logger = logging.getLogger(__name__)


def _touch_index(control_id: str) -> int | None:
    if not control_id.startswith("touch_"):
        return None
    try:
        return int(control_id.split("_", 1)[1])
    except ValueError:
        return None


def _single_line_label(text: str, max_len: int = 80) -> str:
    s = " ".join((text or "").split())
    return s[:max_len] if s else ""


async def flash_knob_page_name(
    deck: Any,
    config_dir: Path,
    raw_config: dict[str, Any],
    device_model: str,
    knob_id: str,
    page_name: str,
    redraw_skin: Callable[..., Awaitable[None]],
) -> None:
    """Draw ``page_name`` on the touch key mapped to this knob, then restore the skin."""

    touch_cid = feedback_touch_key_for_knob_page_name(knob_id, device_model)
    if touch_cid is None:
        return
    n = _touch_index(touch_cid)
    if n is None:
        return

    line = _single_line_label(page_name)
    if not line:
        return

    duration = feedback_duration_sec(raw_config)

    base_entry = {
        "background": "#1a1f2e",
        "text_color": "#e8ecf4",
    }

    def _draw() -> None:
        with deck:
            e1 = {**base_entry, "text": line}
            im1 = render_tactile_key_image(e1, config_dir, size=(90, 90))
            if im1 is not None:
                deck.set_key_image(str(n), im1)

    try:
        await asyncio.to_thread(_draw)
    except Exception:
        logger.exception("Knob page feedback draw failed")
        return

    await asyncio.sleep(duration)

    try:
        await redraw_skin("knob_feedback_restore")
    except Exception:
        logger.exception("redraw_skin after knob feedback failed")
