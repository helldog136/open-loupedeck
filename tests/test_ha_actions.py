"""``ha.*`` actions: dispatch to the configured HaClient with the right domain/service/entity."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from open_loupedeck.actions import ActionContext, run_actions


class _FakeHa:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str | None, dict[str, Any]]] = []

    async def call_service(self, domain, service, entity_id=None, data=None):
        self.calls.append((domain, service, entity_id, dict(data or {})))


def _ctx(ha: Any | None) -> ActionContext:
    return ActionContext(obs=None, http_client=None, log=logging.getLogger("t"), ha=ha)


def _run(coro):
    return asyncio.run(coro)


def test_ha_turn_on_calls_homeassistant_turn_on_with_data():
    ha = _FakeHa()
    _run(run_actions(_ctx(ha), [{"type": "ha.turn_on", "entity_id": "light.kitchen", "data": {"brightness_pct": 60}}]))
    assert ha.calls == [("homeassistant", "turn_on", "light.kitchen", {"brightness_pct": 60})]


def test_ha_turn_off_calls_homeassistant_turn_off():
    ha = _FakeHa()
    _run(run_actions(_ctx(ha), [{"type": "ha.turn_off", "entity_id": "switch.desk"}]))
    assert ha.calls == [("homeassistant", "turn_off", "switch.desk", {})]


def test_ha_toggle_calls_homeassistant_toggle():
    ha = _FakeHa()
    _run(run_actions(_ctx(ha), [{"type": "ha.toggle", "entity_id": "light.kitchen"}]))
    assert ha.calls == [("homeassistant", "toggle", "light.kitchen", {})]


def test_ha_run_script_normalizes_bare_object_id():
    ha = _FakeHa()
    _run(run_actions(_ctx(ha), [{"type": "ha.run_script", "script": "good_night"}]))
    assert ha.calls == [("script", "turn_on", "script.good_night", {})]


def test_ha_run_script_accepts_full_entity_id():
    ha = _FakeHa()
    _run(run_actions(_ctx(ha), [{"type": "ha.run_script", "script": "script.good_night"}]))
    assert ha.calls == [("script", "turn_on", "script.good_night", {})]


def test_ha_call_service_generic_domain_service_entity_and_data():
    ha = _FakeHa()
    _run(
        run_actions(
            _ctx(ha),
            [
                {
                    "type": "ha.call_service",
                    "domain": "climate",
                    "service": "set_temperature",
                    "entity_id": "climate.bedroom",
                    "data": {"temperature": 21},
                }
            ],
        )
    )
    assert ha.calls == [("climate", "set_temperature", "climate.bedroom", {"temperature": 21})]


def test_ha_call_service_without_entity_id():
    ha = _FakeHa()
    _run(run_actions(_ctx(ha), [{"type": "ha.call_service", "domain": "automation", "service": "trigger"}]))
    assert ha.calls == [("automation", "trigger", None, {})]


def test_ha_actions_fail_gracefully_without_ha_configured(caplog):
    """No ha client configured: run_actions swallows the RuntimeError (logged), doesn't raise."""

    with caplog.at_level(logging.ERROR):
        _run(run_actions(_ctx(None), [{"type": "ha.turn_on", "entity_id": "light.kitchen"}]))
    assert "not configured" in caplog.text or "Action" in caplog.text
