"""``merged_catalog``: every entry gets a display category (used to group the UI's action picker)."""

from __future__ import annotations

from open_loupedeck.action_catalog import ACTION_CATALOG, merged_catalog


def test_every_static_catalog_entry_has_a_category():
    missing = [e["type"] for e in ACTION_CATALOG if not e.get("category")]
    assert missing == []


def test_merged_catalog_includes_category_for_known_types():
    catalog = merged_catalog()
    by_type = {e["type"]: e for e in catalog}
    assert by_type["obs.set_scene"]["category"] == "OBS"
    assert by_type["ha.turn_on"]["category"] == "Home Assistant"
    assert by_type["keyboard.play_sequence"]["category"] == "Keyboard"


def test_merged_catalog_sorted_by_category_then_label():
    catalog = merged_catalog()
    keys = [(e["category"].lower(), e["label"].lower()) for e in catalog]
    assert keys == sorted(keys)
