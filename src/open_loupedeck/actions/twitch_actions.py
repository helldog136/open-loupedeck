"""``twitch.*`` management actions: clips, ads, markers, channel info, chat, raids, shoutouts.

All act as the account's connected Twitch user (Services > Twitch > Connect) on that user's own
channel. Like every ``twitch.*`` action they run once per configured account.
"""

from __future__ import annotations

import asyncio
import logging
import webbrowser
from typing import Any

from .registry import ActionContext, register_action

logger = logging.getLogger(__name__)

COMMERCIAL_LENGTHS = (30, 60, 90, 120, 150, 180)

# setting name -> (Helix boolean field, optional (value field, default, min, max))
_CHAT_SETTINGS: dict[str, tuple[str, tuple[str, int, int, int] | None]] = {
    "emote": ("emote_mode", None),
    "subscribers": ("subscriber_mode", None),
    "unique": ("unique_chat_mode", None),
    "followers": ("follower_mode", ("follower_mode_duration", 0, 0, 129600)),  # minutes
    "slow": ("slow_mode", ("slow_mode_wait_time", 30, 3, 120)),  # seconds
}


def _mgr(ctx: ActionContext) -> Any:
    m = ctx.twitch_api
    if m is None:
        raise RuntimeError("Twitch is not available (agent not ready)")
    return m


def _account(ctx: ActionContext) -> dict[str, Any]:
    acct = ctx.twitch_account
    if acct is None:
        raise RuntimeError("No Twitch account configured (Services > Twitch)")
    return acct


async def _call(ctx: ActionContext, method: str, path: str, **kw: Any) -> Any:
    return await _mgr(ctx).helix(ctx.http_client, _account(ctx), method, path, **kw)


async def _me(ctx: ActionContext) -> str:
    uid = await _mgr(ctx).user_id(ctx.http_client, _account(ctx))
    if not uid:
        raise RuntimeError("Twitch user id unknown; reconnect the account in the web UI")
    return uid


async def _user_id_for_login(ctx: ActionContext, login: str) -> str:
    lg = str(login or "").strip().lstrip("@").lower()
    if not lg:
        raise ValueError("a Twitch channel name is required")
    data = await _call(ctx, "GET", "/users", params={"login": lg})
    rows = data.get("data") or []
    if not rows:
        raise RuntimeError(f"Twitch user {lg!r} not found")
    return str(rows[0]["id"])


def _flag(params: dict[str, Any], key: str) -> bool:
    return str(params.get(key, "")).strip().lower() in ("1", "true", "yes", "on")


@register_action("twitch.create_clip")
class TwitchCreateClip:
    """Clips the last moments of the live stream. Optional ``open`` opens the clip editor."""

    async def run(self, ctx: ActionContext, params: dict[str, Any]) -> None:
        me = await _me(ctx)
        data = await _call(ctx, "POST", "/clips", params={"broadcaster_id": me})
        rows = data.get("data") or []
        if not rows:
            raise RuntimeError("Twitch did not create a clip (is the channel live?)")
        edit_url = str(rows[0].get("edit_url") or "")
        logger.info("Twitch clip created: %s (edit: %s)", rows[0].get("id"), edit_url)
        if _flag(params, "open") and edit_url.startswith("https://"):
            await asyncio.to_thread(webbrowser.open, edit_url)


@register_action("twitch.start_commercial")
class TwitchStartCommercial:
    async def run(self, ctx: ActionContext, params: dict[str, Any]) -> None:
        length = int(float(params.get("length") or 30))
        if length not in COMMERCIAL_LENGTHS:
            raise ValueError(f"length must be one of {COMMERCIAL_LENGTHS}")
        me = await _me(ctx)
        data = await _call(ctx, "POST", "/channels/commercial", json_body={"broadcaster_id": me, "length": length})
        rows = data.get("data") or []
        msg = str(rows[0].get("message") or "").strip() if rows else ""
        if msg:
            raise RuntimeError(f"Twitch commercial: {msg}")


@register_action("twitch.snooze_ad")
class TwitchSnoozeAd:
    """Pushes the next scheduled ad back by 5 minutes (limited snoozes per period)."""

    async def run(self, ctx: ActionContext, params: dict[str, Any]) -> None:
        await _call(ctx, "POST", "/channels/ads/schedule/snooze", params={"broadcaster_id": await _me(ctx)})


@register_action("twitch.create_marker")
class TwitchCreateMarker:
    async def run(self, ctx: ActionContext, params: dict[str, Any]) -> None:
        body: dict[str, Any] = {"user_id": await _me(ctx)}
        desc = str(params.get("description") or "").strip()
        if desc:
            body["description"] = desc[:140]
        await _call(ctx, "POST", "/streams/markers", json_body=body)


