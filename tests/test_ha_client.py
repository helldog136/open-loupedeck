from __future__ import annotations

import asyncio
from typing import Any

import httpx

from open_loupedeck.ha_client import HaClient


class _FakeResponse:
    def __init__(self, json_data: Any = None, status: int = 200) -> None:
        self._json = json_data
        self.status_code = status
        self.text = "" if json_data is None else str(json_data)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("GET", "http://example/")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("error", request=request, response=response)

    def json(self) -> Any:
        return self._json


class _FakeHttpClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.get_response: _FakeResponse = _FakeResponse({})
        self.post_response: _FakeResponse = _FakeResponse({})
        self.raise_on_get: Exception | None = None

    async def get(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.calls.append(("GET", url, kwargs))
        if self.raise_on_get is not None:
            raise self.raise_on_get
        return self.get_response

    async def post(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.calls.append(("POST", url, kwargs))
        return self.post_response


def _run(coro):
    return asyncio.run(coro)


def test_get_state_returns_dict_on_success():
    http = _FakeHttpClient()
    http.get_response = _FakeResponse({"state": "21.5", "attributes": {"unit_of_measurement": "°C"}})
    client = HaClient(http, "http://ha.local:8123", "tok")

    state = _run(client.get_state("sensor.temp"))

    assert state == {"state": "21.5", "attributes": {"unit_of_measurement": "°C"}}
    method, url, kwargs = http.calls[0]
    assert method == "GET"
    assert url == "http://ha.local:8123/api/states/sensor.temp"
    assert kwargs["headers"]["Authorization"] == "Bearer tok"


def test_get_state_returns_none_on_404():
    http = _FakeHttpClient()
    http.get_response = _FakeResponse(status=404)
    client = HaClient(http, "http://ha.local:8123", "tok")

    assert _run(client.get_state("sensor.missing")) is None


def test_get_state_raises_friendly_error_on_401():
    http = _FakeHttpClient()
    http.get_response = _FakeResponse(status=401)
    client = HaClient(http, "http://ha.local:8123", "bad-token")

    try:
        _run(client.get_state("sensor.temp"))
        raise AssertionError("expected RuntimeError")
    except RuntimeError as exc:
        assert "rejected the token" in str(exc)


def test_get_state_raises_friendly_error_on_connect_failure():
    http = _FakeHttpClient()
    http.raise_on_get = httpx.ConnectError("boom", request=httpx.Request("GET", "http://ha.local/"))
    client = HaClient(http, "http://ha.local:8123", "tok")

    try:
        _run(client.get_state("sensor.temp"))
        raise AssertionError("expected RuntimeError")
    except RuntimeError as exc:
        assert "Could not reach Home Assistant" in str(exc)


def test_call_service_posts_entity_id_and_extra_data():
    http = _FakeHttpClient()
    client = HaClient(http, "http://ha.local:8123/", "tok")

    _run(client.call_service("light", "turn_on", "light.kitchen", {"brightness_pct": 60}))

    method, url, kwargs = http.calls[0]
    assert method == "POST"
    assert url == "http://ha.local:8123/api/services/light/turn_on"
    assert kwargs["json"] == {"brightness_pct": 60, "entity_id": "light.kitchen"}


def test_call_service_without_entity_id():
    http = _FakeHttpClient()
    client = HaClient(http, "http://ha.local:8123", "tok")

    _run(client.call_service("automation", "trigger", data={"variables": {"x": 1}}))

    _method, _url, kwargs = http.calls[0]
    assert kwargs["json"] == {"variables": {"x": 1}}


def test_probe_true_on_200():
    http = _FakeHttpClient()
    http.get_response = _FakeResponse({}, status=200)
    client = HaClient(http, "http://ha.local:8123", "tok")

    assert _run(client.probe()) is True


def test_probe_false_on_error():
    http = _FakeHttpClient()
    http.raise_on_get = RuntimeError("network down")
    client = HaClient(http, "http://ha.local:8123", "tok")

    assert _run(client.probe()) is False


def test_update_credentials_applies_new_base_url_and_token():
    http = _FakeHttpClient()
    client = HaClient(http, "http://ha.local:8123", "old-tok")

    changed = client.update_credentials("http://ha.local:9999/", "new-tok")

    assert changed is True
    assert client.base_url == "http://ha.local:9999"
    _run(client.get_state("sensor.temp"))
    _method, url, kwargs = http.calls[0]
    assert url == "http://ha.local:9999/api/states/sensor.temp"
    assert kwargs["headers"]["Authorization"] == "Bearer new-tok"


def test_update_credentials_reports_unchanged_when_identical():
    http = _FakeHttpClient()
    client = HaClient(http, "http://ha.local:8123", "tok")

    changed = client.update_credentials("http://ha.local:8123", "tok")

    assert changed is False
