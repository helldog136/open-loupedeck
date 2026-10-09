"""Starter packs (packs/*.json) must only use things that exist."""

from __future__ import annotations

import pytest

from open_loupedeck import i18n
from open_loupedeck.action_catalog import ACTION_CATALOG
from open_loupedeck.config_io import ensure_minimal_structure
from open_loupedeck.knob_duos import get_duo
from open_loupedeck.knob_roles import validate_knob_entry
from open_loupedeck.packs import KEY_COUNT, list_packs, load_raw_packs

TYPES = {a["type"] for a in ACTION_CATALOG}
PACKS = load_raw_packs()


def _actions(entry: dict) -> list[dict]:
    out = []
    if isinstance(entry.get("action"), dict):
        out.append(entry["action"])
    out.extend(a for a in entry.get("actions") or [] if isinstance(a, dict))
    return out


def test_expected_packs_exist() -> None:
    assert {"streamer", "music", "smart_home", "blank"} <= {p["id"] for p in PACKS}


@pytest.mark.parametrize("pack", PACKS, ids=lambda p: p["id"])
def test_pack_is_valid(pack: dict) -> None:
    for pi, page in enumerate(pack["pages"]):
        for idx, entry in page["keys"].items():
            assert idx.isdigit() and 0 <= int(idx) < KEY_COUNT, f"page {pi}: bad key index {idx}"
            acts = _actions(entry)
            assert acts, f"key {idx} has no action"
            for a in acts:
                assert a["type"] in TYPES, f"unknown action type {a['type']}"
        for kid, role in page.get("knobs", {}).items():
            assert not validate_knob_entry(role, kid), validate_knob_entry(role, kid)
            duo = (role.get("rotate") or {}).get("duo")
            if duo:
                assert get_duo(duo) is not None
        cfg = ensure_minimal_structure({"pages": [{"name": "x", "buttons": {}, "knobs": page.get("knobs", {})}]})
        assert cfg["pages"][0]["knobs"] == page.get("knobs", {})


@pytest.mark.parametrize("pack", PACKS, ids=lambda p: p["id"])
@pytest.mark.parametrize("lang", ["en", "fr"])
def test_pack_locale_keys_present(pack: dict, lang: str) -> None:
    keys = [pack["name_key"], pack["description_key"]]
    for page in pack["pages"]:
        keys += [e["text_key"] for e in page["keys"].values() if "text_key" in e]
    for k in keys:
        assert i18n.t(k, lang) != k, f"{k} missing in {lang}"


def test_list_packs_translated_with_preview() -> None:
    fr = {p["id"]: p for p in list_packs("fr")}
    en = {p["id"]: p for p in list_packs("en")}
    assert fr["music"]["name"] == "Musique" and en["music"]["name"] == "Music"
    labels = [i["label"] for i in fr["smart_home"]["preview"]]
    assert "Salon" in labels
    assert all("text_key" not in e for p in fr.values() for pg in p["pages"] for e in pg["keys"].values())
    assert en["streamer"]["preview"] and not en["blank"]["preview"]


def test_onboarding_done_default_and_normalised() -> None:
    assert ensure_minimal_structure({})["onboarding_done"] is False
    assert ensure_minimal_structure({"onboarding_done": True})["onboarding_done"] is True
    assert ensure_minimal_structure({"onboarding_done": "yes"})["onboarding_done"] is False
