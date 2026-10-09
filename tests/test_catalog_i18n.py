"""The action catalog is fully translated through the locale files (en + fr), per language on request."""

from __future__ import annotations

import asyncio
import importlib.util
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from open_loupedeck import action_catalog as ac
from open_loupedeck import i18n
from open_loupedeck.config_state import ConfigState
from open_loupedeck.web_app import create_web_app

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_catalog_keys.py"
_spec = importlib.util.spec_from_file_location("check_catalog_keys", _SCRIPT)
assert _spec and _spec.loader
check_catalog_keys = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_catalog_keys)

LANGS = ("en", "fr")
PLACEHOLDER = re.compile(r"\{(\w+)\}")


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    cfg = tmp_path / "config.yaml"
    return TestClient(create_web_app(cfg, ConfigState(cfg), asyncio.Lock()))


def _catalog(client: TestClient, lang: str) -> dict[str, dict]:
    body = client.get("/api/action_catalog", params={"lang": lang}).json()
    return {a["type"]: a for a in body["actions"]}


def test_catalog_key_script_is_green():
    assert check_catalog_keys.check_catalog_keys(i18n.locales_dir()) == []


def test_script_reports_missing_and_stray_keys(tmp_path: Path):
    import json

    en = {k: v for k, v in i18n.messages_for("en").items() if k != "action.obs.set_scene.label"}
    en["look.nope.label"] = "Nope"
    (tmp_path / "en.json").write_text(json.dumps(en))
    msg = "\n".join(check_catalog_keys.check_catalog_keys(tmp_path))
    assert "action.obs.set_scene.label" in msg and "look.nope.label" in msg


@pytest.mark.parametrize("lang", LANGS)
def test_every_action_field_category_and_look_has_a_key(lang: str):
    msgs = i18n.messages_for(lang)
    own = i18n._load_file(lang)
    for entry in ac.ACTION_CATALOG:
        t = entry["type"]
        needed = [ac.label_key(t), ac.category_key(entry["category"]), f"look.{t}.label"]
        for f in entry["fields"]:
            needed.append(ac.field_key(t, f["name"], "label"))
            needed += [ac.option_key(t, f["name"], o) for o in f.get("options", []) if ac.option_has_key(o)]
            assert not (f.get("placeholder") and not f["placeholder"].isdigit()), f"{t}.{f['name']}: literal text"
        for key in needed:
            assert own.get(key, "").strip(), f"{lang}: missing {key}"
            assert msgs[key]
        assert "label" not in entry, f"{t}: English must live in the locale files"


def test_placeholders_and_vars_are_preserved_in_french():
    en, fr = i18n.messages_for("en"), i18n.messages_for("fr")
    for key, text in en.items():
        if key.startswith(("action.", "look.", "category.")):
            assert set(PLACEHOLDER.findall(text)) <= set(PLACEHOLDER.findall(fr[key])), key


def test_endpoint_returns_french_labels_with_keys(client: TestClient):
    fr, en = _catalog(client, "fr"), _catalog(client, "en")
    assert en["obs.set_scene"]["label"] == "OBS — set program scene"
    assert fr["obs.set_scene"]["label"] == "OBS — changer la scène du programme"
    assert fr["obs.set_scene"]["label_key"] == "action.obs.set_scene.label"
    assert fr["obs.set_scene"]["category"] == "OBS" and fr["sound.play"]["category"] == "Son"
    assert fr["sound.play"]["category_key"] == "category.sound"
    scene = fr["obs.set_scene"]["fields"][0]
    assert scene["label"] == "Nom de la scène" and scene["label_key"] == "action.obs.set_scene.field.scene.label"
    assert scene["placeholder_key"] == "action.obs.set_scene.field.scene.placeholder"
    assert fr["spotify.next"]["default_look"]["label_key"] == "look.spotify.next.label"


def test_endpoint_option_labels(client: TestClient):
    fr, en = _catalog(client, "fr"), _catalog(client, "en")
    mode = next(f for f in fr["sound.mute_toggle"]["fields"] if f["name"] == "mode")
    assert mode["options"] == ["toggle", "mute", "unmute"]  # values unchanged
    assert mode["option_labels"] == {"toggle": "Basculer", "mute": "Couper le son", "unmute": "Rétablir le son"}
    method = next(f for f in en["http.request"]["fields"] if f["name"] == "method")
    assert method["option_labels"]["GET"] == "GET" and method["option_label_keys"] == {}


def test_numeric_placeholders_stay_raw(client: TestClient):
    timeout = next(f for f in _catalog(client, "fr")["http.request"]["fields"] if f["name"] == "timeout")
    assert timeout["placeholder"] == "15" and "placeholder_key" not in timeout


@pytest.mark.parametrize("lang", ["xx", "de", ""])
def test_unknown_language_falls_back_to_english(client: TestClient, lang: str):
    cat = _catalog(client, lang)
    body = client.get("/api/action_catalog", params={"lang": lang}).json()
    if lang:
        assert body["lang"] == "en"
        assert cat["obs.set_scene"]["label"] == "OBS — set program scene"


def test_default_language_follows_the_current_language(client: TestClient):
    before = i18n.get_language()
    try:
        i18n.set_language("fr")
        assert _catalog(client, "")["twitch.raid"]["label"] == "Twitch — lancer un raid"
        i18n.set_language("en")
        assert _catalog(client, "")["twitch.raid"]["label"] == "Twitch — start raid"
    finally:
        i18n.set_language(before)


def test_french_catalog_has_no_english_leftovers():
    """Every French catalog text (action titles) differs from English."""

    en, fr = i18n.messages_for("en"), i18n.messages_for("fr")
    same = [k for k in en if k.startswith("action.") and ".field." not in k and k.endswith(".label") and en[k] == fr[k]]
    assert same == []


def test_plugin_action_without_keys_keeps_working(monkeypatch: pytest.MonkeyPatch):
    from open_loupedeck.actions import registry

    monkeypatch.setattr(registry, "registered_action_kinds", lambda: ["myplugin.foo_bar", "obs.set_scene"])
    cat = {e["type"]: e for e in ac.merged_catalog("fr")}
    plug = cat["myplugin.foo_bar"]
    assert plug["label"] == "myplugin.foo_bar" and plug["category"] == "Myplugin"
    assert plug["params_json"] is True and plug["fields"] == []
    assert plug["label_key"] == "action.myplugin.foo_bar.label"
    assert cat["obs.set_scene"]["label"].startswith("OBS — ")


def test_missing_key_falls_back_to_english(monkeypatch: pytest.MonkeyPatch):
    fr = dict(i18n._load_file("fr"))
    del fr["action.obs.set_scene.label"]
    monkeypatch.setitem(i18n._cache, "fr", fr)
    cat = {e["type"]: e for e in ac.merged_catalog("fr")}
    assert cat["obs.set_scene"]["label"] == "OBS — set program scene"
