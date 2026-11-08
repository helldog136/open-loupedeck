"""``wow.keybind``: chord validation, exactly-one-chord sending, catalog entry, bundled icon-name list."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from types import SimpleNamespace

import pytest

from open_loupedeck import i18n, keyboard_replay
from open_loupedeck.action_catalog import ACTION_CATALOG, DEFAULT_LOOKS, merged_catalog
from open_loupedeck.actions import ActionContext, run_actions
from open_loupedeck.actions import builtins as actions_builtins
from open_loupedeck.keyboard_replay import parse_chord, send_chord_blocking
from open_loupedeck.look_defaults import resolve_look
from open_loupedeck.package_paths import package_root

# --- chord validation ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("ctrl+shift+f13", ["ctrl", "shift", "f13"]),
        ("Ctrl+Shift+F13", ["ctrl", "shift", "f13"]),
        (" shift + ctrl + f24 ", ["ctrl", "shift", "f24"]),
        ("alt+ctrl+shift+f1", ["ctrl", "alt", "shift", "f1"]),
        ("control+a", ["ctrl", "a"]),
        ("f5", ["f5"]),
        ("ctrl+7", ["ctrl", "7"]),
        ("shift+space", ["shift", "space"]),
        ("alt+pageup", ["alt", "pageup"]),
    ],
)
def test_parse_chord_accepts(text: str, expected: list[str]) -> None:
    assert parse_chord(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        None,
        "ctrl",
        "ctrl+shift",
        "ctrl+a+b",
        "a+b",
        "ctrl+ctrl+a",
        "ctrl++a",
        "+a",
        "ctrl+",
        "ctrl+f0",
        "ctrl+f25",
        "ctrl+f99",
        "win+a",
        "meta+a",
        "ctrl+altgr+a",
        "ctrl+nonsense",
        "ctrl+é",
        "ctrl+!",
    ],
)
def test_parse_chord_rejects(text: object) -> None:
    with pytest.raises(ValueError):
        parse_chord(text)


# --- sending exactly one chord ------------------------------------------------------------------


class _Fake:
    def __init__(self) -> None:
        self.events: list[tuple[str, object]] = []

    def press(self, key: object) -> None:
        self.events.append(("press", key))

    def release(self, key: object) -> None:
        self.events.append(("release", key))


_KEYS = SimpleNamespace(ctrl="<ctrl>", shift="<shift>", alt="<alt>", **{f"f{n}": f"<f{n}>" for n in range(1, 25)})


def _patch(monkeypatch: pytest.MonkeyPatch, fake: _Fake, keys: object = _KEYS) -> None:
    monkeypatch.setattr(keyboard_replay, "Controller", lambda: fake)
    monkeypatch.setattr(keyboard_replay, "Key", keys)
    monkeypatch.setattr(keyboard_replay.time, "sleep", lambda s: None)


def test_send_chord_presses_modifiers_then_key_and_releases_in_reverse(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _Fake()
    _patch(monkeypatch, fake)
    send_chord_blocking("ctrl+shift+f13")
    assert fake.events == [
        ("press", "<ctrl>"),
        ("press", "<shift>"),
        ("press", "<f13>"),
        ("release", "<f13>"),
        ("release", "<shift>"),
        ("release", "<ctrl>"),
    ]


def test_send_chord_single_key_and_letter(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _Fake()
    _patch(monkeypatch, fake)
    send_chord_blocking("f20")
    send_chord_blocking("alt+a")
    assert fake.events == [
        ("press", "<f20>"),
        ("release", "<f20>"),
        ("press", "<alt>"),
        ("press", "a"),
        ("release", "a"),
        ("release", "<alt>"),
    ]


def test_send_chord_holds_the_key_for_a_few_milliseconds(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _Fake()
    _patch(monkeypatch, fake)
    sleeps: list[float] = []
    monkeypatch.setattr(keyboard_replay.time, "sleep", sleeps.append)
    send_chord_blocking("ctrl+f13")
    assert sleeps == [keyboard_replay.CHORD_MODIFIER_LEAD_S, keyboard_replay.CHORD_HOLD_S]


def test_send_chord_invalid_sends_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _Fake()
    _patch(monkeypatch, fake)
    with pytest.raises(ValueError):
        send_chord_blocking("ctrl+a+b")
    assert fake.events == []


def test_send_chord_releases_modifiers_if_the_key_press_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    class Boom(_Fake):
        def press(self, key: object) -> None:
            if key == "<f13>":
                raise OSError("blocked")
            super().press(key)

    fake = Boom()
    _patch(monkeypatch, fake)
    with pytest.raises(OSError):
        send_chord_blocking("ctrl+f13")
    assert ("release", "<ctrl>") in fake.events


def test_key_missing_on_this_os_is_a_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """pynput on macOS only knows F1..F20."""

    fake = _Fake()
    mac_like = SimpleNamespace(
        ctrl="<ctrl>", shift="<shift>", alt="<alt>", **{f"f{n}": f"<f{n}>" for n in range(1, 21)}
    )
    _patch(monkeypatch, fake, mac_like)
    send_chord_blocking("ctrl+f20")
    with pytest.raises(ValueError, match="not available"):
        send_chord_blocking("ctrl+f22")


# --- the action ---------------------------------------------------------------------------------


def _ctx() -> ActionContext:
    return ActionContext(obs=None, http_client=None, log=logging.getLogger("t"), on_action_error=None)


def test_action_sends_one_chord_and_never_play_sequence(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[object] = []
    monkeypatch.setattr(actions_builtins, "send_chord_blocking", sent.append)
    monkeypatch.setattr(
        actions_builtins, "play_sequence_blocking", lambda *a, **k: pytest.fail("multi-step replay must not be used")
    )
    asyncio.run(run_actions(_ctx(), [{"type": "wow.keybind", "key": "ctrl+shift+f13", "macro_name": "Mount"}]))
    assert sent == ["ctrl+shift+f13"]


def test_action_rejects_bad_chord_without_sending(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[object] = []
    errors: list[object] = []
    monkeypatch.setattr(actions_builtins, "send_chord_blocking", sent.append)
    ctx = ActionContext(
        obs=None, http_client=None, log=logging.getLogger("t"), on_action_error=lambda *a, **k: errors.append(a)
    )
    asyncio.run(run_actions(ctx, [{"type": "wow.keybind", "key": "ctrl+a+b"}]))
    asyncio.run(run_actions(ctx, [{"type": "wow.keybind"}]))
    assert sent == []
    assert len(errors) == 2


# --- catalog ------------------------------------------------------------------------------------


def test_catalog_entry_and_default_look() -> None:
    entry = next(a for a in ACTION_CATALOG if a["type"] == "wow.keybind")
    assert entry["category"] == "wow"
    assert [f["name"] for f in entry["fields"]] == ["key", "macro_name"]
    assert entry["fields"][1].get("optional") is True
    look = DEFAULT_LOOKS["wow.keybind"]
    assert look["icon"] == "wow:inv_misc_questionmark"
    assert look["mode"] == "both" and look["label_from"] == "macro_name"
    assert re.fullmatch(r"#[0-9a-f]{6}", look["bg"])
    r, g, b = (int(look["bg"][i : i + 2], 16) for i in (1, 3, 5))
    assert r > g > b  # gold / brown family


@pytest.mark.parametrize("lang", ["en", "fr"])
def test_catalog_texts_translated(lang: str) -> None:
    item = next(c for c in merged_catalog(lang) if c["type"] == "wow.keybind")
    assert item["label"] != "wow.keybind" and item["category"] != "wow"
    assert item["help"] and "docs/wow.md" in item["help"]
    key = next(f for f in item["fields"] if f["name"] == "key")
    assert key["label"] != "key" and key["help"] and key["placeholder"] == "ctrl+shift+f13"
    for k in (
        "action.wow.keybind.field.macro_name.label",
        "look.wow.keybind.label",
        "inspector.chord.record",
        "inspector.chord.error.unknown",
        "picker.icon.tab.wow",
        "svc.general.wow_cache_clear",
        "svc.general.wow_cache_cleared",
        "pack.wow.name",
    ):
        assert i18n.t(k, lang) != k, f"{k} missing in {lang}"


def test_label_follows_macro_name_until_modified() -> None:
    entry = {"action": {"type": "wow.keybind", "key": "ctrl+f13", "macro_name": "Hearthstone"}}
    look = resolve_look(entry, "en")
    assert look["label"] == "Hearthstone" and look["icon"] == "wow:inv_misc_questionmark"
    assert resolve_look({"action": {"type": "wow.keybind", "key": "ctrl+f13"}}, "en")["label"] == "WoW"


# --- bundled icon names -------------------------------------------------------------------------

NAMES_FILE = package_root() / "static" / "js" / "pickers" / "wow-icons.json"
GROUPS = ["professions", "mounts", "consumables", "items", "misc"]


def test_icon_names_file_is_names_only_unique_and_valid() -> None:
    data = json.loads(NAMES_FILE.read_text(encoding="utf-8"))
    assert set(data) == {"categories", "keywords"}
    names: list[str] = []
    for cat in data["categories"]:
        assert set(cat) == {"id", "icons"}
        assert re.fullmatch(r"[a-z]+", cat["id"])
        assert cat["icons"], cat["id"]
        names += cat["icons"]
    assert len(names) == len(set(names)), "duplicate icon names"
    assert len(names) >= 300
    for n in names:
        assert re.fullmatch(r"[a-z0-9_]+", n) and len(n) <= 96, n
    ids = [c["id"] for c in data["categories"]]
    assert all(g in ids for g in GROUPS)
    assert {"warrior", "mage", "druid", "evoker"} <= set(ids)
    for known in ("inv_misc_questionmark", "inv_misc_rune_01", "ability_mount_ridinghorse", "spell_fire_fireball02"):
        assert known in names
    for n, words in data["keywords"].items():
        assert n in names and words and all(isinstance(w, str) for w in words)
    # only names and search words: no URL or image data anywhere
    assert "http" not in NAMES_FILE.read_text(encoding="utf-8")


def test_every_category_has_a_label_in_both_languages() -> None:
    data = json.loads(NAMES_FILE.read_text(encoding="utf-8"))
    for cat in data["categories"]:
        for lang in ("en", "fr"):
            assert i18n.t(f"picker.icon.wow.cat.{cat['id']}", lang) != f"picker.icon.wow.cat.{cat['id']}", cat["id"]


def test_no_wow_image_is_bundled() -> None:
    root = package_root()
    bad = [
        p
        for p in root.rglob("*")
        if p.is_file()
        and "wow" in p.name.lower()
        and p.suffix.lower() in {".jpg", ".png", ".jpeg", ".gif", ".webp", ".blp"}
    ]
    assert bad == []
