"""Virtual device: models, backend over the protocol, registry rules, WebSocket, full agent flow."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import dataclasses
import io
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from starlette.websockets import WebSocketDisconnect

from open_loupedeck.app import run_agent
from open_loupedeck.config import DeviceConfig, Settings
from open_loupedeck.config_io import save_raw_config
from open_loupedeck.config_state import ConfigState
from open_loupedeck.deck_skin import apply_page_skin
from open_loupedeck.devices.base import DeviceBackend
from open_loupedeck.devices.model import parse_key_id
from open_loupedeck.devices.registry import DeviceRegistry, model_by_name
from open_loupedeck.devices.virtual.backend import MAX_ROTATE_STEPS, VirtualBackend, VirtualBackendFactory
from open_loupedeck.devices.virtual.models import VIRTUAL_15, VIRTUAL_MEGA, VIRTUAL_MINI, VIRTUAL_MODELS
from open_loupedeck.events import ControlEvent
from open_loupedeck.runtime_refs import AgentRuntimeRefs
from open_loupedeck.web_app import create_web_app
from tests.fake_backend import FakeFactory

# --- models ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("model", VIRTUAL_MODELS, ids=lambda m: m.id)
def test_model_is_consistent(model):
    assert model.problems() == []
    assert model.family == "virtual"
    ids = [c.id for c in model.controls]
    assert len(ids) == len(set(ids))
    for c in model.controls:
        p = c.position
        assert p.x >= 0 and p.x + p.w <= model.layout[0] + 1e-9
        assert p.y >= 0 and p.y + p.h <= model.layout[1] + 1e-9
    # overlapping controls would be unusable in the browser
    rects = [(c.id, c.position) for c in model.controls]
    for i, (a, pa) in enumerate(rects):
        for b, pb in rects[i + 1 :]:
            overlap = pa.x < pb.x + pb.w and pb.x < pa.x + pa.w and pa.y < pb.y + pb.h and pb.y < pa.y + pa.h
            assert not overlap, f"{a} overlaps {b}"


@pytest.mark.parametrize("model", VIRTUAL_MODELS, ids=lambda m: m.id)
def test_feedback_is_computed_for_every_non_display_control(model):
    for c in model.controls:
        if c.kind == "key":
            continue
        fb = model.feedback_key_for(c.id)
        assert fb is not None and model.control(fb).has_image


def test_model_contents():
    assert model_by_name("virtual") is VIRTUAL_15 and model_by_name("virtual_mega") is VIRTUAL_MEGA
    assert model_by_name("virtual_mini") is VIRTUAL_MINI
    assert VIRTUAL_15.grid_of_keys() == (5, 3)
    assert len(VIRTUAL_15.ids_of_kind("knob")) == 2 and len(VIRTUAL_15.ids_of_kind("button")) == 4
    assert all(c.led == "rgb" for c in VIRTUAL_15.controls_of_kind("button"))
    assert VIRTUAL_MEGA.grid_of_keys() == (8, 8)
    assert len(VIRTUAL_MEGA.ids_of_kind("button")) == 12 and len(VIRTUAL_MEGA.ids_of_kind("knob")) == 6
    assert VIRTUAL_MEGA.ids_of_kind("slider") == ["slider_0"]
    assert VIRTUAL_MEGA.control("slider_0").has_input("value")
    assert VIRTUAL_MINI.grid_of_keys() == (3, 2) and len(VIRTUAL_MINI.controls) == 6
    # nearest key of the right-hand mega knobs is on the right edge
    near = VIRTUAL_MEGA.feedback_key_for("knob_5")
    assert near is not None and parse_key_id(near)[0] == 7


# --- backend --------------------------------------------------------------------------------------


def _img(color=(255, 0, 0), size=(90, 90)) -> Image.Image:
    return Image.new("RGB", size, color)


def test_backend_satisfies_the_protocol_and_always_opens():
    b = VirtualBackend(VIRTUAL_15)
    assert isinstance(b, DeviceBackend)
    assert not b.is_open
    b.open()
    assert b.is_open and not b.unplugged
    with b:
        b.set_image("key_0_0", _img())
    b.close()
    b.close()  # idempotent
    assert not b.is_open


def test_images_leds_brightness_are_stored_and_mirrored():
    b = VirtualBackend(VIRTUAL_15)
    b.open()
    seen: list[dict[str, Any]] = []
    b.subscribe(seen.append)
    b.set_image("key_1_1", _img((0, 255, 0)))
    b.set_image("key_1_1", _img((0, 255, 0)))  # unchanged: not sent again
    b.set_image("nope", _img())  # unknown control: ignored
    b.set_image("knob_0", _img())  # no image output: ignored
    b.set_led("button_0", (1, 2, 300))
    b.set_led("key_0_0", (1, 2, 3))  # no LED: ignored
    b.set_brightness(250)  # clamped to 100 = unchanged
    b.set_brightness(-5)
    assert [m["t"] for m in seen] == ["image", "led", "brightness"]
    png = b.png_of("key_1_1")
    assert Image.open(io.BytesIO(png)).getpixel((0, 0)) == (0, 255, 0)
    assert base64.b64decode(seen[0]["png"]) == png
    assert b.led_of("button_0") == (1, 2, 255) and b.brightness == 0
    snap = b.snapshot()
    assert snap["t"] == "snapshot" and snap["model"]["id"] == "virtual_15"
    assert set(snap["images"]) == {"key_1_1"} and snap["leds"] == {"button_0": [1, 2, 255]}
    assert [m["id"] for m in snap["models"]] == ["virtual_15", "virtual_mega", "virtual_mini"]


def test_unsubscribe_and_failing_listener_do_not_break_the_backend():
    b = VirtualBackend(VIRTUAL_MINI)
    got: list[dict[str, Any]] = []

    def boom(_m: dict[str, Any]) -> None:
        raise RuntimeError("x")

    b.subscribe(boom)
    off = b.subscribe(got.append)
    b.set_brightness(40)
    off()
    b.set_brightness(30)
    assert len(got) == 1 and b.brightness == 30


def test_events_reach_the_callback_like_hardware():
    b = VirtualBackend(VIRTUAL_MEGA)
    b.open()
    got: list[ControlEvent] = []
    b.set_event_callback(got.append)
    b.inject({"id": "key_7_7", "type": "press"})
    b.inject({"id": "key_7_7", "type": "release"})
    b.inject({"id": "knob_2", "type": "rotate", "value": -1})
    b.inject({"id": "knob_2", "type": "press"})
    b.inject({"id": "slider_0", "type": "value", "value": 0.25})
    assert [(e.control_id, e.type, e.value) for e in got] == [
        ("key_7_7", "press", None),
        ("key_7_7", "release", None),
        ("knob_2", "rotate", -1),
        ("knob_2", "press", None),
        ("slider_0", "value", 0.25),
    ]
    assert got[2].direction == "left"


def test_input_validation():
    b = VirtualBackend(VIRTUAL_MEGA)
    b.open()
    got: list[ControlEvent] = []
    b.set_event_callback(got.append)
    for bad in (
        None,
        "x",
        {},
        {"id": "key_99_99", "type": "press"},  # unknown control
        {"id": 5, "type": "press"},
        {"id": "key_0_0", "type": "rotate", "value": 1},  # key cannot rotate
        {"id": "key_0_0", "type": "value", "value": 1},
        {"id": "key_0_0", "type": "release"},  # release without press
        {"id": "knob_0", "type": "rotate", "value": "a"},
        {"id": "knob_0", "type": "rotate", "value": float("nan")},
        {"id": "knob_0", "type": "rotate", "value": 0},
        {"id": "slider_0", "type": "value", "value": None},
        {"id": "slider_0", "type": "value", "value": True},
        {"id": "slider_0", "type": "press"},
        {"id": "key_0_0", "type": "bogus"},
    ):
        assert b.inject(bad) is None
    assert got == []
    b.inject({"id": "knob_0", "type": "rotate", "value": 9999})
    b.inject({"id": "knob_0", "type": "rotate", "value": -9999})
    b.inject({"id": "slider_0", "type": "value", "value": 7})
    b.inject({"id": "slider_0", "type": "value", "value": -3})
    assert [e.value for e in got] == [MAX_ROTATE_STEPS, -MAX_ROTATE_STEPS, 1.0, 0.0]


def test_touch_is_clamped_to_the_control_pixels():
    from open_loupedeck.devices.loupedeck.models import LOUPEDECK_LIVE

    b = VirtualBackend(LOUPEDECK_LIVE)  # has touch strips
    ev = b.parse_input({"id": "strip_0", "type": "touch", "value": [999, -5]})
    assert ev is not None and ev.value == (59, 0)
    assert b.parse_input({"id": "strip_0", "type": "touch", "value": [1]}) is None


def test_no_events_before_open_or_after_unplug():
    b = VirtualBackend(VIRTUAL_MINI)
    got: list[ControlEvent] = []
    b.set_event_callback(got.append)
    b.inject({"id": "key_0_0", "type": "press"})  # not open yet
    b.open()
    called: list[int] = []
    b.set_unplugged_callback(lambda: called.append(1))
    b.request_unplug()
    b.request_unplug()
    assert called == [1] and b.unplugged and not b.is_open
    b.inject({"id": "key_0_0", "type": "press"})
    assert got == []


# --- registry -------------------------------------------------------------------------------------


def _settings(model: str = "auto") -> Settings:
    return Settings(device=DeviceConfig(model=model))


def _fake_model():
    return dataclasses.replace(VIRTUAL_MINI, id="fake_model", family="fake", config_names=("fake",))


def test_virtual_is_selected_by_name_only():
    reg = DeviceRegistry([FakeFactory("fake", (_fake_model(),)), VirtualBackendFactory()])
    # device.model: virtual* -> virtual backend
    for name, model_id in (
        ("virtual", "virtual_15"),
        ("virtual_mega", "virtual_mega"),
        ("virtual_mini", "virtual_mini"),
    ):
        b = reg.open_backend(_settings(name))
        assert isinstance(b, VirtualBackend) and b.model.id == model_id
    # auto: the real backend wins and the virtual one is never tried
    assert not isinstance(reg.open_backend(_settings("auto")), VirtualBackend)


def test_auto_never_falls_back_to_virtual():
    factory = FakeFactory("fake", (_fake_model(),))
    factory.fail = RuntimeError("No device")
    reg = DeviceRegistry([factory, VirtualBackendFactory()])
    with pytest.raises(RuntimeError, match="No device"):
        reg.open_backend(_settings("auto"))
    # only the virtual backend registered: auto has nothing to open
    with pytest.raises(RuntimeError):
        DeviceRegistry([VirtualBackendFactory()]).open_backend(_settings("auto"))
    assert VirtualBackendFactory().discover() == []


def test_forced_model_flag():
    reg = DeviceRegistry([VirtualBackendFactory()])
    reg.force_model("virtual_mega")
    assert reg.open_backend(_settings("auto")).model.id == "virtual_mega"
    assert reg.open_backend(_settings("live_s")).model.id == "virtual_mega"
    reg.force_model(None)
    with pytest.raises(RuntimeError):
        reg.open_backend(_settings("auto"))


def test_default_registry_knows_the_virtual_models():
    from open_loupedeck.devices.registry import known_models

    ids = {m.id for m in known_models()}
    assert {"virtual_15", "virtual_mega", "virtual_mini", "loupedeck_live_s"} <= ids
    assert DeviceRegistry().model_by_name("virtual_mega").family == "virtual"


def test_no_device_wins_over_virtual(tmp_path: Path):
    from open_loupedeck.app import _async_main
    from open_loupedeck.devices import registry

    cfg = tmp_path / "config.yaml"
    save_raw_config(cfg, {"pages": [{"name": "A", "buttons": {}}]})

    async def go() -> None:
        task = asyncio.create_task(_async_main(cfg, False, None, True, tmp_path, virtual="virtual"))
        await asyncio.sleep(0.3)
        assert registry.default_registry().forced_model is None
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    asyncio.run(go())


# --- web transport --------------------------------------------------------------------------------


@pytest.fixture()
def web(tmp_path: Path):
    cfg = tmp_path / "config.yaml"
    state = ConfigState(cfg)
    backend = VirtualBackend(VIRTUAL_15)
    backend.open()
    rt = AgentRuntimeRefs(deck=backend)
    app = create_web_app(cfg, state, asyncio.Lock(), runtime=rt)
    with TestClient(app) as client:
        yield client, backend, rt


def test_ws_snapshot_updates_and_events(web):
    client, backend, _rt = web
    got: list[ControlEvent] = []
    backend.set_event_callback(got.append)
    backend.set_image("key_0_0", _img((9, 9, 9)))
    with client.websocket_connect("/ws/virtual") as ws, client.websocket_connect("/ws/virtual") as ws2:
        snap = ws.receive_json()
        assert snap["t"] == "snapshot" and snap["model"]["id"] == "virtual_15"
        assert "key_0_0" in snap["images"] and snap["brightness"] == 100
        assert ws2.receive_json()["t"] == "snapshot"  # several tabs
        backend.set_led("button_1", (10, 20, 30))
        backend.set_brightness(55)
        backend.set_image("key_2_2", _img())
        for sock in (ws, ws2):
            msgs = [sock.receive_json() for _ in range(3)]
            assert [m["t"] for m in msgs] == ["led", "brightness", "image"]
            assert msgs[0]["rgb"] == [10, 20, 30] and msgs[1]["value"] == 55
        ws.send_json({"t": "event", "id": "key_1_0", "type": "press"})
        ws.send_json({"t": "event", "id": "ghost", "type": "press"})
        ws.send_text("not json")
        ws.send_json({"t": "event", "id": "knob_1", "type": "rotate", "value": 1000})
        ws.send_json({"t": "event", "id": "key_1_0", "type": "release"})
        for _ in range(100):
            if len(got) >= 3:
                break
            time.sleep(0.02)
    assert [(e.control_id, e.type, e.value) for e in got] == [
        ("key_1_0", "press", None),
        ("knob_1", "rotate", MAX_ROTATE_STEPS),
        ("key_1_0", "release", None),
    ]


def test_ws_disconnect_releases_pressed_controls(web):
    client, backend, _rt = web
    got: list[ControlEvent] = []
    backend.set_event_callback(got.append)
    with client.websocket_connect("/ws/virtual") as ws:
        ws.receive_json()
        ws.send_json({"t": "event", "id": "key_0_0", "type": "press"})
        for _ in range(100):
            if got:
                break
            time.sleep(0.02)
    for _ in range(100):
        if len(got) == 2:
            break
        time.sleep(0.02)
    assert [e.type for e in got] == ["press", "release"]


def test_ws_without_virtual_device_is_refused(tmp_path: Path):
    cfg = tmp_path / "config.yaml"
    app = create_web_app(cfg, ConfigState(cfg), asyncio.Lock(), runtime=AgentRuntimeRefs(no_device=True))
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect) as exc, client.websocket_connect("/ws/virtual") as ws:
        ws.receive_json()
    assert exc.value.code == 1013
    assert client.get("/api/virtual/state").status_code == 404
    assert client.post("/api/virtual/model", json={"model": "virtual_mini"}).status_code == 409


def test_ws_gets_bye_when_the_device_restarts(web):
    client, backend, _rt = web
    with client.websocket_connect("/ws/virtual") as ws:
        ws.receive_json()
        backend.request_unplug()
        assert ws.receive_json() == {"t": "bye", "reason": "restart"}
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 1012


def test_http_state_and_model_switch(web):
    client, backend, _rt = web
    backend.set_image("key_0_0", _img())
    st = client.get("/api/virtual/state").json()
    assert st["model"]["id"] == "virtual_15" and "key_0_0" in st["images"]
    assert client.post("/api/virtual/model", json={"model": "loupedeck_live_s"}).status_code == 400
    assert client.post("/api/virtual/model", json={}).status_code == 400
    unplugged: list[int] = []
    backend.set_unplugged_callback(lambda: unplugged.append(1))
    from open_loupedeck.devices import registry

    try:
        r = client.post("/api/virtual/model", json={"model": "virtual_mega"})
        assert r.status_code == 200 and r.json()["model"] == "virtual_mega"
        assert unplugged == [1]
        assert registry.default_registry().forced_model == "virtual_mega"
        assert registry.open_backend(_settings("auto")).model.id == "virtual_mega"
    finally:
        registry.force_model(None)


def test_static_page_is_served(web):
    client, _b, _rt = web
    r = client.get("/assets/ui/virtual.html")
    assert r.status_code == 200 and "virtual" in r.text
    assert client.get("/assets/ui/js/virtual/device.js").status_code == 200


# --- full flow: agent + virtual backend + WebSocket -----------------------------------------------


def test_press_over_websocket_changes_the_page_and_pushes_images(tmp_path: Path):
    cfg = tmp_path / "config.yaml"
    save_raw_config(
        cfg,
        {
            "config_version": 2,
            "device": {"model": "virtual"},
            "brightness": 60,
            "global": {},
            "pages": [
                {
                    "name": "Home",
                    "controls": {
                        "key_0_0": {"text": "GO", "action": {"type": "agent.goto_page", "index": 1}},
                        "key_1_0": {"text": "HOME"},
                    },
                },
                {
                    "name": "Second",
                    "controls": {"key_0_0": {"text": "BACK", "action": {"type": "agent.goto_page", "index": 0}}},
                },
            ],
        },
    )
    state = ConfigState(cfg)
    backend = VirtualBackend(VIRTUAL_15)
    runtime = AgentRuntimeRefs(deck=backend)
    ready = threading.Event()
    loop_box: dict[str, Any] = {}

    async def agent() -> None:
        lock = asyncio.Lock()

        async def redraw(_reason: str = "") -> None:
            pages = state.raw["pages"]
            idx = state.page_index % len(pages)
            await asyncio.to_thread(
                apply_page_skin, backend, pages[idx], tmp_path, state.raw.get("global") or {}, page_index=idx
            )

        loop_box["task"] = asyncio.current_task()
        task = asyncio.create_task(run_agent(state, lock, redraw, runtime))
        loop_box["agent"] = task
        loop_box["redraw"] = redraw
        for _ in range(300):
            if runtime.simulate_event is not None:
                break
            await asyncio.sleep(0.01)
        await redraw("startup")
        ready.set()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    def run() -> None:
        loop = asyncio.new_event_loop()
        loop_box["loop"] = loop
        loop.run_until_complete(agent())

    th = threading.Thread(target=run, daemon=True)
    th.start()
    assert ready.wait(10)
    try:
        app = create_web_app(cfg, state, asyncio.Lock(), runtime=runtime)
        with TestClient(app) as client, client.websocket_connect("/ws/virtual") as ws:
            snap = ws.receive_json()
            assert snap["model"]["id"] == "virtual_15" and snap["brightness"] == 60
            assert {"key_0_0", "key_1_0", "key_4_2"} <= set(snap["images"])  # every key was drawn
            before = base64.b64decode(snap["images"]["key_0_0"])
            assert state.page_index == 0

            ws.send_json({"t": "event", "id": "key_0_0", "type": "press"})
            ws.send_json({"t": "event", "id": "key_0_0", "type": "release"})
            updates: dict[str, bytes] = {}
            deadline = time.time() + 10
            while "key_0_0" not in updates and time.time() < deadline:
                m = ws.receive_json()
                if m["t"] == "image":
                    updates[m["id"]] = base64.b64decode(m["png"])
            assert state.page_index == 1
            assert updates["key_0_0"] != before  # "BACK" replaced "GO"
            assert backend.png_of("key_0_0") == updates["key_0_0"]
    finally:
        loop = loop_box["loop"]
        loop.call_soon_threadsafe(loop_box["agent"].cancel)
        th.join(5)
