"""Config migration legacy -> config_version 2 and the UI compatibility view, on realistic configs."""

from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

from open_loupedeck.actions.registry import register_handler
from open_loupedeck.config_backup import backup_dir_for, list_backups
from open_loupedeck.config_io import default_raw_config, ensure_minimal_structure, load_raw_config, save_raw_config
from open_loupedeck.config_migrate import (
    CONFIG_VERSION,
    UNMIGRATED_KEY,
    config_version,
    default_global_bindings,
    from_ui_view,
    migrate_config,
    needs_migration,
    page_button_ids,
    to_ui_view,
)
from open_loupedeck.config_state import ConfigState
from open_loupedeck.devices.loupedeck.models import LOUPEDECK_LIVE, LOUPEDECK_LIVE_S
from open_loupedeck.runtime_refs import AgentRuntimeRefs
from open_loupedeck.web_app import create_web_app
from tests.fake_backend import FakeBackend

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
LEGACY_FILES = ["legacy_config_example.yaml", "legacy_live_s_user.yaml", "legacy_live_user.yaml"]


def _load(name: str) -> dict[str, Any]:
    return yaml.safe_load((FIXTURES / name).read_text(encoding="utf-8"))


def _goto(i: int) -> dict[str, Any]:
    return {"type": "agent.goto_page", "index": i}


def _legacy_entries(raw: dict[str, Any]) -> list[str]:
    out = [json.dumps(e, sort_keys=True) for e in (raw.get("global_buttons") or {}).values()]
    for p in raw.get("pages") or []:
        for section in ("buttons", "knobs"):
            out += [json.dumps(e, sort_keys=True) for e in (p.get(section) or {}).values()]
    return out


def _v2_entries(raw: dict[str, Any]) -> list[str]:
    out = [json.dumps(e, sort_keys=True) for e in (raw.get("global") or {}).values()]
    for p in raw.get("pages") or []:
        out += [json.dumps(e, sort_keys=True) for e in (p.get("controls") or {}).values()]
    return out


# --- versions -----------------------------------------------------------------------------------


def test_versions():
    assert config_version({}) == 1 and needs_migration({})
    assert config_version({"config_version": 2}) == 2 and not needs_migration({"config_version": "2"})
    assert config_version({"config_version": "junk"}) == 1
    assert config_version(default_raw_config()) == CONFIG_VERSION == 2
    assert page_button_ids(LOUPEDECK_LIVE_S) == ["button_0", "button_1", "button_2", "button_3"]
    assert page_button_ids(LOUPEDECK_LIVE) == []
    assert default_global_bindings(LOUPEDECK_LIVE_S)["button_3"] == {"action": _goto(3)}


# --- the user's Live S config -------------------------------------------------------------------


def test_live_s_user_config():
    legacy = _load("legacy_live_s_user.yaml")
    v2, notes = migrate_config(legacy)
    assert next(iter(v2)) == "config_version" and v2["config_version"] == 2
    assert "global_buttons" not in v2 and all("buttons" not in p and "knobs" not in p for p in v2["pages"])
    for k in ("language", "brightness", "brightness_night", "obs", "ha", "spotify", "knob_page_feedback", "bindings"):
        assert v2[k] == legacy[k]  # untouched

    g = v2["global"]
    # The four round buttons: their LED colour, and "open page N" as an ordinary global binding.
    assert g["button_0"] == {"button_color": "#3b6bff", "action": _goto(0)}  # btn_0 alias, colour trimmed
    assert g["button_1"] == {
        "button_color": "#ff8a2b",
        "legacy_action": {"type": "agent.next_page"},
        "action": _goto(1),
    }
    assert g["button_2"] == {"button_color": "#e040c8", "action": _goto(2)}
    assert g["button_3"] == {"action": _goto(3)}
    assert any("legacy_action" in n for n in notes)
    # Entries the legacy runtime never used keep their old id: inactive, not lost.
    assert g["touch_3"] == {"text": "ghost"} and g["knobTL_left"]["action"]["delta"] == -1
    assert g["foo"] == {"text": "unknown"}
    assert g["strip_0"] == {"text": "L"}  # a Live strip: inactive on the Live S

    p0, p1, p4 = (v2["pages"][i]["controls"] for i in (0, 1, 4))
    assert p0["key_0_0"]["press_animation"] == "shrink" and p0["key_0_0"]["action"]["type"] == "obs.toggle_stream"
    assert p0["key_1_0"]["action"]["scene"] == "Game"
    assert p0["key_0_1"]["action"]["type"] == "obs.toggle_mute"  # touch_5: column 0, row 1
    assert p0["key_0_2"]["action"]["type"] == "display.live_message"  # touch_10
    assert p0["key_4_2"]["action"]["type"] == "display.clock"  # touch_14
    assert p0["touch_15"] == {"text": "beyond the grid"}  # no such key: kept as is
    assert p0["btn_2"] == {"button_color": "#000000"}  # page-level page button: never used, kept
    assert p0["knob_0"]["press"] == {"type": "sound.mute_toggle"}
    assert p0["knob_1"]["rotate"]["right"] == [{"type": "agent.next_page"}]
    assert set(p1) == {"key_2_1", "key_3_1", "key_4_1", "knob_0"}
    assert p4 == {"key_2_2": {"action": {"type": "sound.play", "file": "library/sounds/applause.wav"}}}
    assert [p["id"] for p in v2["pages"]] == [0, 1, 2, 3, 4] and v2["pages"][3]["controls"] == {}


