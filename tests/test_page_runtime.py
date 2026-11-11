from __future__ import annotations

import asyncio

import pytest

from open_loupedeck.bindings import actions_of, iter_bindings, resolve_binding, resolve_in
from open_loupedeck.page_runtime import PageNavigator, actions_for_control

PAGES = [
    {
        "id": 0,
        "name": "Main",
        "controls": {
            "key_0_0": {"action": {"type": "obs.set_scene", "scene": "A"}},
            "key_1_0": {"actions": [], "action": {"type": "b"}},  # empty list must not shadow `action`
            "button_1": {"action": {"type": "page.override"}},
            "knob_0": {"rotate": {"duo": "system_volume"}},
        },
    },
    {"id": 1, "name": "Second", "controls": {}},
]
GLOBAL = {
    "button_1": {"action": {"type": "agent.next_page"}},
    "button_2": {"action": {"type": "agent.prev_page"}},
    "key_0_0": {"text": "global key"},
    "knob_0": {"press": {"type": "sound.mute_toggle"}},
}
RAW = {"global": GLOBAL, "pages": PAGES}


def test_page_binding_matches_by_control_id():
    b, actions = actions_for_control(RAW, 0, "key_0_0")
    assert b is not None and b.scope == "page" and b.storage_key == "p0:key_0_0"
    assert actions == [{"type": "obs.set_scene", "scene": "A"}]
    assert b.entry == PAGES[0]["controls"]["key_0_0"]
    assert actions_for_control(RAW, 0, "key_1_0")[1] == [{"type": "b"}]


def test_no_binding_returns_empty():
    assert actions_for_control(RAW, 0, "key_4_2") == (None, [])
    assert actions_for_control({"pages": []}, 0, "key_0_0") == (None, [])


def test_page_index_wraps_modulo_page_count():
    b, actions = actions_for_control(RAW, 2, "key_0_0")  # index 2 with 2 pages -> page 0
    assert b is not None and b.page_index == 0 and actions


def test_page_overrides_global_and_global_is_the_fallback():
    # Same rule for every kind of control.
    assert resolve_binding(RAW, 0, "button_1").entry == {"action": {"type": "page.override"}}
    assert resolve_binding(RAW, 1, "button_1").entry == GLOBAL["button_1"]
    assert resolve_binding(RAW, 1, "button_1").storage_key == "g:button_1"
    assert resolve_binding(RAW, 0, "button_2").scope == "global"
    assert resolve_binding(RAW, 1, "key_0_0").entry == {"text": "global key"}
    assert resolve_binding(RAW, 0, "knob_0").entry == {"rotate": {"duo": "system_volume"}}
    assert resolve_binding(RAW, 1, "knob_0").entry == GLOBAL["knob_0"]
    assert resolve_binding(RAW, 1, "button_3") is None
    assert resolve_in(None, GLOBAL, "button_2").scope == "global"


def test_iter_bindings_covers_global_and_pages():
    keys = [sk for sk, _cid, _e in iter_bindings(RAW)]
    assert keys[:4] == ["g:button_1", "g:button_2", "g:key_0_0", "g:knob_0"]
    assert "p0:knob_0" in keys and "p0:button_1" in keys


def test_actions_of_rejects_non_list_actions():
    with pytest.raises(ValueError, match="must be a list"):
        actions_of({"actions": "not-a-list"})
    with pytest.raises(ValueError, match="mapping"):
        actions_of({"action": "nope"})


class _Navigator:
    def __init__(self, pages: list[dict]) -> None:
        self.pages = pages
        self.index = 0
        self.redraws = 0

    def build(self) -> PageNavigator:
        async def on_change() -> None:
            self.redraws += 1

        return PageNavigator(
            get_pages=lambda: self.pages,
            get_index=lambda: self.index,
            set_index=self._set_index,
            on_change=on_change,
        )

    def _set_index(self, i: int) -> None:
        self.index = i


def test_navigator_next_prev_wrap_and_trigger_redraw():
    state = _Navigator(PAGES)
    nav = state.build()

    asyncio.run(nav.next_page())
    assert state.index == 1
    assert state.redraws == 1

    asyncio.run(nav.next_page())  # wraps back to 0
    assert state.index == 0

    asyncio.run(nav.prev_page())  # wraps to last page
    assert state.index == 1


def test_navigator_goto_page_by_name_and_unknown_name_is_noop():
    state = _Navigator(PAGES)
    nav = state.build()

    asyncio.run(nav.goto_page(name="Second"))
    assert state.index == 1

    asyncio.run(nav.goto_page(name="Nonexistent"))
    assert state.index == 1  # unchanged
