"""Screen brightness: pure time-window / clamping logic, controller with a fake clock, config, API, actions."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, time
from types import SimpleNamespace

import pytest

from open_loupedeck.config_io import default_raw_config, ensure_minimal_structure
from open_loupedeck.deck_brightness import (
    DeckBrightness,
    clamp_level,
    in_window,
    normalize_night,
    parse_hhmm,
)

NIGHT = {"enabled": True, "from": "22:00", "to": "07:00", "level": 20}


class FakeDeck:
    def __init__(self) -> None:
        self.levels: list[int] = []

    def set_brightness(self, pct: int) -> None:
        self.levels.append(pct)


class Clock:
    def __init__(self, hour: int = 12, minute: int = 0) -> None:
        self.t = 0.0
        self.when = datetime(2026, 1, 1, hour, minute, tzinfo=UTC)

    def mono(self) -> float:
        return self.t

    def now(self) -> datetime:
        return self.when

    def at(self, hour: int, minute: int = 0) -> None:
        self.when = datetime(2026, 1, 1, hour, minute, tzinfo=UTC)


def make(level=80, night=None, hour=12):
    clock = Clock(hour)
    deck = FakeDeck()
    saved: list[tuple[int, dict]] = []
    ctl = DeckBrightness(
        SimpleNamespace(deck=deck),
        lambda lv, n: saved.append((lv, n)),
        level=level,
        night=night,
        now=clock.now,
        clock=clock.mono,
    )
    return ctl, clock, deck, saved


def test_clamp_level_tolerates_junk():
    assert clamp_level(55) == 55
    assert clamp_level(-5) == 0
    assert clamp_level(250) == 100
    assert clamp_level("70") == 70
    assert clamp_level(True) == 80
    assert clamp_level(None) == 80
    assert clamp_level("loud", 33) == 33
    assert clamp_level(float("nan")) == 80


def test_parse_hhmm():
    assert parse_hhmm("22:00") == time(22, 0)
    assert parse_hhmm(" 7:05 ") == time(7, 5)
    for bad in ("24:00", "12:60", "noon", "", None, 7, "12"):
        assert parse_hhmm(bad) is None


def test_normalize_night_defaults_and_junk():
    assert normalize_night(None) == {"enabled": False, "from": "22:00", "to": "07:00", "level": 20}
    out = normalize_night({"enabled": "yes", "from": "25:00", "to": "6:30", "level": 500})
    assert out == {"enabled": False, "from": "22:00", "to": "06:30", "level": 100}


def test_in_window_same_day_and_across_midnight():
    assert in_window(time(13), time(12), time(14))
    assert not in_window(time(14), time(12), time(14))  # end is exclusive
    assert in_window(time(23), time(22), time(7))
    assert in_window(time(3), time(22), time(7))
    assert in_window(time(22), time(22), time(7))
    assert not in_window(time(7), time(22), time(7))
    assert not in_window(time(12), time(22), time(7))
    assert not in_window(time(5), time(5), time(5))  # empty window


def test_effective_level_follows_the_window():
    ctl, clock, _, _ = make(80, NIGHT, hour=12)
    assert ctl.effective_level() == 80
    clock.at(23, 30)
    assert ctl.effective_level() == 20
    clock.at(6, 59)
    assert ctl.effective_level() == 20
    clock.at(7, 0)
    assert ctl.effective_level() == 80
    ctl.update_night({"enabled": False})
    clock.at(23)
    assert ctl.effective_level() == 80


def test_apply_sends_effective_level_and_ignores_errors_and_no_device():
    ctl, _, deck, _ = make(60)
    assert ctl.apply() == 60
    assert deck.levels == [60]

    class Broken:
        def set_brightness(self, pct):
            raise OSError("unplugged")

    DeckBrightness(SimpleNamespace(deck=Broken())).apply()
    DeckBrightness(SimpleNamespace(deck=None)).apply()
    DeckBrightness(SimpleNamespace(deck=object())).apply()


def test_set_clamps_and_applies():
    ctl, _, deck, _ = make(80)
    assert ctl.set(130) == 100
    assert ctl.set(-3) == 0
    assert deck.levels == [100, 0]
    assert ctl.level == 0


def test_delta_edits_day_level_outside_the_window_and_night_level_inside():
    ctl, clock, deck, _ = make(80, NIGHT, hour=12)
    assert ctl.delta(-10) == 70
    assert (ctl.level, ctl.night["level"]) == (70, 20)
    clock.at(23)
    assert ctl.delta(+30) == 50
    assert (ctl.level, ctl.night["level"]) == (70, 50)
    assert ctl.delta(+100) == 100
    assert ctl.delta(-500) == 0
    assert deck.levels[-1] == 0
    assert ctl.delta("junk") == 0  # ignored


def test_persistence_is_debounced():
    ctl, clock, _, saved = make(80)
    ctl.delta(-10)
    clock.t = 0.4
    ctl.delta(-10)  # restarts the debounce
    clock.t = 1.2
    ctl.tick()
    assert saved == []
    clock.t = 1.5
    ctl.tick()
    assert saved == [(60, {**normalize_night(None)})]
    clock.t = 5
    ctl.tick()
    assert len(saved) == 1  # nothing new to save


def test_flush_saves_immediately_and_only_once():
    ctl, _, _, saved = make(80)
    ctl.flush()
    assert saved == []
    ctl.set(10)
    ctl.flush()
    ctl.flush()
    assert len(saved) == 1 and saved[0][0] == 10


def test_loop_reevaluates_every_30_seconds():
    ctl, clock, deck, _ = make(80, NIGHT, hour=21)
    ctl.apply()
    assert deck.levels == [80]
    clock.at(22, 0)
    clock.t = 10
    ctl.tick()
    assert deck.levels == [80]  # not yet
    clock.t = 31
    ctl.tick()
    assert deck.levels == [80, 20]
    clock.t = 70
    ctl.tick()
    assert deck.levels == [80, 20]  # unchanged: no resend


def test_update_night_keeps_valid_parts_and_rejects_bad_times():
    ctl, _, _, _ = make(80)
    ctl.update_night({"enabled": True, "from": "23:15", "to": "bogus", "level": 35})
    assert ctl.night == {"enabled": True, "from": "23:15", "to": "07:00", "level": 35}


def test_run_loop_flushes_on_cancel():
    ctl, _, _, saved = make(80)

    async def go():
        task = asyncio.create_task(ctl.run(interval=0.01))
        ctl.set(40)
        await asyncio.sleep(0.03)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(go())
    assert saved and saved[-1][0] == 40


# --- config -----------------------------------------------------------------------------------


def test_config_defaults_and_validation():
    d = default_raw_config()
    assert d["brightness"] == 80
    assert d["brightness_night"] == {"enabled": False, "from": "22:00", "to": "07:00", "level": 20}
    out = ensure_minimal_structure({"brightness": "900", "brightness_night": "nope"})
    assert out["brightness"] == 100
    assert out["brightness_night"]["enabled"] is False
    out = ensure_minimal_structure({"brightness_night": {"enabled": True, "from": "9", "level": -4}})
    assert out["brightness_night"] == {"enabled": True, "from": "22:00", "to": "07:00", "level": 0}
    assert ensure_minimal_structure({})["brightness"] == 80


# --- actions ----------------------------------------------------------------------------------


def test_brightness_actions():
    import open_loupedeck.actions  # noqa: F401
    from open_loupedeck.actions.registry import ActionContext, run_actions

    ctl, _, deck, _ = make(50)
    ctx = ActionContext(obs=None, http_client=None, log=__import__("logging").getLogger("t"), deck_brightness=ctl)
    asyncio.run(run_actions(ctx, [{"type": "deck.brightness_delta", "delta": 20}]))
    assert ctl.level == 70
    asyncio.run(run_actions(ctx, [{"type": "deck.brightness_set", "percent": 10}]))
    assert deck.levels == [70, 10]


def test_screen_brightness_duo():
    from open_loupedeck.knob_duos import duo_feedback, expand_duo

    assert expand_duo("screen_brightness", {}, "left") == [{"type": "deck.brightness_delta", "delta": -10}]
    assert expand_duo("screen_brightness", {"step": 5}, "right") == [{"type": "deck.brightness_delta", "delta": 5}]
    assert duo_feedback("screen_brightness", {"step": 5}, "right", "en") == "Brightness +5"


# --- API --------------------------------------------------------------------------------------


@pytest.fixture
def client(tmp_path):
    from fastapi.testclient import TestClient

    from open_loupedeck.config_state import ConfigState
    from open_loupedeck.runtime_refs import AgentRuntimeRefs
    from open_loupedeck.web_app import create_web_app

    path = tmp_path / "config.yaml"
    state = ConfigState(path)
    rt = AgentRuntimeRefs()
    rt.deck = FakeDeck()
    app = create_web_app(path, state, asyncio.Lock(), runtime=rt)
    return TestClient(app), rt, state


def test_api_get_put_and_config_autosave_does_not_revert(client):
    c, rt, state = client
    r = c.get("/api/brightness")
    assert r.status_code == 200 and r.json()["level"] == 80
    r = c.put("/api/brightness", json={"level": 40, "night": {"enabled": True, "level": 10}})
    assert r.status_code == 200
    body = r.json()
    assert body["level"] == 40 and body["night"]["enabled"] is True and body["night"]["level"] == 10
    assert rt.deck.levels  # applied immediately
    # A stale full-config autosave must not revert the brightness.
    stale = dict(state.raw)
    stale["brightness"] = 99
    stale["brightness_night"] = {"enabled": False}
    assert c.put("/api/config", json=stale).status_code == 200
    assert c.get("/api/brightness").json()["level"] == 40
    assert state.raw["brightness"] == 40
    assert state.raw["brightness_night"]["enabled"] is True


@pytest.mark.parametrize(
    "body",
    [
        {"level": 120},
        {"level": "x"},
        {"level": True},
        {"night": "x"},
        {"night": {"from": "99:99"}},
        {"night": {"level": -1}},
    ],
)
def test_api_rejects_bad_input(client, body):
    c, _, _ = client
    r = c.put("/api/brightness", json=body)
    assert r.status_code == 400
    assert not r.json()["detail"].startswith("error.")  # translated, not a raw key