@register_action("twitch.update_channel")
class TwitchUpdateChannel:
    """Set the stream title and/or category (game looked up by exact name)."""

    async def run(self, ctx: ActionContext, params: dict[str, Any]) -> None:
        body: dict[str, Any] = {}
        title = str(params.get("title") or "").strip()
        if title:
            body["title"] = title[:140]
        game = str(params.get("game") or "").strip()
        if game:
            data = await _call(ctx, "GET", "/games", params={"name": game})
            rows = data.get("data") or []
            if not rows:
                raise RuntimeError(f"Twitch category {game!r} not found")
            body["game_id"] = str(rows[0]["id"])
        if not body:
            raise ValueError("twitch.update_channel requires 'title' and/or 'game'")
        await _call(ctx, "PATCH", "/channels", params={"broadcaster_id": await _me(ctx)}, json_body=body)


@register_action("twitch.chat_mode")
class TwitchChatMode:
    """Turn a chat restriction on/off/toggle: emote-only, followers-only, slow, subs-only, unique."""

    async def run(self, ctx: ActionContext, params: dict[str, Any]) -> None:
        setting = str(params.get("setting") or "").strip().lower()
        if setting not in _CHAT_SETTINGS:
            raise ValueError(f"setting must be one of {sorted(_CHAT_SETTINGS)}")
        state = str(params.get("state") or "toggle").strip().lower()
        if state not in ("on", "off", "toggle"):
            raise ValueError("state must be on, off or toggle")
        field, extra = _CHAT_SETTINGS[setting]
        me = await _me(ctx)
        q = {"broadcaster_id": me, "moderator_id": me}
        if state == "toggle":
            cur = await _call(ctx, "GET", "/chat/settings", params=q)
            rows = cur.get("data") or []
            enabled = not bool(rows[0].get(field)) if rows else True
        else:
            enabled = state == "on"
        body: dict[str, Any] = {field: enabled}
        if enabled and extra is not None:
            value_field, default, lo, hi = extra
            raw = params.get("duration")
            value = default if raw in (None, "") else int(float(raw))
            body[value_field] = max(lo, min(hi, value))
        await _call(ctx, "PATCH", "/chat/settings", params=q, json_body=body)


@register_action("twitch.announce")
class TwitchAnnounce:
    async def run(self, ctx: ActionContext, params: dict[str, Any]) -> None:
        msg = str(params.get("message") or "").strip()
        if not msg:
            raise ValueError("twitch.announce requires 'message'")
        me = await _me(ctx)
        body: dict[str, Any] = {"message": msg[:500]}
        color = str(params.get("color") or "").strip().lower()
        if color and color != "primary":
            body["color"] = color
        await _call(
            ctx, "POST", "/chat/announcements", params={"broadcaster_id": me, "moderator_id": me}, json_body=body
        )


@register_action("twitch.send_chat")
class TwitchSendChat:
    async def run(self, ctx: ActionContext, params: dict[str, Any]) -> None:
        msg = str(params.get("message") or "").strip()
        if not msg:
            raise ValueError("twitch.send_chat requires 'message'")
        me = await _me(ctx)
        data = await _call(
            ctx, "POST", "/chat/messages", json_body={"broadcaster_id": me, "sender_id": me, "message": msg[:500]}
        )
        rows = data.get("data") or []
        if rows and rows[0].get("is_sent") is False:
            reason = (rows[0].get("drop_reason") or {}).get("message") or "message dropped"
            raise RuntimeError(f"Twitch chat: {reason}")


@register_action("twitch.clear_chat")
class TwitchClearChat:
    async def run(self, ctx: ActionContext, params: dict[str, Any]) -> None:
        me = await _me(ctx)
        await _call(ctx, "DELETE", "/chat/messages", params={"broadcaster_id": me, "moderator_id": me})


@register_action("twitch.raid")
class TwitchRaid:
    async def run(self, ctx: ActionContext, params: dict[str, Any]) -> None:
        target = await _user_id_for_login(ctx, params.get("channel") or params.get("login") or "")
        await _call(ctx, "POST", "/raids", params={"from_broadcaster_id": await _me(ctx), "to_broadcaster_id": target})


@register_action("twitch.cancel_raid")
class TwitchCancelRaid:
    async def run(self, ctx: ActionContext, params: dict[str, Any]) -> None:
        await _call(ctx, "DELETE", "/raids", params={"broadcaster_id": await _me(ctx)})


@register_action("twitch.shoutout")
class TwitchShoutout:
    async def run(self, ctx: ActionContext, params: dict[str, Any]) -> None:
        target = await _user_id_for_login(ctx, params.get("channel") or params.get("login") or "")
        me = await _me(ctx)
        await _call(
            ctx,
            "POST",
            "/chat/shoutouts",
            params={"from_broadcaster_id": me, "to_broadcaster_id": target, "moderator_id": me},
        )