def test_live_user_config():
    v2, _ = migrate_config(_load("legacy_live_user.yaml"))
    g = v2["global"]
    assert g["strip_0"]["background"] == "#202040" and g["strip_1"] == {"text": "Right"}  # `right` alias
    assert g["button_0"] == {"action": {"type": "agent.prev_page"}}  # no page buttons on the Live
    assert g["button_7"]["action"]["type"] == "agent.next_page" and g["button_3"] == {"text": "look only"}
    c = v2["pages"][0]["controls"]
    assert c["key_0_0"]["action"]["scene"] == "A" and c["key_3_2"]["action"]["scene"] == "B"  # 4 columns
    assert c["touch_12"] == {"text": "beyond the 4x3 grid"}
    # A page round-button entry only ran when the global one had no action: same outcome now.
    assert c["button_3"] == {"action": {"type": "sound.mute_toggle"}}
    assert c["btn_7"]["action"]["type"] == "obs.toggle_stream"  # inactive (global btn_7 had an action)
    assert c["strip_left"] == {"text": "page strip"}  # strips never read page entries
    assert c["knob_5"] == {"rotate": {"duo": "system_volume"}} and c["knob_3"]["press"]["type"] == "sound.mute_toggle"


def test_config_example_and_auto_means_live_s():
    v2, _ = migrate_config(_load("legacy_config_example.yaml"))
    assert v2["device"]["model"] == "auto"
    assert v2["global"] == default_global_bindings(LOUPEDECK_LIVE_S)  # auto -> Live S
    assert list(v2).index("global") == list(v2).index("pages") - 1  # readable: right before pages
    c = v2["pages"][0]["controls"]
    assert c["key_0_0"]["text"] == "BRB" and c["button_7"] == {"action": {"type": "agent.next_page"}}
    assert v2["bindings"] == _load("legacy_config_example.yaml")["bindings"]


def test_config_example_is_the_migrated_legacy_example():
    example = load_raw_config(ROOT / "config.example.yaml")
    assert example["config_version"] == 2 and not needs_migration(example)
    assert example == migrate_config(_load("legacy_config_example.yaml"))[0]


@pytest.mark.parametrize("name", LEGACY_FILES)
def test_migration_is_idempotent_and_loses_nothing(name: str):
    legacy = _load(name)
    v2, _ = migrate_config(legacy)
    assert migrate_config(v2) == (v2, [])
    assert ensure_minimal_structure(ensure_minimal_structure(legacy)) == ensure_minimal_structure(legacy)
    assert legacy == _load(name)  # the input is not modified
    # Every legacy binding is still there (page buttons get a goto action, nothing else changes).
    after = _v2_entries(v2)
    for entry in _legacy_entries(legacy):
        e = json.loads(entry)
        if e in ({"button_color": "#e040c8", "actions": []},):
            continue
        found = entry in after or any(
            {k: v for k, v in json.loads(a).items() if k not in ("action", "legacy_action")}
            == {k: (v.strip() if k == "button_color" else v) for k, v in e.items() if k not in ("action",)}
            for a in after
        )
        assert found, entry


