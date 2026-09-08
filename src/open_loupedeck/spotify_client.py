"""Spotify Web API: PKCE OAuth, token storage, playback helpers."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import secrets
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)

SPOTIFY_AUTH = "https://accounts.spotify.com/authorize"
SPOTIFY_TOKEN = "https://accounts.spotify.com/api/token"
SPOTIFY_API = "https://api.spotify.com/v1"

# Playback control requires Spotify Premium for many users; scopes:
SCOPES = "user-read-playback-state user-modify-playback-state"

_PENDING_TTL_SEC = 600.0
_PENDING: dict[str, tuple[str, float]] = {}  # state -> (code_verifier, monotonic_ts)


def _cleanup_pending() -> None:
    now = time.monotonic()
    dead = [k for k, (_, t) in _PENDING.items() if now - t > _PENDING_TTL_SEC]
    for k in dead:
        del _PENDING[k]


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)[:128]
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return verifier, challenge


def normalize_playlist_uri(raw: str) -> str:
    """Accept spotify:playlist:id, open.spotify.com URL, or raw playlist id."""

    s = str(raw or "").strip()
    if not s:
        return ""
    if s.startswith("spotify:playlist:"):
        return s
    m = re.search(r"open\.spotify\.com/playlist/([a-zA-Z0-9]+)", s)
    if m:
        return f"spotify:playlist:{m.group(1)}"
    if re.match(r"^[a-zA-Z0-9]{22}$", s):
        return f"spotify:playlist:{s}"
    return s


class SpotifyManager:
    """PKCE OAuth (no client secret). Tokens live beside config in ``spotify_tokens.json``."""

    def __init__(
        self,
        token_path: Path,
        get_spotify_section: Callable[[], dict[str, Any]],
    ) -> None:
        self._token_path = token_path
        self._get_section = get_spotify_section

    def _section(self) -> dict[str, Any]:
        return dict(self._get_section() or {})

    def is_configured(self) -> bool:
        s = self._section()
        return bool(str(s.get("client_id") or "").strip() and str(s.get("redirect_uri") or "").strip())

    def client_id(self) -> str:
        return str(self._section().get("client_id") or "").strip()

    def redirect_uri(self) -> str:
        return str(self._section().get("redirect_uri") or "").strip()

    def _load_tokens(self) -> dict[str, Any] | None:
        if not self._token_path.is_file():
            return None
        try:
            return json.loads(self._token_path.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("Could not read %s", self._token_path)
            return None

    def _save_tokens(self, data: dict[str, Any]) -> None:
        self._token_path.parent.mkdir(parents=True, exist_ok=True)
        self._token_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def has_tokens(self) -> bool:
        t = self._load_tokens()
        return bool(t and t.get("refresh_token"))

    def clear_tokens(self) -> None:
        try:
            if self._token_path.is_file():
                self._token_path.unlink()
        except OSError:
            logger.exception("Could not remove %s", self._token_path)

    def build_authorize_url(self) -> tuple[str, str]:
        """Returns (authorize_url, state)."""

        if not self.is_configured():
            raise RuntimeError("spotify.client_id and spotify.redirect_uri must be set in config")
        verifier, challenge = _pkce_pair()
        state = secrets.token_urlsafe(24)
        _cleanup_pending()
        _PENDING[state] = (verifier, time.monotonic())
        q = urlencode(
            {
                "client_id": self.client_id(),
                "response_type": "code",
                "redirect_uri": self.redirect_uri(),
                "scope": SCOPES,
                "state": state,
                "code_challenge_method": "S256",
                "code_challenge": challenge,
                "show_dialog": "true",
            }
        )
        return f"{SPOTIFY_AUTH}?{q}", state

    def pop_verifier_for_state(self, state: str) -> str | None:
        _cleanup_pending()
        item = _PENDING.pop(state, None)
        if not item:
            return None
        ver, ts = item
        if time.monotonic() - ts > _PENDING_TTL_SEC:
            return None
        return ver

    async def exchange_code(self, code: str, verifier: str) -> None:
        cid = self.client_id()
        redir = self.redirect_uri()
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redir,
            "client_id": cid,
            "code_verifier": verifier,
        }
        async with httpx.AsyncClient() as client:
            r = await client.post(
                SPOTIFY_TOKEN,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=30.0,
            )
        if r.status_code != 200:
            logger.error("Spotify token exchange failed: %s %s", r.status_code, r.text)
            raise RuntimeError(f"Spotify login failed ({r.status_code})")
        j = r.json()
        exp = float(j.get("expires_in") or 3600)
        self._save_tokens(
            {
                "access_token": j.get("access_token", ""),
                "refresh_token": j.get("refresh_token", ""),
                "expires_at": time.time() + exp - 60.0,
                "client_id": cid,
            }
        )

    async def _refresh(self, client: httpx.AsyncClient, tok: dict[str, Any]) -> dict[str, Any]:
        rt = tok.get("refresh_token")
        cid = str(tok.get("client_id") or self.client_id())
        if not rt or not cid:
            raise RuntimeError("Spotify session expired; connect again in the web UI")
        data = {
            "grant_type": "refresh_token",
            "refresh_token": str(rt),
            "client_id": cid,
        }
        r = await client.post(
            SPOTIFY_TOKEN,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30.0,
        )
        if r.status_code != 200:
            logger.error("Spotify refresh failed: %s %s", r.status_code, r.text)
            self.clear_tokens()
            raise RuntimeError("Spotify session expired; connect again in the web UI")
        j = r.json()
        exp = float(j.get("expires_in") or 3600)
        tok["access_token"] = j.get("access_token", "")
        if j.get("refresh_token"):
            tok["refresh_token"] = j["refresh_token"]
        tok["expires_at"] = time.time() + exp - 60.0
        tok["client_id"] = cid
        self._save_tokens(tok)
        return tok

    async def ensure_access_token(self, client: httpx.AsyncClient) -> str:
        tok = self._load_tokens()
        if not tok or not tok.get("access_token"):
            raise RuntimeError("Spotify is not connected; use the web UI to connect")
        exp = float(tok.get("expires_at") or 0)
        if time.time() >= exp:
            tok = await self._refresh(client, tok)
        return str(tok["access_token"])

    async def api(
        self,
        client: httpx.AsyncClient,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any | None = None,
    ) -> httpx.Response:
        token = await self.ensure_access_token(client)
        url = f"{SPOTIFY_API}{path}" if path.startswith("/") else f"{SPOTIFY_API}/{path}"
        headers = {"Authorization": f"Bearer {token}"}
        return await client.request(
            method.upper(),
            url,
            headers=headers,
            params=params,
            json=json_body,
            timeout=30.0,
        )

    async def get_me(self, client: httpx.AsyncClient) -> dict[str, Any]:
        r = await self.api(client, "GET", "/me")
        if r.status_code != 200:
            return {}
        return r.json()

    def _device_qs(self, device_id: str | None) -> dict[str, Any]:
        d = str(device_id or "").strip()
        return {"device_id": d} if d else {}

    async def play_pause(self, client: httpx.AsyncClient, device_id: str | None = None) -> None:
        r = await self.api(client, "GET", "/me/player")
        if r.status_code == 204:
            raise RuntimeError(
                "No active Spotify player; open Spotify on a phone, desktop, or web player and try again"
            )
        if r.status_code != 200:
            raise RuntimeError(f"Spotify player state failed ({r.status_code})")
        st = r.json()
        playing = bool(st.get("is_playing"))
        dev = self._device_qs(device_id)
        if playing:
            r2 = await self.api(client, "PUT", "/me/player/pause", params=dev)
        else:
            r2 = await self.api(client, "PUT", "/me/player/play", params=dev)
        if r2.status_code not in (200, 202, 204):
            raise RuntimeError(f"Spotify play/pause failed ({r2.status_code}): {r2.text[:200]}")

    async def next_track(self, client: httpx.AsyncClient, device_id: str | None = None) -> None:
        r = await self.api(client, "POST", "/me/player/next", params=self._device_qs(device_id))
        if r.status_code not in (200, 202, 204):
            raise RuntimeError(f"Spotify next failed ({r.status_code}): {r.text[:200]}")

    async def previous_track(self, client: httpx.AsyncClient, device_id: str | None = None) -> None:
        r = await self.api(client, "POST", "/me/player/previous", params=self._device_qs(device_id))
        if r.status_code not in (200, 202, 204):
            raise RuntimeError(f"Spotify previous failed ({r.status_code}): {r.text[:200]}")

    async def set_volume(
        self,
        client: httpx.AsyncClient,
        percent: int,
        device_id: str | None = None,
    ) -> None:
        pct = max(0, min(100, int(percent)))
        params: dict[str, Any] = {"volume_percent": pct}
        params.update(self._device_qs(device_id))
        r = await self.api(client, "PUT", "/me/player/volume", params=params)
        if r.status_code not in (200, 202, 204):
            raise RuntimeError(f"Spotify volume failed ({r.status_code}): {r.text[:200]}")

    async def play_playlist(
        self,
        client: httpx.AsyncClient,
        playlist_uri: str,
        device_id: str | None = None,
    ) -> None:
        uri = normalize_playlist_uri(playlist_uri)
        if not uri.startswith("spotify:playlist:"):
            raise ValueError("spotify.play_playlist needs a playlist id, URI, or open.spotify.com link")
        body = {"context_uri": uri}
        params = self._device_qs(device_id)
        r = await self.api(client, "PUT", "/me/player/play", params=params, json_body=body)
        if r.status_code not in (200, 202, 204):
            raise RuntimeError(f"Spotify play playlist failed ({r.status_code}): {r.text[:200]}")
