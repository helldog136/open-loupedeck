"""Spotify player commands recover from "no active device" by activating one."""

from __future__ import annotations

import asyncio
import json
import time

import httpx

from open_loupedeck.spotify_client import SpotifyManager

DEVICES = {
    "devices": [
        {"id": "phone", "name": "Phone", "type": "Smartphone", "is_active": False, "is_restricted": False},
        {"id": "pc", "name": "PC", "type": "Computer", "is_active": False, "is_restricted": False},
        {"id": "tv", "name": "TV", "type": "TV", "is_active": False, "is_restricted": True},
    ]
}


def _manager(tmp_path) -> SpotifyManager:
    path = tmp_path / "spotify_tokens.json"
    path.write_text(json.dumps({"access_token": "at", "refresh_token": "rt", "expires_at": time.time() + 3600}))
    return SpotifyManager(path, dict)


def _run(mgr, handler, fn):
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await fn(mgr, client)

    asyncio.run(go())


def test_play_pause_with_no_player_activates_a_computer_and_plays(tmp_path):
    calls: list[tuple[str, str, dict]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content) if req.content else {}
        calls.append((req.method, req.url.path, body))
        if req.url.path == "/v1/me/player" and req.method == "GET":
            return httpx.Response(204)
        if req.url.path == "/v1/me/player/devices":
            return httpx.Response(200, json=DEVICES)
        return httpx.Response(204)

    async def fn(mgr, client):
        await mgr.play_pause(client)

    _run(_manager(tmp_path), handler, fn)
    assert ("PUT", "/v1/me/player", {"device_ids": ["pc"], "play": True}) in calls


def test_next_on_no_active_device_transfers_then_retries(tmp_path):
    sent: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        sent.append(f"{req.method} {req.url.path}")
        if req.url.path == "/v1/me/player/next":
            first = sent.count("POST /v1/me/player/next") == 1
            if first:
                return httpx.Response(
                    404,
                    json={"error": {"status": 404, "message": "No active device found", "reason": "NO_ACTIVE_DEVICE"}},
                )
            return httpx.Response(204)
        if req.url.path == "/v1/me/player/devices":
            return httpx.Response(200, json=DEVICES)
        return httpx.Response(204)

    _run(_manager(tmp_path), handler, lambda mgr, client: mgr.next_track(client))
    assert sent == [
        "POST /v1/me/player/next",
        "GET /v1/me/player/devices",
        "PUT /v1/me/player",
        "POST /v1/me/player/next",
    ]


def test_no_devices_at_all_gives_a_clear_error(tmp_path):
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/v1/me/player/devices":
            return httpx.Response(200, json={"devices": []})
        return httpx.Response(404, json={"error": {"reason": "NO_ACTIVE_DEVICE"}})

    async def fn(mgr, client):
        try:
            await mgr.next_track(client)
            raise AssertionError("expected RuntimeError")
        except RuntimeError as e:
            assert "No Spotify device found" in str(e)

    _run(_manager(tmp_path), handler, fn)