def test_clashes_are_kept_somewhere():
    legacy = {
        "device": {"model": "live_s"},
        "global_buttons": {"btn_circle": {"text": "a"}, "btn_0": {"text": "b"}, "button_0": {"text": "v2"}},
        "pages": [{"name": "A", "buttons": {"touch_0": {"text": "old"}, "key_0_0": {"text": "new"}}}],
    }
    v2, notes = migrate_config(legacy)
    assert v2["global"]["button_0"]["text"] == "v2"  # a control id wins
    assert v2["global"]["btn_circle"] == {"text": "a"} and v2["global"]["btn_0"] == {"text": "b"}
    c = v2["pages"][0]["controls"]
    assert c["key_0_0"] == {"text": "new"} and c["touch_0"] == {"text": "old"}
    assert notes and UNMIGRATED_KEY not in v2


# --- UI compatibility view ----------------------------------------------------------------------

HAND_WRITTEN_V2 = {
    "config_version": 2,
    "device": {"model": "live_s"},
    "global": {
        "button_0": {"action": _goto(0), "button_color": "#ff0000"},
        "button_1": {"action": {"type": "spotify.next"}},  # custom action on a page button
        "button_2": {"button_color": "#00ff00"},  # no action at all
        "knob_1": {"rotate": {"duo": "system_volume"}},  # global knob
        "key_4_2": {"action": {"type": "display.clock"}},  # global key
        "key_9_9": {"text": "other device"},
        "touch_3": {"text": "dead legacy"},
    },
    "pages": [
        {
            "name": "A",
            "controls": {
                "key_0_0": {"text": "x"},
                "button_3": {"action": {"type": "sound.mute_toggle"}},  # page override of a page button
                "knob_0": {"press": {"type": "sound.mute_toggle"}},
                "knob_5": {"rotate": {"duo": "spotify_track"}},  # a Live knob
                "strip_0": {"text": "s"},
                "btn_2": {"text": "dead"},
            },
        },
        {"name": "B", "controls": {}},
    ],
}


@pytest.mark.parametrize("name", LEGACY_FILES)
def test_ui_view_round_trips_migrated_configs(name: str):
    v2, _ = migrate_config(_load(name))
    for model in (LOUPEDECK_LIVE_S, LOUPEDECK_LIVE):
        assert from_ui_view(to_ui_view(v2, model)) == v2  # the view records its model


def test_ui_view_round_trips_hand_written_v2_and_shows_legacy_ids():
    view = to_ui_view(HAND_WRITTEN_V2)
    assert "config_version" not in view and "global" not in view and view["_ui_model"] == "loupedeck_live_s"
    gb = view["global_buttons"]
    assert gb["btn_circle"] == {"button_color": "#ff0000"}  # default goto hidden from the old UI
    assert gb["btn_1"] == {"_v2_action": {"type": "spotify.next"}}
    assert gb["btn_2"] == {"button_color": "#00ff00", "_v2_action": None}
    assert gb["knob_1"]["rotate"]["duo"] == "system_volume" and gb["key_4_2"]
    assert view["_v2_inactive"] == {"touch_3": {"text": "dead legacy"}}  # set aside, never re-read
    page = view["pages"][0]
    assert page["buttons"]["touch_0"] == {"text": "x"}
    assert page["buttons"]["button_3"]["action"]["type"] == "sound.mute_toggle"  # no legacy equivalent
    assert page["knobs"] == {
        "knobTL": {"press": {"type": "sound.mute_toggle"}},
        "knobBR": {"rotate": {"duo": "spotify_track"}},
    }
    assert "controls" not in page and page["buttons"]["strip_0"] == {"text": "s"}
    assert page["_v2_inactive"] == {"btn_2": {"text": "dead"}}
    assert view["_v2_unbound"] == ["button_3"]  # only a page override: no global binding
    assert from_ui_view(view) == HAND_WRITTEN_V2

    # The old UI edits a LED colour and a key, then saves: everything else survives.
    view["global_buttons"]["btn_circle"]["button_color"] = "#123456"
    view["pages"][1]["buttons"]["touch_6"] = {"text": "new key"}
    del view["global_buttons"]["btn_1"]  # the old UI never deletes page buttons, but if it did:
    back = from_ui_view(view)
    assert back["global"]["button_0"] == {"action": _goto(0), "button_color": "#123456"}
    assert back["global"]["button_1"] == {"action": _goto(1)}  # a page button the old UI drops opens its page
    assert "button_3" not in back["global"]
    assert back["pages"][1]["controls"] == {"key_1_1": {"text": "new key"}}
    assert back["global"]["touch_3"] == {"text": "dead legacy"} and back["pages"][0]["controls"]["btn_2"]

    # A page button deliberately left without a binding in YAML stays so through the old UI.
    unbound = copy.deepcopy(HAND_WRITTEN_V2)
    del unbound["global"]["button_2"]
    view = to_ui_view(unbound)
    assert view["_v2_unbound"] == ["button_2", "button_3"] and "btn_2" not in view["global_buttons"]
    assert from_ui_view(view) == unbound


