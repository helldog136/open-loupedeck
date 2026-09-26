"""Twitch Helix with a *user* access token (clips, ads, chat settings, raids, ...).

Distinct from ``twitch_helix.py`` (read-only stream status via an app token): the management
endpoints act on the broadcaster's own channel and need a user token with specific scopes. It is
obtained with Twitch's Device Code Grant flow -- the user just approves a code on twitch.tv, so
no redirect URI and no client secret are needed. Tokens live beside the config in
``twitch_tokens.json`` (keyed by ``client_id``).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

TWITCH_DEVICE_URL = "https://id.twitch.tv/oauth2/device"
TWITCH_TOKEN_URL = "https://id.twitch.tv/oauth2/token"
TWITCH_HELIX = "https://api.twitch.tv/helix"

# Everything the twitch.* actions need; Twitch asks apps to request only scopes they use.
TWITCH_SCOPES = [
    "clips:edit",
    "channel:edit:commercial",
    "channel:manage:ads",
    "channel:read:ads",
    "channel:manage:broadcast",
    "moderator:manage:chat_settings",
    "moderator:manage:announcements",
    "moderator:manage:chat_messages",
    "moderator:manage:shoutouts",
    "user:write:chat",
    "channel:manage:raids",
]

# client_id of the Open-Loupedeck Twitch application (a *Public* client, so it is not a secret and
# needs no client secret). Lets users just click "Connect" and log in on twitch.tv instead of
# registering their own developer app; an account's own ``client_id`` in config overrides it.
DEFAULT_CLIENT_ID = "i2bc7qcz6t72syr61qcbrim4zqvx8h"

_DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
_EXPIRY_MARGIN_S = 60.0


class TwitchManager:
    def __init__(self, token_path: Path, get_accounts: Callable[[], list[dict[str, Any]]]) -> None:
        self._token_path = token_path
        self._get_accounts = get_accounts
        self._pending: dict[str, dict[str, Any]] = {}  # client_id -> device flow state
        self._refresh_lock = asyncio.Lock()

    # --- token store -------------------------------------------------------------------

    def _load_all(self) -> dict[str, Any]:
        if not self._token_path.is_file():
            return {}
        try:
            data = json.loads(self._token_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            logger.exception("Could not read %s", self._token_path)
            return {}

    def _save_all(self, data: dict[str, Any]) -> None:
        self._token_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._token_path.with_name(f"{self._token_path.name}.tmp-{os.getpid()}")
        try:
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            os.replace(tmp, self._token_path)
        finally:
            tmp.unlink(missing_ok=True)

    def _tokens(self, client_id: str) -> dict[str, Any] | None:
        t = self._load_all().get(client_id)
        return t if isinstance(t, dict) and t.get("refresh_token") else None

    def _store(self, client_id: str, tok: dict[str, Any]) -> None:
        data = self._load_all()
        data[client_id] = tok
        self._save_all(data)

    def is_connected(self, account: dict[str, Any]) -> bool:
        return self._tokens(account_key(account)) is not None

    def login_for(self, account: dict[str, Any]) -> str:
        t = self._tokens(account_key(account))
        return str(t.get("login") or "") if t else ""

    def disconnect(self, account: dict[str, Any]) -> None:
        key = account_key(account)
        data = self._load_all()
        if data.pop(key, None) is not None:
            self._save_all(data)
        self._pending.pop(key, None)

    # --- device code flow --------------------------------------------------------------

    async def start_device_flow(self, client: httpx.AsyncClient, account: dict[str, Any]) -> dict[str, Any]:
        client_id = resolve_client_id(account)
        r = await client.post(
            TWITCH_DEVICE_URL,
            data={"client_id": client_id, "scopes": " ".join(TWITCH_SCOPES)},
            timeout=20.0,
        )
        if r.status_code != 200:
            raise RuntimeError(_error_text("Twitch device authorization failed", r))
        j = r.json()
        self._pending[account_key(account)] = {
            "device_code": j["device_code"],
            "expires_at": time.time() + float(j.get("expires_in") or 300),
        }
        return {
            "user_code": j.get("user_code", ""),
            "verification_uri": j.get("verification_uri", ""),
            "expires_in": int(j.get("expires_in") or 300),
            "interval": int(j.get("interval") or 5),
        }

    async def poll_device_flow(self, client: httpx.AsyncClient, account: dict[str, Any]) -> dict[str, Any]:
        """One token-exchange attempt: ``pending`` | ``connected`` | ``expired`` | ``error``."""

        client_id = resolve_client_id(account)
        key = account_key(account)
        pend = self._pending.get(key)
        if not pend:
            return {"status": "expired", "detail": "No authorization in progress"}
        if time.time() >= float(pend["expires_at"]):
            self._pending.pop(key, None)
            return {"status": "expired", "detail": "Code expired -- start again"}
        r = await client.post(
            TWITCH_TOKEN_URL,
            data={
                "client_id": client_id,
                "scopes": " ".join(TWITCH_SCOPES),
                "device_code": pend["device_code"],
                "grant_type": _DEVICE_GRANT,
            },
            timeout=20.0,
        )
        if r.status_code != 200:
            msg = _message(r)
            if "pending" in msg.lower():
                return {"status": "pending"}
            self._pending.pop(key, None)
            return {"status": "error", "detail": msg or f"HTTP {r.status_code}"}
        j = r.json()
        self._pending.pop(key, None)
        tok = _token_record(j)
        me = await self._fetch_me(client, client_id, tok["access_token"])
        tok.update(me)
        self._store(key, tok)
        return {"status": "connected", "login": tok.get("login", "")}

    async def _fetch_me(self, client: httpx.AsyncClient, client_id: str, access: str) -> dict[str, str]:
        r = await client.get(
            f"{TWITCH_HELIX}/users",
            headers={"Authorization": f"Bearer {access}", "Client-Id": client_id},
            timeout=15.0,
        )
        r.raise_for_status()
        rows = r.json().get("data") or []
        if not rows:
            raise RuntimeError("Twitch did not return the authorized user")
        return {"user_id": str(rows[0]["id"]), "login": str(rows[0]["login"])}

    # --- tokens for API calls ----------------------------------------------------------

    async def _refresh(self, client: httpx.AsyncClient, account: dict[str, Any]) -> dict[str, Any]:
        client_id = resolve_client_id(account)
        key = account_key(account)
        async with self._refresh_lock:
            tok = self._tokens(key)
            if not tok:
                raise RuntimeError("Twitch is not connected for this account; use Connect in the web UI")
            # Another caller may have refreshed while we waited for the lock.
            if time.time() < float(tok.get("expires_at") or 0):
                return tok
            data = {
                "client_id": client_id,
                "grant_type": "refresh_token",
                "refresh_token": tok["refresh_token"],
            }
            secret = str(account.get("client_secret") or "").strip()
            if secret:
                data["client_secret"] = secret
            r = await client.post(TWITCH_TOKEN_URL, data=data, timeout=20.0)
            if r.status_code != 200:
                logger.error("Twitch refresh failed: %s %s", r.status_code, r.text)
                if r.status_code in (400, 401):
                    self.disconnect(account)
                raise RuntimeError("Twitch session expired; connect again in the web UI")
            new = _token_record(r.json())
            new["user_id"] = tok.get("user_id", "")
            new["login"] = tok.get("login", "")
            self._store(key, new)  # refresh tokens may be single-use: persist immediately
            return new

    async def _access(
        self, client: httpx.AsyncClient, account: dict[str, Any], *, force_refresh: bool = False
    ) -> dict[str, Any]:
        key = account_key(account)
        tok = self._tokens(key)
        if not tok:
            raise RuntimeError("Twitch is not connected for this account; use Connect in the web UI")
        if force_refresh or time.time() >= float(tok.get("expires_at") or 0):
            if force_refresh:
                tok = dict(tok, expires_at=0)
                self._store(key, tok)
            tok = await self._refresh(client, account)
        return tok

    async def user_id(self, client: httpx.AsyncClient, account: dict[str, Any]) -> str:
        return str((await self._access(client, account)).get("user_id") or "")

    async def helix(
        self,
        client: httpx.AsyncClient,
        account: dict[str, Any],
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any | None = None,
    ) -> Any:
        """Call a Helix endpoint as the connected user; returns parsed JSON (or ``{}``)."""

        cid = resolve_client_id(account)
        tok = await self._access(client, account)
        for attempt in (0, 1):
            r = await client.request(
                method.upper(),
                f"{TWITCH_HELIX}{path}",
                headers={"Authorization": f"Bearer {tok['access_token']}", "Client-Id": cid},
                params=params,
                json=json_body,
                timeout=20.0,
            )
            if r.status_code == 401 and attempt == 0:
                tok = await self._access(client, account, force_refresh=True)
                continue
            break
        if r.status_code >= 400:
            raise RuntimeError(_error_text(f"Twitch {method.upper()} {path}", r))
        if not r.content:
            return {}
        try:
            return r.json()
        except ValueError:
            return {}


def resolve_client_id(account: dict[str, Any] | None) -> str:
    """The account's own Twitch app, else the built-in one."""

    cid = str((account or {}).get("client_id") or "").strip() or DEFAULT_CLIENT_ID
    if not cid:
        raise RuntimeError("No Twitch client_id: set one under Services > Twitch (or use a build that ships one)")
    return cid


def account_key(account: dict[str, Any] | None) -> str:
    """Token-store key: the app's client_id, plus the account's optional ``label`` so two logins
    can share the built-in app."""

    cid = str((account or {}).get("client_id") or "").strip() or DEFAULT_CLIENT_ID or "default"
    label = str((account or {}).get("label") or "").strip()
    return f"{cid}|{label}" if label else cid


def _token_record(j: dict[str, Any]) -> dict[str, Any]:
    return {
        "access_token": j.get("access_token", ""),
        "refresh_token": j.get("refresh_token", ""),
        "expires_at": time.time() + float(j.get("expires_in") or 3600) - _EXPIRY_MARGIN_S,
    }


def _message(r: httpx.Response) -> str:
    try:
        j = r.json()
        return str(j.get("message") or j.get("error_description") or j.get("error") or "")
    except ValueError:
        return r.text[:200]


def _error_text(prefix: str, r: httpx.Response) -> str:
    return f"{prefix}: HTTP {r.status_code} {_message(r)}".strip()
