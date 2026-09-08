from __future__ import annotations

import asyncio

import pytest

from open_loupedeck.events import NormalizedEvent
from open_loupedeck.page_runtime import PageNavigator, actions_for_page_event


def _touch(idx: int) -> NormalizedEvent:
    return NormalizedEvent(kind="touch", id=idx, edge="down", raw={})


def _button(bid: str) -> NormalizedEvent:
    return NormalizedEvent(kind="button", id=bid, edge="down", raw={})


PAGES = [
    {
        "id": 0,
        "name": "Main",
        "buttons": {
            "touch_0": {"action": {"type": "obs.set_scene", "scene": "A"}},
            "touch_1": {"actions": []},  # empty list must not shadow a sibling `action`
        },
    },
    {"id": 1, "name": "Second", "buttons": {}},
]


def test_page_button_matches_by_control_id():
    cid, actions, entry = actions_for_page_event(PAGES, 0, _touch(0))
    assert cid == "touch_0"
    assert actions == [{"type": "obs.set_scene", "scene": "A"}]
    assert entry == {"action": {"type": "obs.set_scene", "scene": "A"}}


def test_no_match_returns_empty():
    cid, actions, entry = actions_for_page_event(PAGES, 0, _touch(5))
    assert cid is None
    assert actions == []
    assert entry is None


def test_page_index_wraps_modulo_page_count():
    # index 2 with 2 pages -> page 0
    cid, actions, _entry = actions_for_page_event(PAGES, 2, _touch(0))
    assert cid == "touch_0"
    assert actions


def test_global_buttons_preferred_for_non_touch_controls():
    gb = {"btn_1": {"action": {"type": "agent.next_page"}}}
    cid, actions, entry = actions_for_page_event(PAGES, 0, _button("btn_1"), global_buttons=gb)
    assert cid == "btn_1"
    assert actions == [{"type": "agent.next_page"}]
    assert entry == gb["btn_1"]


def test_empty_global_entry_does_not_shadow_per_page_button_entry():
    # An empty {} global_buttons entry (e.g. left over from UI normalization) must not hide
    # a real per-page binding for the same non-touch control id.
    pages = [{"id": 0, "name": "Main", "buttons": {"btn_1": {"action": {"type": "agent.next_page"}}}}]
    gb = {"btn_1": {}}
    cid, actions, _entry = actions_for_page_event(pages, 0, _button("btn_1"), global_buttons=gb)
    assert cid == "btn_1"
    assert actions == [{"type": "agent.next_page"}]


def test_actions_from_entry_rejects_non_list_actions():
    bad_pages = [{"id": 0, "name": "X", "buttons": {"touch_0": {"actions": "not-a-list"}}}]
    with pytest.raises(ValueError, match="must be a list"):
        actions_for_page_event(bad_pages, 0, _touch(0))


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
