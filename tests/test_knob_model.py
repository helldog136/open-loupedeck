"""Knob roles per deck page: schema, duo catalogue, legacy knob_pages migration, runtime dispatch."""

from __future__ import annotations

import asyncio
import copy
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

from open_loupedeck import i18n
from open_loupedeck.actions.builtins import next_scene_name
from open_loupedeck.actions.registry import register_handler
from open_loupedeck.config_io import ensure_minimal_structure, load_raw_config, save_raw_config
from open_loupedeck.config_state import ConfigState
from open_loupedeck.knob_duos import (
    KNOB_DUOS,
    duo_feedback,
    expand_duo,
    get_duo,
    list_duos,
    match_duo,
    missing_params,
)
from open_loupedeck.knob_flash import flash_knob_feedback
from open_loupedeck.knob_pages import KNOB_ENCODER_IDS, feedback_duration_sec
from open_loupedeck.knob_roles import (
    LEGACY_KEY,
    effective_model,
    feedback_touch_key,
    migrate_legacy_knob_pages,
    resolve_knob_event,
    validate_knobs_config,
)
from open_loupedeck.runtime_refs import AgentRuntimeRefs
from open_loupedeck.web_app import create_web_app

ROOT = Path(__file__).resolve().parent.parent

# The knob block that config.example.yaml documented before the per-page model (verbatim).
LEGACY_EXAMPLE_KNOBS = yaml.safe_load(
    """
knob_page_feedback:
  duration_sec: 2
knob_pages:
  knobTL:
    pages:
      - name: "Volume"
        rotate_left: { type: sound.volume_delta, delta: -2 }
        rotate_right: { type: sound.volume_delta, delta: 2 }
      - name: "Deck page"
        rotate_left: { type: agent.prev_page }
        rotate_right: { type: agent.next_page }
  knobCL:
    pages:
      - name: "Scroll"
        rotate_left: { type: command.run, argv: ["xdotool", "click", "4"] }
        rotate_right: { type: command.run, argv: ["xdotool", "click", "5"] }
"""
)


def _legacy_config(model: str = "live_s") -> dict[str, Any]:
    raw = load_raw_config(ROOT / "config.example.yaml")
    raw.update(copy.deepcopy(LEGACY_EXAMPLE_KNOBS))
    raw.setdefault("device", {})["model"] = model
    raw["pages"] = [*(raw.get("pages") or []), {"name": "Second", "buttons": {}}]
    return raw


@pytest.fixture(autouse=True)
def _english():
    before = i18n.get_language()
    i18n.set_language("en")
    yield
    i18n.set_language(before)


# --- duo catalogue ----------------------------------------------------------------------------


def test_catalogue_covers_the_required_duos():
    ids = {d.id for d in KNOB_DUOS}
    for required in (
        "system_volume",
        "obs_input_volume",
        "ha_light_brightness",
        "spotify_volume",
        "spotify_track",
        "obs_scene",
        "deck_page",
        "keyboard_up_down",
    ):
        assert required in ids


def test_every_duo_action_type_is_registered():
    import open_loupedeck.actions  # noqa: F401
    from open_loupedeck.actions.registry import registered_action_kinds

    kinds = set(registered_action_kinds())
    for d in KNOB_DUOS:
        for side in ("left", "right"):
            params = {p.name: "x" if p.kind == "text" else 3 for p in d.params}
            for act in expand_duo(d.id, params, side):
                assert act["type"] in kinds, (d.id, act)


def test_every_duo_has_label_and_feedback_in_every_language():
    for lang in ("en", "fr"):
        msgs = i18n.messages_for(lang)
        for d in KNOB_DUOS:
            for key in (d.label_key, d.side_key("left"), d.side_key("right")):
                assert key in msgs, (lang, key)
            for p in d.params:
                assert p.label_key in msgs
            assert f"category.{d.category}" in msgs


def test_expand_volume_duo_with_step_and_defaults():
    assert expand_duo("system_volume", {"step": 3}, "left") == [{"type": "sound.volume_delta", "delta": -3}]
    assert expand_duo("system_volume", {}, "right") == [{"type": "sound.volume_delta", "delta": 5}]
    # clamped to the schema (1..25) and non-numbers fall back to the default
    assert expand_duo("system_volume", {"step": 500}, "right") == [{"type": "sound.volume_delta", "delta": 25}]
    assert expand_duo("system_volume", {"step": "abc"}, "left") == [{"type": "sound.volume_delta", "delta": -5}]


