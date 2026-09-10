"""``keyboard_replay``: key-name resolution and chord press/release ordering."""

from __future__ import annotations

from pynput.keyboard import Key

from open_loupedeck import keyboard_replay
from open_loupedeck.keyboard_replay import play_sequence_blocking, resolve_key


def test_resolve_key_maps_named_modifiers_and_specials():
    assert resolve_key("ctrl") == Key.ctrl
    assert resolve_key("Ctrl") == Key.ctrl
    assert resolve_key("alt") == Key.alt
    assert resolve_key("shift") == Key.shift
    assert resolve_key("meta") == Key.cmd
    assert resolve_key("win") == Key.cmd
    assert resolve_key("tab") == Key.tab
    assert resolve_key("escape") == Key.esc
    assert resolve_key("f5") == Key.f5


def test_resolve_key_passes_through_plain_characters():
    assert resolve_key("a") == "a"
    assert resolve_key("A") == "A"
    assert resolve_key("!") == "!"
    assert resolve_key("5") == "5"


class _FakeController:
    def __init__(self) -> None:
        self.events: list[tuple[str, object]] = []

    def press(self, key) -> None:
        self.events.append(("press", key))

    def release(self, key) -> None:
        self.events.append(("release", key))


def test_play_sequence_presses_chord_then_releases_in_reverse_order(monkeypatch):
    fake = _FakeController()
    monkeypatch.setattr(keyboard_replay, "Controller", lambda: fake)

    play_sequence_blocking([{"keys": ["ctrl", "shift", "s"]}], delay_ms=0)

    assert fake.events == [
        ("press", Key.ctrl),
        ("press", Key.shift),
        ("press", "s"),
        ("release", "s"),
        ("release", Key.shift),
        ("release", Key.ctrl),
    ]


def test_play_sequence_runs_multiple_steps_in_order(monkeypatch):
    fake = _FakeController()
    monkeypatch.setattr(keyboard_replay, "Controller", lambda: fake)

    play_sequence_blocking([{"keys": ["ctrl", "c"]}, {"keys": ["ctrl", "v"]}], delay_ms=0)

    assert fake.events == [
        ("press", Key.ctrl),
        ("press", "c"),
        ("release", "c"),
        ("release", Key.ctrl),
        ("press", Key.ctrl),
        ("press", "v"),
        ("release", "v"),
        ("release", Key.ctrl),
    ]


def test_play_sequence_skips_steps_without_keys(monkeypatch):
    fake = _FakeController()
    monkeypatch.setattr(keyboard_replay, "Controller", lambda: fake)

    play_sequence_blocking([{"keys": []}, {}, {"keys": ["a"]}], delay_ms=0)

    assert fake.events == [("press", "a"), ("release", "a")]
