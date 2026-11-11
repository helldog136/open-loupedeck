"""The agent, skin and web UI driven through the DeviceBackend interface (FakeBackend, no hardware)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from open_loupedeck.actions.registry import register_handler
from open_loupedeck.config_io import save_raw_config
from open_loupedeck.config_state import ConfigState
from open_loupedeck.deck_skin import apply_page_skin, drawable_control_ids, page_needs_animated_skin
from open_loupedeck.devices.loupedeck.models import LOUPEDECK_LIVE, LOUPEDECK_LIVE_S
from open_loupedeck.events import NormalizedEvent
from open_loupedeck.runtime_refs import AgentRuntimeRefs
from tests.fake_backend import FakeBackend


def _ev(kind: str, cid: Any, edge: str) -> NormalizedEvent:
    return NormalizedEvent(kind=kind, id=cid, edge=edge, raw={})  # type: ignore[arg-type]


def _rec(tag: str) -> dict[str, Any]:
    return {"type": "test.dev_record", "tag": tag}


def _config(model: str = "live_s") -> dict[str, Any]:
    return {
        "device": {"model": model},
        "brightness": 55,
        "knob_page_feedback": {"duration_sec": 0},
        "pages": [
            {"name": f"P{i}", "buttons": {"touch_2": {"text": f"k{i}", "actions": [_rec(f"p{i}-touch2")]}}}
            for i in range(5)
        ],
    }


class AgentHarness:
    def __init__(self, tmp_path: Path, raw: dict[str, Any], backend: FakeBackend | None) -> None:
        self.recorded: list[str] = []

        async def _record(_ctx: Any, params: dict[str, Any]) -> None:
            self.recorded.append(str(params.get("tag")))

        register_handler("test.dev_record", _record)
        cfg = tmp_path / "config.yaml"
        save_raw_config(cfg, raw)
        self.state = ConfigState(cfg)
        self.runtime = AgentRuntimeRefs(deck=backend, no_device=backend is None)
        self.redraws: list[str] = []

    async def redraw(self, reason: str = "") -> None:
        self.redraws.append(reason)

    async def start(self) -> asyncio.Task[None]:
        from open_loupedeck.app import run_agent

        task = asyncio.create_task(run_agent(self.state, asyncio.Lock(), self.redraw, self.runtime))
        for _ in range(200):
            if self.runtime.simulate_event is not None:
                break
            await asyncio.sleep(0.01)
        assert self.runtime.simulate_event is not None
        return task

    @staticmethod
    async def stop(task: asyncio.Task[None]) -> None:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


async def _settle() -> None:
    for _ in range(5):
        await asyncio.sleep(0.01)


def test_backend_lifecycle_events_and_brightness(tmp_path: Path):
    dev = FakeBackend(LOUPEDECK_LIVE_S)
    h = AgentHarness(tmp_path, _config(), dev)

    async def go() -> None:
        task = await h.start()
        assert dev.opened and dev.event_callback is not None and dev.unplugged_callback is not None
        assert dev.levels == [55]  # brightness applied right after open
        assert "agent_startup" in h.redraws
        dev.emit(_ev("touch", 2, "down"))  # from the "device thread"
        dev.emit(_ev("touch", 2, "up"))  # up edges are not dispatched
        await _settle()
        await h.stop(task)
        assert dev.closed  # closed on shutdown
        assert h.runtime.simulate_event is None and h.runtime.simulate_raw_message is None

    asyncio.run(go())
    assert h.recorded == ["p0-touch2"]


def test_page_buttons_come_from_the_model(tmp_path: Path):
    live_s = AgentHarness(tmp_path, _config("live_s"), FakeBackend(LOUPEDECK_LIVE_S))

    async def go_s() -> list[int]:
        task = await live_s.start()
        seen = []
        for raw_id in ("2", "circle", "3", "1"):
            await live_s.runtime.simulate_event(_ev("button", raw_id, "down"))
            seen.append(live_s.state.page_index)
        await live_s.runtime.simulate_event(_ev("touch", 2, "down"))
        await h_stop(task)
        return seen

    async def h_stop(task: asyncio.Task[None]) -> None:
        await AgentHarness.stop(task)

    assert asyncio.run(go_s()) == [2, 0, 3, 1]
    assert live_s.redraws.count("physical_page_button") == 4
    assert live_s.recorded == ["p1-touch2"]

    (tmp_path / "live").mkdir()
    live = AgentHarness(tmp_path / "live", _config("live"), FakeBackend(LOUPEDECK_LIVE))

    async def go_live() -> int:
        task = await live.start()
        await live.runtime.simulate_event(_ev("button", "2", "down"))
        idx = live.state.page_index
        await AgentHarness.stop(task)
        return idx

    assert asyncio.run(go_live()) == 0  # the Live has no page buttons
    assert "physical_page_button" not in live.redraws


def test_raw_message_compat_path_and_knob_press(tmp_path: Path):
    raw = _config()
    raw["knob_page_feedback"] = {"duration_sec": 0.01}
    raw["pages"][0]["knobs"] = {"knobCL": {"press": _rec("press"), "rotate": {"left": _rec("left")}}}
    dev = FakeBackend(LOUPEDECK_LIVE_S)
    h = AgentHarness(tmp_path, raw, dev)

    async def go() -> None:
        task = await h.start()
        await h.runtime.simulate_raw_message({"action": "push", "state": "down", "id": "knobCL"})
        await h.runtime.simulate_event(_ev("knob", "knobCL", "left"))
        await h.runtime.simulate_raw_message({"action": "touchstart", "screen": "center", "key": 2})
        await asyncio.sleep(0.15)
        await AgentHarness.stop(task)

    asyncio.run(go())
    assert h.recorded == ["press", "left", "p0-touch2"]
    assert dev.images == ["touch_5", "touch_5"]  # feedback next to knobCL, drawn by control id


def test_unplug_signal_triggers_reconnect_through_the_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import open_loupedeck.app as app_mod

    first = FakeBackend(LOUPEDECK_LIVE_S)
    second = FakeBackend(LOUPEDECK_LIVE_S, path="/dev/fake1")
    opened: list[Any] = []

    def fake_open(settings: Any) -> FakeBackend:
        opened.append(settings.device.model)
        return second

    monkeypatch.setattr(app_mod, "open_backend", fake_open)
    h = AgentHarness(tmp_path, _config(), first)
    h.runtime.no_device = False

    async def go() -> None:
        task = await h.start()
        first.unplug()
        await _settle()
        assert h.runtime.deck_unplugged
        for _ in range(60):
            if h.runtime.deck is second:
                break
            await asyncio.sleep(0.1)
        await _settle()
        await AgentHarness.stop(task)

    asyncio.run(go())
    assert opened == ["live_s"]
    assert h.runtime.deck is second and not h.runtime.deck_unplugged
    assert first.closed and first.unplugged_callback is None
    assert second.opened and second.event_callback is not None and second.levels == [55]
    assert "deck_reconnect" in h.redraws
    assert second.closed  # shutdown closes the current device


def test_skin_draws_the_model_controls_and_leds(tmp_path: Path):
    page = {"name": "A", "buttons": {"touch_1": {"text": "hi"}}}
    gb = {"btn_2": {"button_color": "#ff0000"}, "strip_left": {"text": "L"}}

    s = FakeBackend(LOUPEDECK_LIVE_S)
    apply_page_skin(s, page, tmp_path, gb)
    assert s.images == [f"touch_{i}" for i in range(15)]
    assert s.colors == {
        "btn_circle": (32, 32, 40),
        "btn_1": (32, 32, 40),
        "btn_2": (255, 0, 0),
        "btn_3": (32, 32, 40),
    }
    assert s.lock_depth == 0

    live = FakeBackend(LOUPEDECK_LIVE)
    apply_page_skin(live, page, tmp_path, gb)
    assert live.images == LOUPEDECK_LIVE.drawable_control_ids() == drawable_control_ids(live)
    assert live.colors == {}  # no LED capability on the Live model
    assert not page_needs_animated_skin(live, page, gb, tmp_path)
    assert page_needs_animated_skin(live, {"buttons": {"touch_0": {"idle_animation": "pulse"}}}, {}, tmp_path)


def test_web_simulate_press_and_status_use_the_backend(tmp_path: Path):
    from fastapi.testclient import TestClient

    from open_loupedeck.web_app import create_web_app

    path = tmp_path / "config.yaml"
    state = ConfigState(path)
    rt = AgentRuntimeRefs()
    dev = FakeBackend(LOUPEDECK_LIVE_S)
    dev.open()
    rt.deck = dev
    got: list[NormalizedEvent] = []

    async def sim(ev: NormalizedEvent) -> None:
        got.append(ev)

    rt.simulate_event = sim
    client = TestClient(create_web_app(path, state, asyncio.Lock(), runtime=rt))
    assert client.post("/api/simulate_press", json={"control_id": "knobCL", "direction": "left"}).status_code == 200
    assert client.post("/api/simulate_press", json={"control_id": "btn_circle"}).status_code == 200
    assert client.post("/api/simulate_press", json={"control_id": "strip_left"}).status_code == 400
    assert [(e.kind, e.id, e.edge) for e in got] == [("knob", "knobCL", "left"), ("button", "circle", "down")]

    st = client.get("/api/status").json()
    assert st["deck_layout"] == "live_s"
    assert st["usb"] == {"connected": True, "disabled": False, "detail": "/dev/fake0", "path": "/dev/fake0"}
    rt.deck = FakeBackend(LOUPEDECK_LIVE)
    assert client.get("/api/status").json()["deck_layout"] == "live"


def test_api_device_model(tmp_path: Path):
    from fastapi.testclient import TestClient

    from open_loupedeck.web_app import create_web_app

    path = tmp_path / "config.yaml"
    save_raw_config(path, {"device": {"model": "live"}})
    state = ConfigState(path)
    rt = AgentRuntimeRefs(no_device=True)
    client = TestClient(create_web_app(path, state, asyncio.Lock(), runtime=rt))

    body = client.get("/api/device_model").json()
    assert body["source"] == "config" and body["connected"] is False and body["configured_model"] == "live"
    assert body["model"] == LOUPEDECK_LIVE.to_dict()
    assert {"loupedeck_live", "loupedeck_live_s"} <= set(body["known_models"])

    dev = FakeBackend(LOUPEDECK_LIVE_S)
    dev.open()
    rt.deck = dev  # the connected device wins over the config
    body = client.get("/api/device_model").json()
    assert body["source"] == "device" and body["connected"] is True
    assert body["model"]["id"] == "loupedeck_live_s" and body["model"]["grid"]["count"] == 15

    rt.deck = None
    state.raw["device"] = {"model": "auto"}
    body = client.get("/api/device_model").json()
    assert body["source"] is None and body["model"] is None
