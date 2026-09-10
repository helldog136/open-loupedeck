"""``keyboard_replay``: key-name resolution and chord press/release ordering.

Deliberately never imports real ``pynput`` -- its backend resolves eagerly at import time and
raises on a headless CI runner (no DISPLAY on Linux, no windowing session on macOS). Both
``Controller`` and ``Key`` are faked via monkeypatch instead, matching how keyboard_replay.py is
designed to be used (lazy, mockable module attributes) -- see its module docstring.
"""

from __future__ import annotations

from types import SimpleNamespace

from open_loupedeck import keyboard_replay
from open_loupedeck.keyboard_replay import NamedKey, play_sequence_blocking, resolve_key

_FAKE_KEY = SimpleNamespace(
    ctrl="<ctrl>", shift="<shift>", alt="<alt>", cmd="<cmd>", tab="<tab>", esc="<esc>", f5="<f5>"
)


def test_resolve_key_maps_named_modifiers_and_specials_to_sentinels():
    assert resolve_key("ctrl") == NamedKey("ctrl")
    assert resolve_key("Ctrl") == NamedKey("ctrl")
    assert resolve_key("alt") == NamedKey("alt")
    assert resolve_key("shift") == NamedKey("shift")
    assert resolve_key("meta") == NamedKey("cmd")
    assert resolve_key("win") == NamedKey("cmd")
    assert resolve_key("tab") == NamedKey("tab")
    assert resolve_key("escape") == NamedKey("esc")
    assert resolve_key("f5") == NamedKey("f5")


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


def _patch_pynput(monkeypatch, fake_controller: _FakeController) -> None:
    monkeypatch.setattr(keyboard_replay, "Controller", lambda: fake_controller)
    monkeypatch.setattr(keyboard_replay, "Key", _FAKE_KEY)


def test_play_sequence_presses_chord_then_releases_in_reverse_order(monkeypatch):
    fake = _FakeController()
    _patch_pynput(monkeypatch, fake)

    play_sequence_blocking([{"keys": ["ctrl", "shift", "s"]}], delay_ms=0)

    assert fake.events == [
        ("press", "<ctrl>"),
        ("press", "<shift>"),
        ("press", "s"),
        ("release", "s"),
        ("release", "<shift>"),
        ("release", "<ctrl>"),
    ]


def test_play_sequence_runs_multiple_steps_in_order(monkeypatch):
    fake = _FakeController()
    _patch_pynput(monkeypatch, fake)

    play_sequence_blocking([{"keys": ["ctrl", "c"]}, {"keys": ["ctrl", "v"]}], delay_ms=0)

    assert fake.events == [
        ("press", "<ctrl>"),
        ("press", "c"),
        ("release", "c"),
        ("release", "<ctrl>"),
        ("press", "<ctrl>"),
        ("press", "v"),
        ("release", "v"),
        ("release", "<ctrl>"),
    ]


def test_play_sequence_skips_steps_without_keys(monkeypatch):
    fake = _FakeController()
    _patch_pynput(monkeypatch, fake)

    play_sequence_blocking([{"keys": []}, {}, {"keys": ["a"]}], delay_ms=0)

    assert fake.events == [("press", "a"), ("release", "a")]
