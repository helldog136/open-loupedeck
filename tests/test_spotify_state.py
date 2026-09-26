"""Spotify play/pause keys: icon follows the polled playback state."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from open_loupedeck.live_message import (
    DEFAULT_ICON_PAUSED,
    DEFAULT_ICON_PLAYING,
    refresh_live_messages,
    spotify_state_entry,
)
from open_loupedeck.runtime_refs import AgentRuntimeRefs

KEY = {"action": {"type": "spotify.play_pause"}, "text": "Music"}


def test_icon_reflects_state():
    assert spotify_state_entry(KEY, "playing")["icon"] == DEFAULT_ICON_PLAYING == "lucide:pause"
    assert spotify_state_entry(KEY, "paused")["icon"] == DEFAULT_ICON_PAUSED == "lucide:play"
    assert spotify_state_entry(KEY, "playing")["text"] == "Music"


def test_custom_icons_and_explicit_image_are_respected():
    custom = {"action": {"type": "spotify.play_pause", "icon_playing": "lucide:square", "icon_paused": "lucide:music"}}
    assert spotify_state_entry(custom, "playing")["icon"] == "lucide:square"
    assert spotify_state_entry(custom, "paused")["icon"] == "lucide:music"
    with_image = {**KEY, "image": "library/images/x.png"}
    assert "icon" not in spotify_state_entry(with_image, "playing")


class _Resp:
    def __init__(self, status: int, body: dict[str, Any] | None = None) -> None:
        self.status_code = status
        self._body = body or {}

    def json(self) -> dict[str, Any]:
        return self._body


class _FakeSpotify:
    def __init__(self) -> None:
        self.response = _Resp(200, {"is_playing": True})

    def has_tokens(self) -> bool:
        return True

    async def api(self, client, method, path, **kw):
        assert (method, path) == ("GET", "/me/player")
        return self.response


def _refresh(runtime, raw):
    return asyncio.run(refresh_live_messages(raw, 0, runtime, None, logging.getLogger("t")))


def test_refresh_sets_playing_then_paused():
    raw = {"pages": [{"buttons": {"touch_0": KEY}}]}
    sm = _FakeSpotify()
    rt = AgentRuntimeRefs(spotify=sm)

    assert _refresh(rt, raw) is True
    assert rt.live_message_text["p0:touch_0"] == "playing"

    sm.response = _Resp(204)
    rt.spotify_last_fetch = 0.0  # poll again now
    assert _refresh(rt, raw) is True
    assert rt.live_message_text["p0:touch_0"] == "paused"


def test_unknown_state_leaves_the_key_untouched():
    raw = {"pages": [{"buttons": {"touch_0": KEY}}]}
    rt = AgentRuntimeRefs(spotify=None)
    assert _refresh(rt, raw) is False
    assert "p0:touch_0" not in rt.live_message_text
