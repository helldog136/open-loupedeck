"""
Loupedeck Live S: 5×3 touch grid (15 keys), center display 480×270, two left knobs, four buttons.

Protocol matches upstream python-loupedeck-live, but touch/key geometry differs from Loupedeck Live.
See foxxyz/loupedeck LoupedeckLiveS (USB VID 0x2ec2, PID 0x0006).
"""

from __future__ import annotations

import logging
import math
from datetime import datetime
from typing import Any

from Loupedeck.Devices.LoupedeckLive import (
    BIG_ENDIAN,
    CALLBACK_KEYWORD,
    DISPLAYS,
    HEADERS,
    KW_CENTER,
    KW_HEIGHT,
    KW_ID,
    KW_LEFT,
    KW_OFFSET,
    KW_RIGHT,
    KW_WIDTH,
    LoupedeckLive,
)
from Loupedeck.ImageHelpers import PILHelper

logger = logging.getLogger(__name__)

# Live S touch grid (matches foxxyz/loupedeck)
LIVE_S_VISIBLE_X0 = 15
LIVE_S_VISIBLE_X1 = 465
LIVE_S_COLUMNS = 5
LIVE_S_ROWS = 3
KEY_PX = 90
LIVE_S_MAX_KEY = LIVE_S_COLUMNS * LIVE_S_ROWS - 1  # 14


class LoupedeckLiveS(LoupedeckLive):
    """Same serial/WebSocket handshake as Live; different touch mapping and draw offsets."""

    DECK_TYPE = "LoupedeckLiveS"

    def on_touch(self, buff: bytearray, event=CALLBACK_KEYWORD.TOUCH_MOVE.value):
        x = int.from_bytes(buff[1:3], BIG_ENDIAN)
        y = int.from_bytes(buff[3:5], BIG_ENDIAN)
        idx = buff[5]

        screen = KW_CENTER
        key = None
        if LIVE_S_VISIBLE_X0 <= x < LIVE_S_VISIBLE_X1:
            column = math.floor((x - LIVE_S_VISIBLE_X0) / KEY_PX)
            row = math.floor(y / KEY_PX)
            if 0 <= column < LIVE_S_COLUMNS and 0 <= row < LIVE_S_ROWS:
                key = row * LIVE_S_COLUMNS + column
        elif x < LIVE_S_VISIBLE_X0:
            screen = KW_LEFT
        elif x >= LIVE_S_VISIBLE_X1:
            screen = KW_RIGHT

        touch = {
            CALLBACK_KEYWORD.IDENTIFIER.value: idx,
            CALLBACK_KEYWORD.ACTION.value: event,
            CALLBACK_KEYWORD.SCREEN.value: screen,
            CALLBACK_KEYWORD.KEY.value: key,
            CALLBACK_KEYWORD.X.value: x,
            CALLBACK_KEYWORD.Y.value: y,
            CALLBACK_KEYWORD.TIMESTAMP.value: datetime.now().astimezone().timestamp(),
        }
        if event == "touchmove":
            if idx not in self.touches:
                touch["action"] = "touchstart"
                self.touches[idx] = touch
        else:
            del self.touches[idx]

        if self.callback:
            self.callback(self, touch)

    def draw_buffer(
        self,
        buff,
        display: str,
        width: int | None = None,
        height: int | None = None,
        x: int = 0,
        y: int = 0,
        auto_refresh: bool = True,
    ):
        """Center framebuffer is 480×270 with no +60 horizontal offset (unlike Loupedeck Live)."""

        if display == KW_CENTER:
            display_info = {
                KW_ID: DISPLAYS[KW_CENTER][KW_ID],
                KW_WIDTH: 480,
                KW_HEIGHT: 270,
                KW_OFFSET: 0,
            }
            xoffset = 0
        else:
            display_info = DISPLAYS[display]
            t = display_info[KW_OFFSET]
            xoffset = int.from_bytes(t) if type(t) is bytes else int(t)

        x = x + xoffset
        loc_width: int = int(display_info[KW_WIDTH]) if width is None else width
        loc_height: int = int(display_info[KW_HEIGHT]) if height is None else height
        expected: int = loc_width * loc_height * 2
        if len(buff) != expected:
            logger.error(
                "draw_buffer Live S: display %s invalid buffer %s, expected %s",
                display,
                len(buff),
                expected,
            )
            return

        header = x.to_bytes(2, BIG_ENDIAN)
        header = header + y.to_bytes(2, BIG_ENDIAN)
        header = header + loc_width.to_bytes(2, BIG_ENDIAN)
        header = header + loc_height.to_bytes(2, BIG_ENDIAN)
        payload = display_info[KW_ID] + header + buff
        self.do_action(HEADERS["WRITE_FRAMEBUFF"], payload, track=True)
        if auto_refresh:
            self.refresh(display)

    def set_key_image(self, idx: str, image: Any) -> None:
        """Draw a 90×90 key at indices 0..14 (5×3)."""

        if idx in (KW_LEFT, KW_RIGHT):
            logger.warning("Loupedeck Live S has no left/right strip images; use center keys only")
            return
        try:
            loc_idx = int(idx)
        except ValueError:
            logger.warning("set_key_image Live S: invalid key %r", idx)
            return
        if loc_idx < 0 or loc_idx > LIVE_S_MAX_KEY:
            logger.warning("set_key_image Live S: key %s out of 0..%s", loc_idx, LIVE_S_MAX_KEY)
            return

        x = LIVE_S_VISIBLE_X0 + (loc_idx % LIVE_S_COLUMNS) * KEY_PX
        y = math.floor(loc_idx / LIVE_S_COLUMNS) * KEY_PX
        buff = PILHelper.to_native_format(KW_CENTER, image)
        self.draw_buffer(
            buff,
            display=KW_CENTER,
            width=90,
            height=90,
            x=x,
            y=y,
            auto_refresh=True,
        )

    def set_left_image(self, image: Any) -> None:
        logger.warning("Loupedeck Live S: set_left_image is not used on this model")

    def set_right_image(self, image: Any) -> None:
        logger.warning("Loupedeck Live S: set_right_image is not used on this model")