def test_expand_obs_and_ha_duos_fill_text_and_nested_params():
    assert expand_duo("obs_input_volume", {"input_name": "Mic/Aux", "step": 2}, "left") == [
        {"type": "obs.input_volume_delta", "input_name": "Mic/Aux", "delta": -2}
    ]
    assert expand_duo("ha_light_brightness", {"entity_id": "light.desk"}, "right") == [
        {
            "type": "ha.call_service",
            "domain": "light",
            "service": "turn_on",
            "entity_id": "light.desk",
            "data": {"brightness_step_pct": 10},
        }
    ]
    assert missing_params(get_duo("ha_light_brightness"), {}) == ["entity_id"]
    assert expand_duo("spotify_track", None, "left") == [{"type": "spotify.previous"}]
    assert expand_duo("nope", {}, "left") == []


def test_duo_feedback_is_translated():
    assert duo_feedback("system_volume", {"step": 5}, "right") == "Volume +5"
    assert duo_feedback("system_volume", {"step": 5}, "left", "fr") == "Volume −5"
    assert duo_feedback("spotify_track", {}, "right", "fr") == "Piste suivante"
    assert duo_feedback("obs_input_volume", {"input_name": "Mic"}, "left") == "Mic −5"


def test_match_duo_recognises_expansions():
    for d in KNOB_DUOS:
        params = {p.name: ("Mic" if p.kind == "text" else 4) for p in d.params}
        left, right = expand_duo(d.id, params, "left"), expand_duo(d.id, params, "right")
        hit = match_duo(left, right)
        assert hit is not None
        assert expand_duo(hit[0], hit[1], "left") == left
    assert (
        match_duo([{"type": "sound.volume_delta", "delta": -2}], [{"type": "sound.volume_delta", "delta": 3}]) is None
    )
    assert match_duo([{"type": "command.run", "argv": ["a"]}], [{"type": "command.run", "argv": ["b"]}]) is None


def test_next_scene_name_wraps_and_handles_unknown_current():
    names = ["A", "B", "C"]
    assert next_scene_name(names, "B", 1) == "C"
    assert next_scene_name(names, "C", 1) == "A"
    assert next_scene_name(names, "A", -1) == "C"
    assert next_scene_name(names, "A", -1, wrap=False) is None
    assert next_scene_name(names, "?", 1) == "A"
    assert next_scene_name([], "A", 1) is None


def test_api_knob_duos_lists_translated_labels(tmp_path: Path):
    cfg = tmp_path / "config.yaml"
    client = TestClient(create_web_app(cfg, ConfigState(cfg), asyncio.Lock()))
    body = client.get("/api/knob_duos", params={"lang": "fr"}).json()
    assert body["lang"] == "fr"
    by_id = {d["id"]: d for d in body["duos"]}
    assert by_id["system_volume"]["label"] == "Volume du PC"
    assert by_id["system_volume"]["right_label"] == "Volume +5"
    assert by_id["system_volume"]["category_key"] == "category.sound"
    assert by_id["obs_input_volume"]["params"][0]["name"] == "input_name"
    assert by_id["system_volume"]["right"] == [{"type": "sound.volume_delta", "delta": {"param": "step", "sign": 1}}]
    assert len(list_duos("en")) == len(body["duos"])


# --- schema -----------------------------------------------------------------------------------


def _pages_with(knobs: Any) -> dict[str, Any]:
    return {"pages": [{"name": "P", "buttons": {}, "knobs": knobs}]}


def test_valid_knobs_schema():
    raw = _pages_with(
        {
            "knobTL": {
                "rotate": {"duo": "system_volume", "params": {"step": 5}},
                "press": {"type": "sound.mute_toggle"},
            },
            "knobCL": {
                "rotate": {"left": {"type": "agent.prev_page"}, "right": [{"type": "agent.next_page"}]},
                "press": None,
                "feedback_sec": 1.5,
            },
            "knobBL": None,
        }
    )
    assert validate_knobs_config(raw) == []
    # A required param still empty is allowed (autosave while typing).
    assert validate_knobs_config(_pages_with({"knobTL": {"rotate": {"duo": "obs_input_volume"}}})) == []


