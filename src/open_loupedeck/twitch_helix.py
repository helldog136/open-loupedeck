"""Twitch Helix API helpers for stream status (client credentials or static token)."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)

TWITCH_TOKEN_URL = "https://id.twitch.tv/oauth2/token"
TWITCH_HELIX = "https://api.twitch.tv/helix"


def normalize_twitch_login_params(raw: dict[str, Any]) -> str:
    v = raw.get("login") or raw.get("channel") or raw.get("user_login") or ""
    return str(v).strip().lower()


def _format_uptime_from_started(started_at: str | None) -> str:
    if not started_at:
        return "—"
    try:
        s = str(started_at).replace("Z", "+00:00")
        start = datetime.fromisoformat(s)
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - start.astimezone(timezone.utc)
        sec = max(0, int(delta.total_seconds()))
        h, r = divmod(sec, 3600)
        m, s2 = divmod(r, 60)
        if h > 0:
            return f"{h}:{m:02d}:{s2:02d}"
        return f"{m}:{s2:02d}"
    except Exception:
        logger.debug("twitch: bad started_at %r", started_at, exc_info=True)
        return "—"


def offline_fields(login: str) -> dict[str, str]:
    lg = login or "—"
    return {
        "twitch_login": lg,
        "twitch_live": "no",
        "twitch_status": "Offline",
        "twitch_viewers": "0",
        "twitch_title": "—",
        "twitch_game": "—",
        "twitch_uptime": "—",
    }


def live_fields(login: str, stream: dict[str, Any]) -> dict[str, str]:
    title = str(stream.get("title") or "").strip() or "—"
    game = str(stream.get("game_name") or "").strip() or "—"
    viewers = stream.get("viewer_count")
    try:
        vc = str(int(viewers)) if viewers is not None else "0"
    except (TypeError, ValueError):
        vc = "0"
    uptime = _format_uptime_from_started(stream.get("started_at"))
    lg = str(stream.get("user_login") or login or "").strip() or login
    return {
        "twitch_login": lg,
        "twitch_live": "yes",
        "twitch_status": "LIVE",
        "twitch_viewers": vc,
        "twitch_title": title[:120],
        "twitch_game": game[:80],
        "twitch_uptime": uptime,
    }


async def _ensure_bearer(
    client: httpx.AsyncClient,
    twitch_cfg: dict[str, Any],
    runtime: Any,
) -> str | None:
    """Return Bearer token, or None if Twitch is not configured."""

    if not isinstance(twitch_cfg, dict):
        return None
    explicit = str(twitch_cfg.get("access_token") or "").strip()
    if explicit:
        return explicit

    client_id = str(twitch_cfg.get("client_id") or "").strip()
    client_secret = str(twitch_cfg.get("client_secret") or "").strip()
    if not client_id or not client_secret:
        return None

    now = time.monotonic()
    tok = getattr(runtime, "twitch_bearer_token", "") or ""
    exp = float(getattr(runtime, "twitch_bearer_expires_at", 0.0) or 0.0)
    if tok and now < exp:
        return tok

    r = await client.post(
        TWITCH_TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "client_credentials",
        },
        timeout=20.0,
    )
    r.raise_for_status()
    data = r.json()
    access = str(data.get("access_token") or "")
    if not access:
        raise RuntimeError("Twitch token response missing access_token")
    expires_in = float(data.get("expires_in") or 3600)
    # Refresh a bit before expiry
    runtime.twitch_bearer_token = access
    runtime.twitch_bearer_expires_at = now + max(60.0, expires_in * 0.85)
    return access


async def fetch_stream_fields_for_login(
    client: httpx.AsyncClient,
    raw: dict[str, Any],
    runtime: Any,
    login: str,
) -> dict[str, str]:
    """Fetch Helix stream info; returns template fields (offline if not live or on error)."""

    lg = (login or "").strip().lower()
    if not lg:
        return offline_fields("—")

    tw_raw = raw.get("twitch")
    if isinstance(tw_raw, list):
        # Multi-account config: for Helix stream status we only need *an* app token.
        twitch_cfg = next((d for d in tw_raw if isinstance(d, dict) and d), {})
    elif isinstance(tw_raw, dict):
        twitch_cfg = tw_raw
    else:
        twitch_cfg = {}
    try:
        token = await _ensure_bearer(client, twitch_cfg, runtime)
    except Exception:
        logger.warning("Twitch auth failed", exc_info=True)
        return offline_fields(lg)

    if not token:
        logger.warning(
            "Twitch not configured: set twitch.client_id + twitch.client_secret "
            "(app token) or twitch.access_token in config"
        )
        return offline_fields(lg)

    client_id = str(twitch_cfg.get("client_id") or "").strip()
    if not client_id:
        logger.warning("twitch.client_id is required for Helix (even when using access_token)")
        return offline_fields(lg)

    headers = {
        "Authorization": f"Bearer {token}",
        "Client-Id": client_id,
    }
    url = f"{TWITCH_HELIX}/streams"
    try:
        r = await client.get(url, headers=headers, params={"user_login": lg}, timeout=15.0)
        r.raise_for_status()
        payload = r.json()
    except Exception:
        logger.debug("Twitch Helix streams fetch failed for %r", lg, exc_info=True)
        return offline_fields(lg)

    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or len(rows) == 0:
        return offline_fields(lg)

    row = rows[0]
    if not isinstance(row, dict):
        return offline_fields(lg)
    return live_fields(lg, row)
