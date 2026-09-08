"""Spotify playback actions (requires Premium + active Spotify Connect device for most calls)."""

from __future__ import annotations

from typing import Any

import httpx

from .registry import ActionContext, register_action


def _require_spotify(ctx: ActionContext):
    sm = ctx.spotify
    if sm is None:
        raise RuntimeError("Spotify is not available (internal error)")
    if not sm.is_configured():
        raise RuntimeError("Spotify is not configured; set spotify.client_id and redirect_uri in config")
    if not sm.has_tokens():
        raise RuntimeError("Spotify is not connected; open the web UI and click Connect with Spotify")
    return sm


def _optional_device(params: dict[str, Any]) -> str | None:
    d = params.get("device_id")
    return str(d).strip() if d else None


@register_action("spotify.play_pause")
class SpotifyPlayPause:
    async def run(self, ctx: ActionContext, params: dict[str, Any]) -> None:
        sm = _require_spotify(ctx)
        client: httpx.AsyncClient = ctx.http_client
        await sm.play_pause(client, _optional_device(params))


@register_action("spotify.next")
class SpotifyNext:
    async def run(self, ctx: ActionContext, params: dict[str, Any]) -> None:
        sm = _require_spotify(ctx)
        client: httpx.AsyncClient = ctx.http_client
        await sm.next_track(client, _optional_device(params))


@register_action("spotify.previous")
class SpotifyPrevious:
    async def run(self, ctx: ActionContext, params: dict[str, Any]) -> None:
        sm = _require_spotify(ctx)
        client: httpx.AsyncClient = ctx.http_client
        await sm.previous_track(client, _optional_device(params))


@register_action("spotify.volume_set")
class SpotifyVolumeSet:
    async def run(self, ctx: ActionContext, params: dict[str, Any]) -> None:
        raw = params.get("percent")
        if raw is None:
            raw = params.get("volume")
        if raw is None:
            raise ValueError("spotify.volume_set requires percent (0–100)")
        sm = _require_spotify(ctx)
        client: httpx.AsyncClient = ctx.http_client
        await sm.set_volume(client, int(float(raw)), _optional_device(params))


@register_action("spotify.volume_delta")
class SpotifyVolumeDelta:
    async def run(self, ctx: ActionContext, params: dict[str, Any]) -> None:
        raw = params.get("delta") if params.get("delta") is not None else params.get("step")
        if raw is None:
            raise ValueError("spotify.volume_delta requires delta (e.g. 5 or -5)")
        delta = int(float(raw))
        if delta == 0:
            return
        sm = _require_spotify(ctx)
        client: httpx.AsyncClient = ctx.http_client
        r = await sm.api(client, "GET", "/me/player")
        if r.status_code == 204:
            raise RuntimeError("No active Spotify player; open Spotify on a device and try again")
        if r.status_code != 200:
            raise RuntimeError(f"Spotify player state failed ({r.status_code})")
        st = r.json()
        dev = st.get("device") or {}
        cur = int(dev.get("volume_percent") or 0)
        new_v = max(0, min(100, cur + delta))
        await sm.set_volume(client, new_v, _optional_device(params))


@register_action("spotify.play_playlist")
class SpotifyPlayPlaylist:
    async def run(self, ctx: ActionContext, params: dict[str, Any]) -> None:
        pl = params.get("playlist") or params.get("playlist_uri") or params.get("uri")
        if not pl:
            raise ValueError(
                "spotify.play_playlist requires playlist (id, spotify:playlist:…, or open.spotify.com URL)"
            )
        sm = _require_spotify(ctx)
        client: httpx.AsyncClient = ctx.http_client
        await sm.play_playlist(client, str(pl), _optional_device(params))
