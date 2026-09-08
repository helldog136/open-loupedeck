"""Home Assistant REST API client (long-lived access token).

Unlike ``ObsSession`` (persistent WebSocket), Home Assistant's REST API is stateless request/
response, so this reuses the agent's shared ``httpx.AsyncClient`` instead of owning a connection.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


def _friendly_error(base_url: str, exc: BaseException) -> str:
    if isinstance(exc, httpx.ConnectError):
        return (
            f"Could not reach Home Assistant at {base_url}. Check ha.base_url in your config "
            "and that Home Assistant is reachable from this machine."
        )
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code == 401:
            return "Home Assistant rejected the token (401). Check ha.token (Profile → Long-Lived Access Tokens)."
        return f"Home Assistant request failed: HTTP {code} {exc.response.text[:200]}"
    return f"Home Assistant request to {base_url} failed: {exc}"


class HaClient:
    def __init__(self, http_client: httpx.AsyncClient, base_url: str, token: str) -> None:
        self._http = http_client
        self._base_url = str(base_url or "").strip().rstrip("/")
        self._token = str(token or "")

    @property
    def base_url(self) -> str:
        return self._base_url

    def update_credentials(self, base_url: str, token: str) -> bool:
        """Apply new connection settings (e.g. after the user edits them in the UI).

        Without this, editing ``ha.base_url``/``ha.token`` from the UI updates config.yaml but the
        live client -- built once at agent startup -- keeps using the original values until the
        whole app restarts.
        """

        new_base_url = str(base_url or "").strip().rstrip("/")
        new_token = str(token or "")
        changed = (new_base_url, new_token) != (self._base_url, self._token)
        self._base_url = new_base_url
        self._token = new_token
        return changed

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    async def get_state(self, entity_id: str) -> dict[str, Any] | None:
        """``GET /api/states/<entity_id>``: ``{"state": ..., "attributes": {...}, ...}``."""

        url = f"{self._base_url}/api/states/{entity_id}"
        try:
            r = await self._http.get(url, headers=self._headers(), timeout=10.0)
        except httpx.HTTPError as exc:
            raise RuntimeError(_friendly_error(self._base_url, exc)) from exc
        if r.status_code == 404:
            return None
        try:
            r.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(_friendly_error(self._base_url, exc)) from exc
        data = r.json()
        return data if isinstance(data, dict) else None

    async def call_service(
        self,
        domain: str,
        service: str,
        entity_id: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> Any:
        """``POST /api/services/<domain>/<service>``, optionally targeting ``entity_id``."""

        url = f"{self._base_url}/api/services/{domain}/{service}"
        body: dict[str, Any] = dict(data or {})
        if entity_id:
            body.setdefault("entity_id", entity_id)
        try:
            r = await self._http.post(url, headers=self._headers(), json=body, timeout=15.0)
            r.raise_for_status()
        except httpx.HTTPError as exc:
            raise RuntimeError(_friendly_error(self._base_url, exc)) from exc
        try:
            return r.json()
        except Exception:
            return None

    async def probe(self, timeout: float = 5.0) -> bool:
        """Best-effort reachability + auth check (``GET /api/``)."""

        try:
            r = await self._http.get(f"{self._base_url}/api/", headers=self._headers(), timeout=timeout)
            return r.status_code == 200
        except Exception:
            return False
