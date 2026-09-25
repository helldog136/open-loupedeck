"""Twitch management: device-code login, token refresh, and twitch.* action -> Helix mapping."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import httpx

from open_loupedeck import twitch_api
from open_loupedeck.actions import ActionContext, run_actions
from open_loupedeck.twitch_api import TwitchManager, account_key

ACCOUNT = {"client_id": "cid123"}


def _run(coro):
    return asyncio.run(coro)


def _manager(tmp_path, handler) -> tuple[TwitchManager, httpx.AsyncClient]:
    mgr = TwitchManager(tmp_path / "twitch_tokens.json", lambda: [ACCOUNT])
    return mgr, httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_account_key_uses_label_to_separate_logins():
    assert account_key({"client_id": "a"}) == "a"
    assert account_key({"client_id": "a", "label": "bot"}) == "a|bot"


def test_device_flow_connects_and_stores_user(tmp_path):
    polls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        if url.endswith("/oauth2/device"):
            return httpx.Response(
                200,
                json={
                    "device_code": "dc",
                    "user_code": "ABCD",
                    "verification_uri": "https://www.twitch.tv/activate",
                    "expires_in": 600,
                    "interval": 5,
                },
            )
        if url.endswith("/oauth2/token"):
            polls["n"] += 1
            if polls["n"] == 1:
                return httpx.Response(400, json={"status": 400, "message": "authorization_pending"})
            return httpx.Response(200, json={"access_token": "at", "refresh_token": "rt", "expires_in": 14400})
        if url.endswith("/helix/users"):
            return httpx.Response(200, json={"data": [{"id": "42", "login": "helldog136"}]})
        raise AssertionError(url)

    async def go():
        mgr, client = _manager(tmp_path, handler)
        async with client:
            info = await mgr.start_device_flow(client, ACCOUNT)
            first = await mgr.poll_device_flow(client, ACCOUNT)
            second = await mgr.poll_device_flow(client, ACCOUNT)
        return mgr, info, first, second

    mgr, info, first, second = _run(go())
    assert info["user_code"] == "ABCD"
    assert first == {"status": "pending"}
    assert second == {"status": "connected", "login": "helldog136"}
    assert mgr.is_connected(ACCOUNT) and mgr.login_for(ACCOUNT) == "helldog136"
    mgr.disconnect(ACCOUNT)
    assert not mgr.is_connected(ACCOUNT)


def test_expired_token_is_refreshed_and_new_refresh_token_saved(tmp_path):
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        if url.endswith("/oauth2/token"):
            body = dict(x.split("=") for x in req.content.decode().split("&"))
            assert body["grant_type"] == "refresh_token" and body["refresh_token"] == "old-rt"
            return httpx.Response(200, json={"access_token": "new-at", "refresh_token": "new-rt", "expires_in": 14400})
        seen.append(req.headers["Authorization"])
        return httpx.Response(200, json={"data": []})

    async def go():
        mgr, client = _manager(tmp_path, handler)
        mgr._store(
            "cid123",
            {
                "access_token": "old-at",
                "refresh_token": "old-rt",
                "expires_at": time.time() - 5,
                "user_id": "42",
                "login": "x",
            },
        )
        async with client:
            await mgr.helix(client, ACCOUNT, "GET", "/streams")
        return mgr

    mgr = _run(go())
    assert seen == ["Bearer new-at"]
    assert json.loads((tmp_path / "twitch_tokens.json").read_text())["cid123"]["refresh_token"] == "new-rt"
    assert mgr.login_for(ACCOUNT) == "x"


class _FakeTwitch:
    def __init__(self, responses: dict[tuple[str, str], Any] | None = None) -> None:
        self.calls: list[tuple[str, str, dict[str, Any] | None, Any]] = []
        self.responses = responses or {}

    async def user_id(self, client, account):
        return "42"

    async def helix(self, client, account, method, path, *, params=None, json_body=None):
        self.calls.append((method, path, params, json_body))
        return self.responses.get((method, path), {})


def _ctx(fake, errors=None) -> ActionContext:
    return ActionContext(
        obs=None,
        http_client=None,
        log=logging.getLogger("t"),
        twitch_api=fake,
        twitch_accounts=[ACCOUNT],
        twitch_account=ACCOUNT,
        on_action_error=(lambda k, p, e: errors.append(e)) if errors is not None else None,
    )


def test_create_clip_and_commercial_hit_the_right_endpoints():
    fake = _FakeTwitch({("POST", "/clips"): {"data": [{"id": "c1", "edit_url": "https://clips.twitch.tv/c1/edit"}]}})
    _run(run_actions(_ctx(fake), [{"type": "twitch.create_clip"}, {"type": "twitch.start_commercial", "length": 60}]))
    assert fake.calls[0] == ("POST", "/clips", {"broadcaster_id": "42"}, None)
    assert fake.calls[1] == ("POST", "/channels/commercial", None, {"broadcaster_id": "42", "length": 60})


def test_commercial_rejects_invalid_length():
    fake, errors = _FakeTwitch(), []
    _run(run_actions(_ctx(fake, errors), [{"type": "twitch.start_commercial", "length": 45}]))
    assert fake.calls == [] and isinstance(errors[0], ValueError)


def test_chat_mode_toggle_reads_current_state_then_flips_it():
    fake = _FakeTwitch({("GET", "/chat/settings"): {"data": [{"slow_mode": False}]}})
    _run(run_actions(_ctx(fake), [{"type": "twitch.chat_mode", "setting": "slow", "state": "toggle", "duration": 10}]))
    method, path, params, body = fake.calls[1]
    assert (method, path) == ("PATCH", "/chat/settings")
    assert params == {"broadcaster_id": "42", "moderator_id": "42"}
    assert body == {"slow_mode": True, "slow_mode_wait_time": 10}


def test_chat_mode_off_sends_only_the_flag():
    fake = _FakeTwitch()
    _run(run_actions(_ctx(fake), [{"type": "twitch.chat_mode", "setting": "emote", "state": "off"}]))
    assert fake.calls == [
        ("PATCH", "/chat/settings", {"broadcaster_id": "42", "moderator_id": "42"}, {"emote_mode": False})
    ]


def test_raid_resolves_the_target_login_first():
    fake = _FakeTwitch({("GET", "/users"): {"data": [{"id": "99"}]}})
    _run(run_actions(_ctx(fake), [{"type": "twitch.raid", "channel": "@SomeStreamer"}]))
    assert fake.calls[0] == ("GET", "/users", {"login": "somestreamer"}, None)
    assert fake.calls[1] == ("POST", "/raids", {"from_broadcaster_id": "42", "to_broadcaster_id": "99"}, None)


def test_update_channel_needs_title_or_game():
    fake, errors = _FakeTwitch(), []
    _run(run_actions(_ctx(fake, errors), [{"type": "twitch.update_channel"}]))
    assert isinstance(errors[0], ValueError)


def test_builtin_client_id_constant_exists():
    assert isinstance(twitch_api.DEFAULT_CLIENT_ID, str)