@pytest.mark.parametrize(
    "knobs, fragment",
    [
        ([], "must be an object"),
        ({"knobXX": {}}, "unknown knob"),
        ({"knobTL": "volume"}, "must be an object"),
        ({"knobTL": {"rotate": {"duo": "nope"}}}, "unknown duo"),
        ({"knobTL": {"rotate": {"duo": "system_volume", "left": {"type": "a"}}}}, "not both"),
        ({"knobTL": {"rotate": {"duo": "system_volume", "params": {"step": "big"}}}}, "must be a number"),
        ({"knobTL": {"rotate": {"duo": "system_volume", "params": [1]}}}, "params must be an object"),
        ({"knobTL": {"rotate": {"left": {"delta": 1}}}}, "type must be a non-empty string"),
        ({"knobTL": {"press": "mute"}}, "must be an action object"),
        ({"knobTL": {"feedback_sec": 9}}, "feedback_sec"),
    ],
)
def test_invalid_knobs_schema(knobs: Any, fragment: str):
    errors = validate_knobs_config(_pages_with(knobs))
    assert errors and any(fragment in e for e in errors), errors


def test_put_config_validates_and_round_trips_knobs(tmp_path: Path):
    cfg = tmp_path / "config.yaml"
    state = ConfigState(cfg)
    client = TestClient(create_web_app(cfg, state, asyncio.Lock()))
    raw = client.get("/api/config").json()
    assert "knob_pages" not in raw
    raw["pages"][0]["knobs"] = {"knobTL": {"rotate": {"duo": "spotify_volume", "params": {"step": 10}}}}
    assert client.put("/api/config", json=raw).status_code == 200
    again = client.get("/api/config").json()
    assert again["pages"][0]["knobs"] == raw["pages"][0]["knobs"]
    assert load_raw_config(cfg)["pages"][0]["knobs"] == raw["pages"][0]["knobs"]

    raw["pages"][0]["knobs"] = {"knobTL": {"rotate": {"duo": "no_such_duo"}}}
    r = client.put("/api/config", json=raw)
    assert r.status_code == 400
    assert "no_such_duo" in r.json()["detail"]
    assert load_raw_config(cfg)["pages"][0]["knobs"]["knobTL"]["rotate"]["duo"] == "spotify_volume"


# --- migration --------------------------------------------------------------------------------


def test_migration_from_config_example():
    raw = _legacy_config()
    original_kp = copy.deepcopy(raw["knob_pages"])
    out = ensure_minimal_structure(raw)
    assert "knob_pages" not in out
    assert out[LEGACY_KEY] == original_kp
    assert out["knob_page_feedback"] == {"duration_sec": 2}
    assert len(out["pages"]) >= 2
    for page in out["pages"]:
        # first knob page "Volume" (delta ±2) is recognised as the system volume duo
        assert page["knobs"]["knobTL"] == {"rotate": {"duo": "system_volume", "params": {"step": 2}}}
        # "Scroll" with command.run is not a duo: split left / right, actions verbatim
        assert page["knobs"]["knobCL"] == {
            "rotate": {
                "left": [{"type": "command.run", "argv": ["xdotool", "click", "4"]}],
                "right": [{"type": "command.run", "argv": ["xdotool", "click", "5"]}],
            }
        }
    assert validate_knobs_config(out) == []


def test_migration_is_idempotent_and_survives_save_load(tmp_path: Path):
    once = ensure_minimal_structure(_legacy_config())
    twice = ensure_minimal_structure(once)
    assert twice == once
    assert migrate_legacy_knob_pages(copy.deepcopy(once)) is False
    path = tmp_path / "config.yaml"
    save_raw_config(path, once)
    assert ensure_minimal_structure(load_raw_config(path)) == once


