"""Default looks per action: catalog coverage, resolution rules, rendering and the HTTP surface."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from PIL import ImageChops

from open_loupedeck import i18n
from open_loupedeck.action_catalog import ACTION_CATALOG, merged_catalog
from open_loupedeck.button_render import render_tactile_key_image
from open_loupedeck.icon_loader import icon_url_from_spec
from open_loupedeck.look_defaults import LIVE_PLACEHOLDER, proposed_entry, resolve_look

HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
TYPES = [e["type"] for e in ACTION_CATALOG]


@pytest.mark.parametrize("action", TYPES)
def test_every_catalog_action_has_a_valid_default_look(action):
    entry = next(e for e in ACTION_CATALOG if e["type"] == action)
    look = entry["default_look"]
    assert HEX.match(look["bg"]) and HEX.match(look["fg"])
    assert look["mode"] in ("text", "icon", "both")
    assert icon_url_from_spec(look["icon"]) is not None
    assert look["label_key"] == f"look.{action}.label"
    for code in ("en", "fr"):
        assert i18n.t(look["label_key"], code) != look["label_key"]
    if "label_from" in look:
        assert look["label_from"] in {f["name"] for f in entry["fields"]}
    if "live" in look:
        assert HEX.match(look["live"]["offline_bg"]) and HEX.match(look["live"]["offline_fg"])


def test_look_label_keys_exist_in_every_locale_and_none_are_stray():
    expected = {f"look.{t}.label" for t in TYPES}
    for code in ("en", "fr"):
        keys = {k for k in i18n.messages_for(code) if k.startswith("look.")}
        assert keys == expected, code


def test_transport_controls_are_icon_mode_and_live_actions_are_flagged():
    by = {e["type"]: e["default_look"] for e in ACTION_CATALOG}
    for t in ("spotify.play_pause", "spotify.next", "spotify.previous", "agent.next_page"):
        assert by[t]["mode"] == "icon"
    for t in ("display.clock", "display.live_message", "display.twitch_live", "display.obs_scene"):
        assert "live" in by[t]
    assert by["twitch.create_clip"]["bg"] == "#9146ff"


def test_merged_catalog_exposes_default_look():
    cat = {e["type"]: e for e in merged_catalog()}
    assert cat["obs.set_scene"]["default_look"]["label_from"] == "scene"
    assert all(e["default_look"] for e in cat.values() if e["type"] in TYPES)


def test_proposed_look_for_bare_action():
    r = resolve_look({"action": {"type": "obs.set_scene", "scene": "Just Chatting"}})
    assert r["label"] == "Just Chatting"
    assert r["bg"] == "#1f6fe0" and r["fg"] == "#ffffff" and r["mode"] == "text"
    assert set(r["source"].values()) == {"proposed"}
    assert set(r["source"]) == {"label", "icon", "bg", "fg", "mode"}


def test_modified_fields_win_and_others_stay_proposed():
    r = resolve_look(
        {
            "action": {"type": "obs.set_scene", "scene": "BRB"},
            "text": "Be right back",
            "background": "#112233",
        }
    )
    assert r["label"] == "Be right back" and r["bg"] == "#112233"
    assert r["source"]["label"] == "modified" and r["source"]["bg"] == "modified"
    assert r["source"]["fg"] == "proposed" and r["source"]["icon"] == "proposed"
    assert r["fg"] == "#ffffff"


def test_label_alias_icon_image_and_text_color_are_modifications():
    r = resolve_look({"action": {"type": "command.run"}, "label": "Go", "image": "x.png", "text_color": "#000000"})
    assert (r["label"], r["icon"], r["fg"]) == ("Go", "x.png", "#000000")
    assert {r["source"][k] for k in ("label", "icon", "fg")} == {"modified"}


def test_gradient_background_counts_as_modified_bg():
    r = resolve_look(
        {
            "action": {"type": "command.run"},
            "background_gradient_from": "#000000",
            "background_gradient_to": "#ffffff",
        }
    )
    assert r["source"]["bg"] == "modified"


def test_label_from_param_and_fallback_to_label_key():
    sound = resolve_look({"action": {"type": "sound.play", "file": "media/sfx/Applause.mp3"}})
    assert sound["label"] == "Applause"
    empty = resolve_look({"action": {"type": "sound.play"}})
    assert empty["label"] == "Sound"
    light = resolve_look({"action": {"type": "ha.toggle", "entity_id": "light.office_desk"}})
    assert light["label"] == "Office desk"
    # a template placeholder is not a usable label
    assert resolve_look({"action": {"type": "obs.set_scene", "scene": "{x}"}})["label"] == "Scene"


def test_language_switch_changes_proposed_label_only():
    entry = {"action": {"type": "spotify.next"}}
    assert resolve_look(entry, "en")["label"] == "Next"
    assert resolve_look(entry, "fr")["label"] == "Suivant"
    assert resolve_look(entry, "fr-FR")["label"] == "Suivant"
    assert resolve_look(entry, "de")["label"] == "Next"  # unknown language -> English
    # a user-typed label is not translated
    assert resolve_look({**entry, "text": "Skip"}, "fr")["label"] == "Skip"
    # param-driven labels do not depend on the language
    scene = {"action": {"type": "obs.set_scene", "scene": "Jeu"}}
    assert resolve_look(scene, "fr")["label"] == resolve_look(scene, "en")["label"] == "Jeu"


def test_injectable_translate():
    r = resolve_look({"action": {"type": "spotify.next"}}, "xx", translate=lambda k, lang: f"{lang}:{k}")
    assert r["label"] == "xx:look.spotify.next.label"


def test_explicit_mode_key_is_honoured():
    r = resolve_look({"action": {"type": "sound.play", "file": "a.wav"}, "mode": "icon"})
    assert r["mode"] == "icon" and r["source"]["mode"] == "modified"


def test_entry_without_action_is_returned_as_is():
    r = resolve_look({"text": "Hi", "background": "#010203"})
    assert r["label"] == "Hi" and r["bg"] == "#010203" and r["icon"] == "" and r["fg"] == ""


def test_live_action_exposes_offline_colours():
    r = resolve_look({"action": {"type": "display.clock"}})
    assert r["live"]["offline_bg"] == "#2b2f45"


# --- rendering ------------------------------------------------------------------------------


def test_bare_text_action_renders_its_proposed_colours(tmp_path: Path):
    img = render_tactile_key_image({"action": {"type": "obs.set_scene", "scene": "Jeu"}}, tmp_path)
    assert img is not None
    assert img.convert("RGB").getpixel((2, 2)) == (0x1F, 0x6F, 0xE0)


def test_bare_live_action_draws_offline_dash(tmp_path: Path):
    entry = proposed_entry({"action": {"type": "display.clock"}})
    assert entry["text"] == LIVE_PLACEHOLDER and entry["background"] == "#2b2f45"
    img = render_tactile_key_image({"action": {"type": "display.clock"}}, tmp_path)
    assert img is not None and img.convert("RGB").getpixel((2, 2)) == (0x2B, 0x2F, 0x45)


def test_live_key_with_runtime_text_gets_proposed_colours_but_keeps_its_text():
    out = proposed_entry({"action": {"type": "display.clock"}, "text": "13:54"})
    assert out["text"] == "13:54" and out["background"] == "#4a4f8f"


def _corner(img):
    return img.convert("RGB").getpixel((2, 2))


def test_customising_one_field_keeps_the_others_proposed(tmp_path: Path):
    # A custom label only: the proposed colours stay (the key does not fall back to the plain look).
    entry = {"text": "Jeu", "action": {"type": "obs.set_scene", "scene": "Jeu"}}
    assert _corner(render_tactile_key_image(entry, tmp_path)) == (0x1F, 0x6F, 0xE0)
    # A custom background only: the proposed label and icon are still drawn.
    out = proposed_entry({"background": "#102030", "action": {"type": "sound.play", "file": "sfx/Clap.mp3"}})
    assert out["background"] == "#102030" and out["text"] == "Clap"
    assert out["icon"] == "lucide:volume-2" and out["mode"] == "both" and out["text_color"] == "#ffffff"
    img = render_tactile_key_image({"background": "#102030", "action": {"type": "obs.set_scene"}}, tmp_path)
    assert _corner(img) == (0x10, 0x20, 0x30)


def test_stored_mode_wins_and_drives_the_layout(tmp_path: Path):
    base = {"action": {"type": "sound.play", "file": "a.wav"}}
    assert proposed_entry({**base, "mode": "text"})["mode"] == "text"
    assert "icon" not in proposed_entry({**base, "mode": "text"})
    text = render_tactile_key_image({**base, "mode": "text"}, tmp_path)
    both = render_tactile_key_image(base, tmp_path)
    assert ImageChops.difference(text.convert("RGB"), both.convert("RGB")).getbbox() is not None


def test_explicit_content_is_never_hidden_by_the_proposed_mode():
    icon_on_text_key = resolve_look({"action": {"type": "obs.set_scene", "scene": "A"}, "icon": "lucide:star"})
    assert icon_on_text_key["mode"] == "both" and icon_on_text_key["source"]["mode"] == "proposed"
    label_on_icon_key = resolve_look({"action": {"type": "spotify.next"}, "text": "Skip"})
    assert label_on_icon_key["mode"] == "both"
    # ...unless the user picked the mode.
    assert resolve_look({"action": {"type": "spotify.next"}, "text": "Skip", "mode": "icon"})["mode"] == "icon"


def test_live_key_keeps_its_own_text_and_colours():
    out = proposed_entry({"text": "13:54", "text_color": "#ff0000", "action": {"type": "display.clock"}})
    assert out["text"] == "13:54" and out["text_color"] == "#ff0000" and out["background"] == "#4a4f8f"


def test_entries_without_a_known_action_are_untouched():
    assert proposed_entry({"text": "Go", "background": "#123456"}) is None
    assert proposed_entry({"text": "Go", "action": {"type": "plugin.unknown"}}) is None


def test_device_render_equals_the_editor_preview(tmp_path: Path):
    from open_loupedeck.button_render import render_key_preview

    cases = [
        {"action": {"type": "obs.set_scene", "scene": "Just Chatting"}},
        {"action": {"type": "sound.play", "file": "x.wav"}, "text": "Clap", "background": "#22a35a"},
        {"action": {"type": "spotify.next"}, "mode": "text"},
        {"text": "Plain", "background": "#000000"},
        {"text": "Big", "background": "#000000", "mode": "text"},
    ]
    for entry in cases:
        device = render_tactile_key_image(entry, tmp_path)
        preview, _m = render_key_preview(entry, tmp_path)
        assert ImageChops.difference(device.convert("RGB"), preview.convert("RGB")).getbbox() is None, entry


def test_entries_without_action_still_render_nothing(tmp_path: Path):
    assert render_tactile_key_image({}, tmp_path) is None
    assert render_tactile_key_image({"action": {"type": "plugin.unknown"}}, tmp_path) is None


def test_actions_list_uses_first_action_look(tmp_path: Path):
    entry = {"actions": [{"type": "twitch.create_clip"}, {"type": "command.run"}]}
    assert proposed_entry(entry)["background"] == "#9146ff"


# --- HTTP -----------------------------------------------------------------------------------


def test_resolve_look_and_catalog_endpoints(tmp_path: Path):
    import asyncio

    from fastapi.testclient import TestClient

    from open_loupedeck.config_state import ConfigState
    from open_loupedeck.web_app import create_web_app

    cfg = tmp_path / "config.yaml"
    app = create_web_app(cfg, ConfigState(cfg), asyncio.Lock())
    client = TestClient(app)
    cat = client.get("/api/action_catalog").json()["actions"]
    assert all("default_look" in a for a in cat)
    r = client.post(
        "/api/resolve_look",
        json={"entry": {"action": {"type": "spotify.next"}}, "lang": "fr"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["label"] == "Suivant" and body["source"]["label"] == "proposed"
    assert client.post("/api/resolve_look", json={"entry": 3}).status_code == 400
