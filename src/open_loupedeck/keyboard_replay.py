"""Synthetic keyboard input for the ``keyboard.play_sequence`` action (pynput-based).

Recording happens in the browser (the UI captures real ``keydown`` events while the user presses
their intended combo); this module only handles replay -- sending those same keys to the OS so
they land in whatever application currently has focus, exactly like a physical keyboard would.
"""

from __future__ import annotations

import time
from typing import Any

from pynput.keyboard import Controller, Key

_NAMED_KEYS: dict[str, Key] = {
    "ctrl": Key.ctrl,
    "control": Key.ctrl,
    "shift": Key.shift,
    "alt": Key.alt,
    "altgr": Key.alt_gr,
    "alt_gr": Key.alt_gr,
    "meta": Key.cmd,
    "win": Key.cmd,
    "cmd": Key.cmd,
    "super": Key.cmd,
    "tab": Key.tab,
    "enter": Key.enter,
    "return": Key.enter,
    "esc": Key.esc,
    "escape": Key.esc,
    "space": Key.space,
    "backspace": Key.backspace,
    "delete": Key.delete,
    "insert": Key.insert,
    "up": Key.up,
    "down": Key.down,
    "left": Key.left,
    "right": Key.right,
    "home": Key.home,
    "end": Key.end,
    "pageup": Key.page_up,
    "page_up": Key.page_up,
    "pagedown": Key.page_down,
    "page_down": Key.page_down,
    "capslock": Key.caps_lock,
    "caps_lock": Key.caps_lock,
    "numlock": Key.num_lock,
    "num_lock": Key.num_lock,
    "printscreen": Key.print_screen,
    "print_screen": Key.print_screen,
    "menu": Key.menu,
    "pause": Key.pause,
}
for _n in range(1, 25):
    _f_key = getattr(Key, f"f{_n}", None)
    if _f_key is not None:
        _NAMED_KEYS[f"f{_n}"] = _f_key


def resolve_key(name: str) -> Any:
    """Map a canonical key name (as produced by the UI recorder) to a pynput key/character.

    Single characters (``"a"``, ``"A"``, ``"!"``, ``"5"``, ...) are passed straight to pynput,
    which handles producing the right character -- including any shift it implies -- on its own;
    only named keys (modifiers, arrows, function keys, ...) need mapping to ``pynput.keyboard.Key``.
    """

    raw = str(name)
    lowered = raw.strip().lower()
    if lowered in _NAMED_KEYS:
        return _NAMED_KEYS[lowered]
    return raw


def _play_sequence_sync(steps: list[Any], delay_ms: float) -> None:
    controller = Controller()
    delay_s = max(0.0, delay_ms) / 1000.0
    for step in steps:
        keys = step.get("keys") if isinstance(step, dict) else None
        if not keys:
            continue
        resolved = [resolve_key(k) for k in keys]
        for k in resolved:
            controller.press(k)
        for k in reversed(resolved):
            controller.release(k)
        if delay_s:
            time.sleep(delay_s)


def play_sequence_blocking(steps: list[Any], delay_ms: float = 30.0) -> None:
    """Synchronous entry point (call via ``asyncio.to_thread`` from async code)."""

    _play_sequence_sync(steps, delay_ms)