def test_migration_does_not_overwrite_existing_roles_or_legacy_data():
    raw = _legacy_config()
    raw["pages"][0]["knobs"] = {"knobTL": {"rotate": {"duo": "deck_page"}}}
    raw[LEGACY_KEY] = {"knobTL": {"pages": [{"name": "older"}]}}
    assert migrate_legacy_knob_pages(raw) is True
    assert raw["pages"][0]["knobs"]["knobTL"] == {"rotate": {"duo": "deck_page"}}
    assert raw["pages"][1]["knobs"]["knobTL"]["rotate"]["duo"] == "system_volume"
    assert raw[LEGACY_KEY]["knobTL"] == {"pages": [{"name": "older"}]}
    assert raw[LEGACY_KEY]["knobTL_2"] == LEGACY_EXAMPLE_KNOBS["knob_pages"]["knobTL"]


def test_migration_keeps_knob_pages_when_there_are_no_deck_pages():
    raw = {"knob_pages": copy.deepcopy(LEGACY_EXAMPLE_KNOBS["knob_pages"]), "device": {"model": "auto"}}
    out = ensure_minimal_structure(raw)
    assert out["knob_pages"] == LEGACY_EXAMPLE_KNOBS["knob_pages"]
    assert LEGACY_KEY not in out


def test_migration_drops_empty_and_keeps_malformed_knob_pages():
    out = ensure_minimal_structure({"knob_pages": {}, "pages": [{"name": "A", "buttons": {}}]})
    assert "knob_pages" not in out and LEGACY_KEY not in out
    out = ensure_minimal_structure({"knob_pages": ["junk"], "pages": [{"name": "A", "buttons": {}}]})
    assert out[LEGACY_KEY] == {"_unparsed": ["junk"]}


# --- resolution -------------------------------------------------------------------------------

ROLES = {
    "device": {"model": "live_s"},
    "pages": [
        {
            "name": "Main",
            "buttons": {},
            "knobs": {
                "knobTL": {
                    "rotate": {"duo": "system_volume", "params": {"step": 5}},
                    "press": {"type": "sound.mute_toggle"},
                },
            },
        },
        {
            "name": "Music",
            "buttons": {},
            "knobs": {
                "knobTL": {"rotate": {"duo": "spotify_track"}, "feedback_sec": 0.5},
                "knobCL": {"rotate": {"left": {"type": "agent.prev_page"}, "right": {"type": "spotify.next"}}},
            },
        },
        {"name": "Empty", "buttons": {}},
    ],
}


def test_roles_differ_per_page():
    r0 = resolve_knob_event(ROLES, 0, "knobTL", "right")
    assert r0.actions == [{"type": "sound.volume_delta", "delta": 5}]
    assert r0.feedback == "Volume +5"
    assert r0.feedback_sec is None
    r1 = resolve_knob_event(ROLES, 1, "knobTL", "left")
    assert r1.actions == [{"type": "spotify.previous"}]
    assert r1.feedback == "Previous track"
    assert r1.feedback_sec == 0.5
    # page index wraps like the deck does
    assert resolve_knob_event(ROLES, 3, "knobTL", "right").actions == r0.actions


def test_press_is_independent_and_split_rotation_uses_action_labels():
    press = resolve_knob_event(ROLES, 0, "knobTL", "press")
    assert press.actions == [{"type": "sound.mute_toggle"}]
    assert press.feedback == i18n.t("action.sound.mute_toggle.label")
    split = resolve_knob_event(ROLES, 1, "knobCL", "right")
    assert split.actions == [{"type": "spotify.next"}]
    assert split.feedback == i18n.t("action.spotify.next.label")


def test_no_role_is_a_noop():
    assert resolve_knob_event(ROLES, 2, "knobTL", "left") is None  # page without knobs
    assert resolve_knob_event(ROLES, 0, "knobCL", "left") is None  # knob without role
    assert resolve_knob_event(ROLES, 1, "knobTL", "press") is None  # no press action
    assert resolve_knob_event({"pages": []}, 0, "knobTL", "left") is None


def test_duo_missing_required_param_runs_nothing_but_says_so():
    raw = _pages_with({"knobTL": {"rotate": {"duo": "obs_input_volume"}}})
    res = resolve_knob_event(raw, 0, "knobTL", "right")
    assert res.actions == []
    assert res.feedback == "OBS source volume: needs setup"


# --- feedback target key + duration ------------------------------------------------------------