# --- loading a legacy file: backup + migration --------------------------------------------------


def test_config_state_backs_up_then_migrates_once(tmp_path: Path):
    path = tmp_path / "config.yaml"
    original = (FIXTURES / "legacy_live_s_user.yaml").read_bytes()
    path.write_bytes(original)
    state = ConfigState(path)
    backup = backup_dir_for(path) / "config.yaml.pre-v2"
    assert backup.read_bytes() == original  # byte for byte, comments included
    on_disk = load_raw_config(path)
    assert on_disk["config_version"] == 2 and "global_buttons" not in on_disk
    assert on_disk == migrate_config(yaml.safe_load(original))[0]
    assert state.raw["global"]["button_1"]["action"] == _goto(1)

    ConfigState(path)  # second start: nothing to migrate, no new migration backup
    assert sorted(p.name for p in backup_dir_for(path).glob("*.pre-v2*")) == ["config.yaml.pre-v2"]
    assert load_raw_config(path) == on_disk

    # Restoring a (legacy) rotating backup migrates again, with its own copy.
    assert any(b["name"] == "config.yaml.bak1" for b in list_backups(path))
    client = TestClient(create_web_app(path, state, asyncio.Lock()))
    path.write_bytes(original)
    state.reload_from_disk()
    assert state.raw["config_version"] == 2
    assert sorted(p.name for p in backup_dir_for(path).glob("*.pre-v2*")) == [
        "config.yaml.pre-v2",
        "config.yaml.pre-v2.1",
    ]
    assert client.get("/api/config").status_code == 200


def test_new_config_is_v2_with_page_buttons(tmp_path: Path):
    path = tmp_path / "config.yaml"
    state = ConfigState(path)
    assert load_raw_config(path)["config_version"] == 2
    assert state.raw["global"] == default_global_bindings(LOUPEDECK_LIVE_S)
    assert state.raw["pages"][0]["controls"]["key_4_2"]["action"]["type"] == "display.clock"
    assert not list(backup_dir_for(path).glob("*.pre-v2*"))


# --- web API ------------------------------------------------------------------------------------


def _client(tmp_path: Path, raw: dict[str, Any], deck: Any = None) -> tuple[TestClient, ConfigState, Path]:
    path = tmp_path / "config.yaml"
    save_raw_config(path, raw)
    state = ConfigState(path)
    rt = AgentRuntimeRefs(deck=deck, no_device=deck is None)
    return TestClient(create_web_app(path, state, asyncio.Lock(), runtime=rt)), state, path


def test_api_config_serves_the_ui_view_and_v2(tmp_path: Path):
    client, state, path = _client(tmp_path, _load("legacy_live_s_user.yaml"))
    view = client.get("/api/config").json()
    assert view["pages"][0]["buttons"]["touch_5"]["action"]["type"] == "obs.toggle_mute"
    assert view["pages"][0]["knobs"]["knobTL"]["press"]["type"] == "sound.mute_toggle"
    assert view["global_buttons"]["btn_1"]["button_color"] == "#ff8a2b"
    v2 = client.get("/api/config?format=v2").json()
    assert v2["config_version"] == 2 and v2["global"] == state.raw["global"]

    # The current UI saves its view back: the stored config is unchanged.
    before = load_raw_config(path)
    assert client.put("/api/config", json=view).status_code == 200
    assert load_raw_config(path) == before

    # A v2 body is stored as is (after normalisation).
    v2["pages"][0]["controls"]["key_2_2"] = {"text": "via v2"}
    v2["global"]["knob_1"] = {"rotate": {"duo": "system_volume"}}
    assert client.put("/api/config", json=v2).status_code == 200
    stored = load_raw_config(path)
    assert stored["pages"][0]["controls"]["key_2_2"] == {"text": "via v2"} and "knob_1" in stored["global"]
    assert client.get("/api/config").json()["pages"][0]["buttons"]["touch_12"] == {"text": "via v2"}

    bad = copy.deepcopy(v2)
    bad["global"]["knob_1"] = {"rotate": {"duo": "nope"}}
    r = client.put("/api/config", json=bad)
    assert r.status_code == 400 and "global.knob_1" in r.json()["detail"]

    # A legacy body (an old backup pasted, an old client) is migrated.
    legacy = _load("legacy_live_user.yaml")
    legacy["device"] = {"model": "live_s"}
    assert client.put("/api/config", json=legacy).status_code == 200
    stored = load_raw_config(path)
    assert stored["config_version"] == 2 and stored["global"]["button_0"]["action"] == _goto(0)


