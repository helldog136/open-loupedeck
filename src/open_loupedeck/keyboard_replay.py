"""Synthetic keyboard input for the ``keyboard.play_sequence`` action (pynput-based).

Recording happens in the browser (the UI captures real ``keydown`` events while the user presses
their intended combo); this module only handles replay -- sending those same keys to the OS so
they land in whatever application currently has focus, exactly like a physical keyboard would.

``pynput.keyboard`` resolves its OS backend (X11/Quartz/Win32) as soon as it is imported, not
lazily on first use -- on a headless Linux box (no ``DISPLAY``, as in CI) or a restricted macOS
session, that import raises immediately. Since this module is imported unconditionally as part of
the action registry, a top-level ``import pynput`` would take down *every* action, not just this
one, on any machine where pynput's backend can't resolve. ``Controller``/``Key`` are therefore
loaded lazily, only when a sequence is actually replayed -- and exposed as module attributes
(rather than only local imports) so tests can substitute fakes without ever touching real pynput.
"""

from __future__ import annotations

import time
from typing import Any

Controller: Any = None
Key: Any = None


def _controller_class() -> Any:
    global Controller
    if Controller is None:
        from pynput.keyboard import Controller as _Controller

        Controller = _Controller
    return Controller


def _key_enum() -> Any:
    global Key
    if Key is None:
        from pynput.keyboard import Key as _Key

        Key = _Key
    return Key


class NamedKey:
    """A named key (modifier, arrow, function key, ...), resolved to ``pynput.keyboard.Key`` only
    at replay time -- see the module docstring for why this can't be a real ``Key`` reference."""

    __slots__ = ("attr",)

    def __init__(self, attr: str) -> None:
        self.attr = attr

    def __eq__(self, other: object) -> bool:
        return isinstance(other, NamedKey) and other.attr == self.attr

    def __hash__(self) -> int:
        return hash(("NamedKey", self.attr))

    def __repr__(self) -> str:
        return f"NamedKey({self.attr!r})"


# Canonical name (as produced by the UI recorder) -> pynput.keyboard.Key attribute name.
_NAMED_KEY_ATTRS: dict[str, str] = {
    "ctrl": "ctrl",
    "control": "ctrl",
    "shift": "shift",
    "alt": "alt",
    "altgr": "alt_gr",
    "alt_gr": "alt_gr",
    "meta": "cmd",
    "win": "cmd",
    "cmd": "cmd",
    "super": "cmd",
    "tab": "tab",
    "enter": "enter",
    "return": "enter",
    "esc": "esc",
    "escape": "esc",
    "space": "space",
    "backspace": "backspace",
    "delete": "delete",
    "insert": "insert",
    "up": "up",
    "down": "down",
    "left": "left",
    "right": "right",
    "home": "home",
    "end": "end",
    "pageup": "page_up",
    "page_up": "page_up",
    "pagedown": "page_down",
    "page_down": "page_down",
    "capslock": "caps_lock",
    "caps_lock": "caps_lock",
    "numlock": "num_lock",
    "num_lock": "num_lock",
    "printscreen": "print_screen",
    "print_screen": "print_screen",
    "menu": "menu",
    "pause": "pause",
}
for _n in range(1, 25):
    _NAMED_KEY_ATTRS[f"f{_n}"] = f"f{_n}"


def resolve_key(name: str) -> str | NamedKey:
    """Map a canonical key name (as produced by the UI recorder) to a replay-ready key reference.

    Single characters (``"a"``, ``"A"``, ``"!"``, ``"5"``, ...) are passed straight to pynput,
    which handles producing the right character -- including any shift it implies -- on its own;
    only named keys (modifiers, arrows, function keys, ...) need mapping to ``pynput.keyboard.Key``
    (deferred: see ``_pynput_key``).
    """

    raw = str(name)
    lowered = raw.strip().lower()
    attr = _NAMED_KEY_ATTRS.get(lowered)
    if attr is not None:
        return NamedKey(attr)
    return raw


def _pynput_key(resolved: str | NamedKey) -> Any:
    if isinstance(resolved, NamedKey):
        return getattr(_key_enum(), resolved.attr)
    return resolved


def _play_sequence_sync(steps: list[Any], delay_ms: float) -> None:
    controller = _controller_class()()
    delay_s = max(0.0, delay_ms) / 1000.0
    for step in steps:
        keys = step.get("keys") if isinstance(step, dict) else None
        if not keys:
            continue
        resolved = [_pynput_key(resolve_key(k)) for k in keys]
        for k in resolved:
            controller.press(k)
        for k in reversed(resolved):
            controller.release(k)
        if delay_s:
            time.sleep(delay_s)


def play_sequence_blocking(steps: list[Any], delay_ms: float = 30.0) -> None:
    """Synchronous entry point (call via ``asyncio.to_thread`` from async code)."""

    _play_sequence_sync(steps, delay_ms)