def test_feedback_touch_key_per_model():
    assert feedback_touch_key("knobTL", "live_s") == "touch_0"
    assert feedback_touch_key("knobCL", "live_s") == "touch_5"
    assert feedback_touch_key("knobBL", "live_s") is None
    assert feedback_touch_key("knobCL", "live") == "touch_4"
    assert feedback_touch_key("knobBR", "live") == "touch_11"
    assert {feedback_touch_key(k, "live") for k in KNOB_ENCODER_IDS} == {
        "touch_0",
        "touch_4",
        "touch_8",
        "touch_3",
        "touch_7",
        "touch_11",
    }


def test_effective_model_from_driver_class():
    class LoupedeckLive:  # same names as the real driver classes
        pass

    class LoupedeckLiveS:
        pass

    assert effective_model("auto", LoupedeckLive()) == "live"
    assert effective_model("auto", LoupedeckLiveS()) == "live_s"
    assert effective_model("live", LoupedeckLiveS()) == "live"
    assert effective_model("auto", None) == "auto"


def test_feedback_duration_accepts_zero_to_two_seconds():
    assert feedback_duration_sec({}) == 2.0
    assert feedback_duration_sec({"knob_page_feedback": {"duration_sec": 0}}) == 0.0
    assert feedback_duration_sec({"knob_page_feedback": {"duration_sec": 1.5}}) == 1.5
    assert feedback_duration_sec({"knob_page_feedback": {"duration_sec": 9}}) == 2.0


class FakeDeck:
    def __init__(self) -> None:
        self.images: list[str] = []
        self.started = False
        self.callback = None

    def __enter__(self) -> FakeDeck:
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def set_key_image(self, key: str, _image: Any) -> None:
        self.images.append(key)

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.started = False

    def set_callback(self, cb: Any) -> None:
        self.callback = cb


def test_flash_draws_on_neighbour_and_only_latest_restores(tmp_path: Path):
    deck = FakeDeck()
    redraws: list[str] = []

    async def redraw(reason: str = "") -> None:
        redraws.append(reason)

    async def go() -> list[Any]:
        return await asyncio.gather(
            flash_knob_feedback(deck, tmp_path, {}, "live_s", "knobCL", "Volume +5", redraw, 0.05),
            flash_knob_feedback(deck, tmp_path, {}, "live_s", "knobCL", "Volume +10", redraw, 0.1),
        )

    assert asyncio.run(go()) == ["touch_5", "touch_5"]
    assert deck.images == ["5", "5"]
    assert redraws == ["knob_feedback_restore"]  # the first flash did not wipe the second one

    deck.images.clear()
    assert asyncio.run(flash_knob_feedback(deck, tmp_path, {}, "live_s", "knobTL", "x", redraw, 0)) is None
    assert deck.images == []


# --- end to end through the agent's encoder handler (simulated device messages) ----------------


def _run_agent_with(tmp_path: Path, raw: dict[str, Any], messages: list[dict[str, Any]], page_index: int = 0):
    from open_loupedeck.app import run_agent

    recorded: list[dict[str, Any]] = []

    async def _record(_ctx: Any, params: dict[str, Any]) -> None:
        recorded.append(params)

    register_handler("test.knob_record", _record)
    cfg = tmp_path / "config.yaml"
    save_raw_config(cfg, raw)
    state = ConfigState(cfg)
    state.page_index = page_index
    deck = FakeDeck()
    runtime = AgentRuntimeRefs(deck=deck, no_device=True)
    redraws: list[str] = []

    async def redraw(reason: str = "") -> None:
        redraws.append(reason)

    async def go() -> None:
        task = asyncio.create_task(run_agent(state, asyncio.Lock(), redraw, runtime))
        for _ in range(200):
            if runtime.simulate_raw_message is not None:
                break
            await asyncio.sleep(0.01)
        assert runtime.simulate_raw_message is not None
        for msg in messages:
            await runtime.simulate_raw_message(msg)
        await asyncio.sleep(0.3)  # let background feedback flashes draw and restore
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(go())
    return recorded, deck, redraws, state


def _rec(tag: str) -> dict[str, Any]:
    return {"type": "test.knob_record", "tag": tag}


