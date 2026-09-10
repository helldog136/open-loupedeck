"""``keyboard.play_sequence`` action: validation and dispatch to keyboard_replay."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from open_loupedeck.actions import ActionContext, run_actions
from open_loupedeck.actions import builtins as actions_builtins


def _ctx(on_error=None) -> ActionContext:
    return ActionContext(obs=None, http_client=None, log=logging.getLogger("t"), on_action_error=on_error)


def _run(coro):
    return asyncio.run(coro)


def test_play_sequence_calls_replay_with_steps_and_delay(monkeypatch):
    calls: list[tuple[Any, Any]] = []

    def fake_play(steps, delay_ms):
        calls.append((steps, delay_ms))

    monkeypatch.setattr(actions_builtins, "play_sequence_blocking", fake_play)

    steps = [{"keys": ["ctrl", "c"]}, {"keys": ["ctrl", "v"]}]
    _run(run_actions(_ctx(), [{"type": "keyboard.play_sequence", "steps": steps, "delay_ms": 50}]))

    assert calls == [(steps, 50.0)]


def test_play_sequence_defaults_delay_when_omitted(monkeypatch):
    calls: list[tuple[Any, Any]] = []
    monkeypatch.setattr(actions_builtins, "play_sequence_blocking", lambda steps, delay_ms: calls.append(delay_ms))

    _run(run_actions(_ctx(), [{"type": "keyboard.play_sequence", "steps": [{"keys": ["a"]}]}]))

    assert calls == [30.0]


def test_play_sequence_errors_on_missing_steps(monkeypatch):
    errors: list[BaseException] = []
    monkeypatch.setattr(actions_builtins, "play_sequence_blocking", lambda *a, **k: None)

    _run(run_actions(_ctx(lambda kind, params, exc: errors.append(exc)), [{"type": "keyboard.play_sequence"}]))

    assert len(errors) == 1
    assert isinstance(errors[0], ValueError)


def test_play_sequence_errors_on_empty_steps(monkeypatch):
    errors: list[BaseException] = []
    monkeypatch.setattr(actions_builtins, "play_sequence_blocking", lambda *a, **k: None)

    actions = [{"type": "keyboard.play_sequence", "steps": []}]
    _run(run_actions(_ctx(lambda kind, params, exc: errors.append(exc)), actions))

    assert len(errors) == 1
    assert isinstance(errors[0], ValueError)