def test_api_view_follows_the_connected_model_when_auto(tmp_path: Path):
    raw = {
        "config_version": 2,
        "device": {"model": "auto"},
        "pages": [{"name": "A", "controls": {"key_1_1": {"text": "x"}}}],
    }
    client, _state, path = _client(tmp_path, raw, FakeBackend(LOUPEDECK_LIVE))
    view = client.get("/api/config").json()
    assert view["_ui_model"] == "loupedeck_live" and view["pages"][0]["buttons"] == {"touch_5": {"text": "x"}}
    assert client.put("/api/config", json=view).status_code == 200
    assert load_raw_config(path)["pages"][0]["controls"] == {"key_1_1": {"text": "x"}}
    packs = {p["id"]: p for p in client.get("/api/packs?lang=en").json()["packs"]}
    assert packs["music"]["model"] == "loupedeck_live" and packs["music"]["dropped"]


def test_api_preview_and_status_accept_both_ids(tmp_path: Path):
    client, _state, _path = _client(tmp_path, {"config_version": 2, "pages": [{"name": "A", "controls": {}}]})
    for cid in ("touch_0", "key_0_0", "btn_circle"):
        r = client.post("/api/preview_key", json={"entry": {"text": "x"}, "control_id": cid, "offline": True})
        assert r.status_code == 200, cid


# --- the agent on the migrated user config (end to end, FakeBackend) ----------------------------


def test_agent_on_the_migrated_user_config(tmp_path: Path):
    from open_loupedeck.app import run_agent

    recorded: list[str] = []

    async def _record(_ctx: Any, params: dict[str, Any]) -> None:
        recorded.append(str(params.get("tag")))

    register_handler("test.mig_record", _record)
    legacy = _load("legacy_live_s_user.yaml")
    legacy["knob_page_feedback"] = {"duration_sec": 0}
    legacy["pages"][1]["buttons"]["touch_8"] = {"action": {"type": "test.mig_record", "tag": "music-play"}}
    legacy["pages"][0]["knobs"]["knobCL"] = {"rotate": {"right": {"type": "test.mig_record", "tag": "knob-right"}}}
    path = tmp_path / "config.yaml"
    save_raw_config(path, legacy)
    state = ConfigState(path)
    dev = FakeBackend(LOUPEDECK_LIVE_S)
    runtime = AgentRuntimeRefs(deck=dev, no_device=True)
    redraws: list[str] = []

    async def redraw(reason: str = "") -> None:
        from open_loupedeck.deck_skin import apply_page_skin

        redraws.append(reason)
        pages = state.raw["pages"]
        idx = state.page_index % len(pages)
        apply_page_skin(dev, pages[idx], tmp_path, state.raw["global"], page_index=idx)

    async def go() -> list[int]:
        task = asyncio.create_task(run_agent(state, asyncio.Lock(), redraw, runtime))
        for _ in range(200):
            if runtime.simulate_event is not None:
                break
            await asyncio.sleep(0.01)
        seen = []
        for raw_id in ("1", "3", "circle"):  # the round buttons, as the driver reports them
            await runtime.simulate_raw_message({"action": "push", "state": "down", "id": raw_id})
            seen.append(state.page_index)
        await runtime.simulate_raw_message({"action": "push", "state": "down", "id": "1"})
        await runtime.simulate_raw_message({"action": "touchstart", "screen": "center", "key": 8})
        state.page_index = 0
        await runtime.simulate_raw_message({"action": "rotate", "state": "right", "id": "knobCL"})
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return seen

    assert asyncio.run(go()) == [1, 3, 0]
    assert recorded == ["music-play", "knob-right"]
    # LEDs exactly as before the migration (colours from the old global_buttons, default dim grey).
    assert dev.colors == {
        "button_0": (0x3B, 0x6B, 0xFF),
        "button_1": (0xFF, 0x8A, 0x2B),
        "button_2": (0xE0, 0x40, 0xC8),
        "button_3": (32, 32, 40),
    }
    assert set(dev.images) == {f"key_{c}_{r}" for c in range(5) for r in range(3)}