def test_agent_runs_role_of_current_page_and_flashes_neighbour(tmp_path: Path):
    raw = {
        "device": {"model": "live_s"},
        "knob_page_feedback": {"duration_sec": 0.01},
        "pages": [
            {
                "name": "A",
                "buttons": {},
                "knobs": {"knobCL": {"rotate": {"left": _rec("A-left"), "right": _rec("A-right")}}},
            },
            {
                "name": "B",
                "buttons": {},
                "knobs": {
                    "knobCL": {"rotate": {"left": _rec("B-left"), "right": _rec("B-right")}, "press": _rec("B-press")}
                },
            },
        ],
    }
    msgs = [
        {"action": "rotate", "state": "right", "id": "knobCL"},
        {"action": "push", "state": "down", "id": "knobCL"},
        {"action": "rotate", "state": "left", "id": "knobTL"},  # no role: no-op
    ]
    recorded, deck, redraws, _ = _run_agent_with(tmp_path, raw, msgs, page_index=1)
    assert [r["tag"] for r in recorded] == ["B-right", "B-press"]
    assert deck.images == ["5", "5"]  # Live S: knobCL -> touch_5
    assert redraws.count("knob_feedback_restore") >= 1  # overlapping flashes restore once


def test_agent_legacy_config_is_migrated_and_keeps_rotating(tmp_path: Path):
    raw = {
        "device": {"model": "live_s"},
        "knob_page_feedback": {"duration_sec": 0},
        "knob_pages": {
            "knobTL": {
                "pages": [
                    {"name": "Rec", "rotate_left": _rec("L"), "rotate_right": [_rec("R")]},
                    {"name": "Other", "rotate_left": _rec("other")},
                ]
            }
        },
        "pages": [{"name": "A", "buttons": {}}, {"name": "B", "buttons": {}}],
    }
    msgs = [
        {"action": "rotate", "state": "left", "id": "knobTL"},
        {"action": "push", "state": "down", "id": "knobTL"},  # legacy push cycled pages; now no press role
        {"action": "rotate", "state": "right", "id": "knobTL"},
    ]
    recorded, deck, _, state = _run_agent_with(tmp_path, raw, msgs, page_index=1)
    assert [r["tag"] for r in recorded] == ["L", "R"]
    assert deck.images == []  # duration 0 = no feedback
    assert "knob_pages" not in state.raw and LEGACY_KEY in state.raw


def test_agent_without_deck_pages_keeps_legacy_knob_pages_behaviour(tmp_path: Path):
    raw = {
        "device": {"model": "auto"},
        "knob_page_feedback": {"duration_sec": 0.01},
        "knob_pages": {
            "knobTL": {
                "pages": [{"name": "One", "rotate_right": _rec("one")}, {"name": "Two", "rotate_right": _rec("two")}]
            }
        },
    }
    msgs = [
        {"action": "rotate", "state": "right", "id": "knobTL"},
        {"action": "push", "state": "down", "id": "knobTL"},
        {"action": "rotate", "state": "right", "id": "knobTL"},
    ]
    recorded, deck, _, _ = _run_agent_with(tmp_path, raw, msgs)
    assert [r["tag"] for r in recorded] == ["one", "two"]
    assert deck.images == ["0"]  # page name "Two" flashed on touch_0


def test_obs_scene_names_follow_dock_order_and_scene_step_switches():
    from open_loupedeck.actions.builtins import ObsSceneStep
    from open_loupedeck.obs_client import ObsSession

    obs = ObsSession("127.0.0.1", 4455, "")
    calls: list[tuple[str, Any]] = []

    async def fake_call(request_type: str, request_data: dict[str, Any] | None = None) -> Any:
        calls.append((request_type, request_data))
        if request_type == "GetSceneList":
            # OBS: sceneIndex 0 is the bottom of the Scenes dock.
            return {"scenes": [{"sceneName": "Bottom", "sceneIndex": 0}, {"sceneName": "Top", "sceneIndex": 1}]}
        if request_type == "GetCurrentProgramScene":
            return {"currentProgramSceneName": "Top"}
        return {}

    obs.call = fake_call  # type: ignore[method-assign]
    assert asyncio.run(obs.get_scene_names()) == ["Top", "Bottom"]

    class Ctx:
        pass

    ctx = Ctx()
    ctx.obs = obs  # type: ignore[attr-defined]
    asyncio.run(ObsSceneStep().run(ctx, {"step": 1}))  # type: ignore[arg-type]
    assert ("SetCurrentProgramScene", {"sceneName": "Bottom"}) in calls
