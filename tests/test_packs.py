"""Starter packs (packs/*.json) must only use things that exist."""

from __future__ import annotations

import pytest

from open_loupedeck import i18n
from open_loupedeck.action_catalog import ACTION_CATALOG
from open_loupedeck.config_io import default_raw_config, ensure_minimal_structure
from open_loupedeck.devices.loupedeck.models import LOUPEDECK_LIVE, LOUPEDECK_LIVE_S
from open_loupedeck.devices.model import Control, DeviceModel, Position, control_kind_from_id, key_id, parse_key_id
from open_loupedeck.knob_duos import get_duo
from open_loupedeck.knob_roles import validate_knob_entry, validate_knobs_config
from open_loupedeck.packs import DEFAULT_GRID, apply_pack, fit_pack_to_model, list_packs, load_raw_packs

TYPES = {a["type"] for a in ACTION_CATALOG}
PACKS = load_raw_packs()

# A large virtual device: 8 x 4 keys, 6 knobs (a "mega" deck).
MEGA = DeviceModel(
    id="mega",
    family="virtual",
    name="Mega deck",
    layout=(10, 4),
    controls=(
        *(
            Control(key_id(c, r), "key", "K", Position(c + 1, r), ("press",), image=(96, 96))
            for r in range(4)
            for c in range(8)
        ),
        *(Control(f"knob_{i}", "knob", "N", Position(0 if i < 3 else 9, i % 3), ("press", "rotate")) for i in range(6)),
    ),
)
# A small one: 3 x 2 keys, no knob.
MINI = DeviceModel(
    id="mini",
    family="virtual",
    name="Mini pad",
    layout=(3, 2),
    controls=tuple(
        Control(key_id(c, r), "key", "K", Position(c, r), ("press",), image=(72, 72))
        for r in range(2)
        for c in range(3)
    ),
)


def _actions(entry: dict) -> list[dict]:
    out = []
    if isinstance(entry.get("action"), dict):
        out.append(entry["action"])
    out.extend(a for a in entry.get("actions") or [] if isinstance(a, dict))
    return out


def test_expected_packs_exist() -> None:
    assert {"streamer", "music", "smart_home", "wow", "blank"} <= {p["id"] for p in PACKS}


@pytest.mark.parametrize("pack", PACKS, ids=lambda p: p["id"])
def test_pack_is_valid(pack: dict) -> None:
    assert tuple(pack.get("grid") or DEFAULT_GRID) == DEFAULT_GRID
    cols, rows = DEFAULT_GRID
    for pi, page in enumerate(pack["pages"]):
        assert set(page) == {"controls"}, f"page {pi}: only `controls`"
        for cid, entry in page["controls"].items():
            kind = control_kind_from_id(cid)
            assert kind in ("key", "knob"), f"page {pi}: bad control id {cid}"
            if kind == "key":
                col, row = parse_key_id(cid)
                assert col < cols and row < rows, f"page {pi}: {cid} outside the pack grid"
                acts = _actions(entry)
                assert acts, f"{cid} has no action"
                for a in acts:
                    assert a["type"] in TYPES, f"unknown action type {a['type']}"
            else:
                assert not validate_knob_entry(entry, cid), validate_knob_entry(entry, cid)
                duo = (entry.get("rotate") or {}).get("duo")
                if duo:
                    assert get_duo(duo) is not None
        cfg = ensure_minimal_structure({"config_version": 2, "pages": [{"name": "x", "controls": page["controls"]}]})
        assert cfg["pages"][0]["controls"] == page["controls"]
        assert validate_knobs_config(cfg) == []


@pytest.mark.parametrize("pack", PACKS, ids=lambda p: p["id"])
@pytest.mark.parametrize("lang", ["en", "fr"])
def test_pack_locale_keys_present(pack: dict, lang: str) -> None:
    keys = [pack["name_key"], pack["description_key"]]
    for page in pack["pages"]:
        keys += [e["text_key"] for e in page["controls"].values() if "text_key" in e]
    for k in keys:
        assert i18n.t(k, lang) != k, f"{k} missing in {lang}"


def test_list_packs_translated_with_preview() -> None:
    fr = {p["id"]: p for p in list_packs("fr")}
    en = {p["id"]: p for p in list_packs("en")}
    assert fr["music"]["name"] == "Musique" and en["music"]["name"] == "Music"
    labels = [i["label"] for i in fr["smart_home"]["preview"]]
    assert "Salon" in labels
    assert all("text_key" not in e for p in fr.values() for pg in p["pages"] for e in pg["controls"].values())
    assert all("text_key" not in e for p in fr.values() for pg in p["pages"] for e in pg["keys"].values())
    assert en["streamer"]["preview"] and not en["blank"]["preview"]


