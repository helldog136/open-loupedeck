"""``display.ha_sensor`` / ``display.ha_weather``: param extraction, polling, and templating."""

from __future__ import annotations

import asyncio
import logging

import httpx

from open_loupedeck.live_message import (
    dynamic_display_overlay_entry,
    ha_sensor_params_from_entry,
    ha_weather_params_from_entry,
    refresh_live_messages,
)
from open_loupedeck.runtime_refs import AgentRuntimeRefs


class _FakeHa:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.states: dict[str, dict] = {}
        self.raise_for: set[str] = set()

    async def get_state(self, entity_id: str):
        self.calls.append(entity_id)
        if entity_id in self.raise_for:
            raise RuntimeError("boom")
        return self.states.get(entity_id)


def _run(coro):
    return asyncio.run(coro)


def _raw_with_button(action: dict) -> dict:
    return {"pages": [{"id": 0, "name": "Page 1", "buttons": {"touch_0": {"action": action}}}]}


def test_ha_sensor_params_from_entry_extracts_non_type_fields():
    entry = {"action": {"type": "display.ha_sensor", "entity_id": "sensor.temp", "template": "{state}"}}
    params = ha_sensor_params_from_entry(entry)
    assert params == {"entity_id": "sensor.temp", "template": "{state}"}
    assert ha_sensor_params_from_entry({"action": {"type": "obs.set_scene"}}) is None


def test_ha_weather_params_from_entry_extracts_non_type_fields():
    entry = {"action": {"type": "display.ha_weather", "entity_id": "weather.home"}}
    assert ha_weather_params_from_entry(entry) == {"entity_id": "weather.home"}


def test_dynamic_display_overlay_entry_true_for_ha_kinds():
    assert dynamic_display_overlay_entry({"action": {"type": "display.ha_sensor", "entity_id": "sensor.temp"}})
    assert dynamic_display_overlay_entry({"action": {"type": "display.ha_weather", "entity_id": "weather.home"}})
    assert not dynamic_display_overlay_entry({"action": {"type": "obs.set_scene", "scene": "x"}})


def test_refresh_live_messages_renders_ha_sensor_default_template():
    ha = _FakeHa()
    ha.states["sensor.temp"] = {"state": "21.5", "attributes": {"unit_of_measurement": "°C", "friendly_name": "Temp"}}
    raw = _raw_with_button({"type": "display.ha_sensor", "entity_id": "sensor.temp"})
    runtime = AgentRuntimeRefs()

    async def go():
        async with httpx.AsyncClient() as http_client:
            return await refresh_live_messages(raw, 0, runtime, http_client, logging.getLogger("t"), None, ha)

    changed = _run(go())

    assert changed is True
    assert runtime.live_message_text["p0:touch_0"] == "21.5°C"
    assert ha.calls == ["sensor.temp"]


def test_refresh_live_messages_respects_custom_template_and_caches_between_calls():
    ha = _FakeHa()
    ha.states["sensor.hum"] = {"state": "55", "attributes": {"unit_of_measurement": "%", "friendly_name": "Humidity"}}
    raw = _raw_with_button(
        {"type": "display.ha_sensor", "entity_id": "sensor.hum", "template": "{name}: {state}{unit}"}
    )
    runtime = AgentRuntimeRefs()

    async def go():
        async with httpx.AsyncClient() as http_client:
            await refresh_live_messages(raw, 0, runtime, http_client, logging.getLogger("t"), None, ha)
            # Second call immediately after: within the default 30s interval, must not re-fetch.
            await refresh_live_messages(raw, 0, runtime, http_client, logging.getLogger("t"), None, ha)

    _run(go())

    assert runtime.live_message_text["p0:touch_0"] == "Humidity: 55%"
    assert ha.calls == ["sensor.hum"]


def test_refresh_live_messages_ha_sensor_unavailable_entity_shows_dash():
    ha = _FakeHa()  # no state registered -> get_state returns None
    raw = _raw_with_button({"type": "display.ha_sensor", "entity_id": "sensor.missing"})
    runtime = AgentRuntimeRefs()

    async def go():
        async with httpx.AsyncClient() as http_client:
            return await refresh_live_messages(raw, 0, runtime, http_client, logging.getLogger("t"), None, ha)

    _run(go())

    assert runtime.live_message_text["p0:touch_0"] == "—"


def test_refresh_live_messages_ha_sensor_fetch_error_does_not_raise():
    ha = _FakeHa()
    ha.raise_for.add("sensor.err")
    raw = _raw_with_button({"type": "display.ha_sensor", "entity_id": "sensor.err"})
    runtime = AgentRuntimeRefs()

    async def go():
        async with httpx.AsyncClient() as http_client:
            return await refresh_live_messages(raw, 0, runtime, http_client, logging.getLogger("t"), None, ha)

    _run(go())  # must not raise

    assert runtime.live_message_text["p0:touch_0"] == "—"


def test_refresh_live_messages_renders_ha_weather_default_template():
    ha = _FakeHa()
    ha.states["weather.home"] = {
        "state": "sunny",
        "attributes": {"temperature": 21.5, "temperature_unit": "°C", "friendly_name": "Home"},
    }
    raw = _raw_with_button({"type": "display.ha_weather", "entity_id": "weather.home"})
    runtime = AgentRuntimeRefs()

    async def go():
        async with httpx.AsyncClient() as http_client:
            return await refresh_live_messages(raw, 0, runtime, http_client, logging.getLogger("t"), None, ha)

    _run(go())

    assert runtime.live_message_text["p0:touch_0"] == "sunny\n21.5°C"


def test_refresh_live_messages_ha_actions_without_ha_client_do_not_raise():
    raw = _raw_with_button({"type": "display.ha_sensor", "entity_id": "sensor.temp"})
    runtime = AgentRuntimeRefs()

    async def go():
        async with httpx.AsyncClient() as http_client:
            return await refresh_live_messages(raw, 0, runtime, http_client, logging.getLogger("t"), None, None)

    _run(go())  # ha=None must degrade gracefully, not raise

    assert runtime.live_message_text["p0:touch_0"] == "—"