def test_wow_pack_one_chord_per_key() -> None:
    from open_loupedeck.icon_loader import looks_like_icon_uri
    from open_loupedeck.keyboard_replay import parse_chord

    pack = next(p for p in PACKS if p["id"] == "wow")
    keys = {c: e for c, e in pack["pages"][0]["controls"].items() if c.startswith("key_")}
    assert len(keys) == 10
    chords = []
    for entry in keys.values():
        acts = _actions(entry)
        assert len(acts) == 1 and acts[0]["type"] == "wow.keybind"  # one key press = one action = one chord
        assert "actions" not in entry
        chords.append(acts[0]["key"])
        assert acts[0]["macro_name"].strip()
        assert entry["icon"].startswith("wow:") and looks_like_icon_uri(entry["icon"])
    assert len(set(chords)) == 10
    assert chords == [f"ctrl+shift+f{n}" for n in range(13, 23)]
    for c in chords:
        parse_chord(c)
    assert {i["label"] for i in next(p for p in list_packs("fr") if p["id"] == "wow")["preview"]} >= {
        "Hearthstone",
        "Mount",
    }


def test_onboarding_done_default_and_normalised() -> None:
    assert ensure_minimal_structure({})["onboarding_done"] is False
    assert ensure_minimal_structure({"onboarding_done": True})["onboarding_done"] is True
    assert ensure_minimal_structure({"onboarding_done": "yes"})["onboarding_done"] is False


def test_packs_keep_coordinates_on_a_smaller_grid() -> None:
    streamer = next(p for p in PACKS if p["id"] == "streamer")
    pages, notes = fit_pack_to_model(streamer, LOUPEDECK_LIVE)
    kept = pages[0]["controls"]
    src = streamer["pages"][0]["controls"]
    # 4 x 3: column 4 does not exist; everything else keeps its place.
    assert {c for c in src if c.startswith("key_4_")} == {n["control_id"] for n in notes}
    assert all("4x3" in n["reason"] and n["page"] == "0" for n in notes)
    assert set(kept) == {c for c in src if not c.startswith("key_4_")}
    assert kept["knob_0"] == src["knob_0"]

    pages, notes = fit_pack_to_model(streamer, MINI)
    assert set(pages[0]["controls"]) == {c for c in src if c in set(MINI.ids_of_kind("key"))}
    assert {n["control_id"] for n in notes} >= {"knob_0", "key_4_2"}
    assert any("has no knob_0" in n["reason"] for n in notes)


def test_packs_on_a_larger_grid_drop_nothing() -> None:
    for pack in PACKS:
        pages, notes = fit_pack_to_model(pack, MEGA)
        assert notes == []
        assert [p["controls"] for p in pages] == [p["controls"] for p in pack["pages"]]


def test_list_packs_for_each_model_gives_legacy_keys_for_the_ui() -> None:
    s_packs = {p["id"]: p for p in list_packs("en", LOUPEDECK_LIVE_S)}
    live_packs = {p["id"]: p for p in list_packs("en", LOUPEDECK_LIVE)}
    music_s, music_live = s_packs["music"], live_packs["music"]
    assert music_s["dropped"] == [] and music_s["model"] == "loupedeck_live_s"
    assert set(music_s["pages"][0]["keys"]) == {"7", "8", "9", "13", "14"}  # the old Live S indices
    assert music_s["pages"][0]["knobs"].keys() == {"knobTL", "knobCL"}
    # Live: key_2_1 / key_3_1 / key_3_2 stay at their place (touch 6, 7, 11); column 4 is dropped.
    assert set(music_live["pages"][0]["keys"]) == {"6", "7", "11"}
    assert {d["control_id"] for d in music_live["dropped"]} == {"key_4_1", "key_4_2"}
    assert [p["id"] for p in list_packs("en")] == [p["id"] for p in s_packs.values()]  # default: Live S


def test_apply_pack_fills_only_what_is_empty_on_any_grid() -> None:
    music = next(p for p in PACKS if p["id"] == "music")
    raw = ensure_minimal_structure(default_raw_config())
    raw["pages"][0]["controls"]["key_2_1"] = {"action": {"type": "obs.set_scene", "scene": "Mine"}}
    raw["pages"][0]["controls"]["key_3_1"] = {"text": "look only"}  # no action: gets filled
    notes = apply_pack(raw, music, LOUPEDECK_LIVE)
    controls = raw["pages"][0]["controls"]
    assert controls["key_2_1"]["action"]["scene"] == "Mine"  # kept
    assert controls["key_3_1"] == music["pages"][0]["controls"]["key_3_1"]
    assert "key_4_1" not in controls and {n["control_id"] for n in notes} == {"key_4_1", "key_4_2"}
    assert controls["knob_0"]["rotate"]["duo"] == "spotify_volume"
    assert raw["onboarding_pack"] == "music"

    big = {"config_version": 2, "pages": [{"name": "A", "controls": {}}]}
    assert apply_pack(big, music, MEGA) == []
    assert big["pages"][0]["controls"] == music["pages"][0]["controls"]
    assert apply_pack({"pages": []}, music, MINI) != []  # notes, nothing to fill
