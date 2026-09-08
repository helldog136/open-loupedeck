"""Per-page button lookup and page navigation."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from .control_ids import control_ids_for_lookup, is_page_scoped_control
from .events import NormalizedEvent

logger = logging.getLogger(__name__)


def _actions_from_entry(entry: dict[str, Any]) -> list[dict[str, Any]]:
    """Prefer a non-empty ``actions`` list; otherwise use singular ``action``.

    An empty ``actions: []`` must not hide a valid ``action`` (common when hand-editing YAML).
    """

    if "actions" in entry:
        a = entry["actions"]
        if isinstance(a, list) and len(a) > 0:
            return list(a)
        if a is not None and not isinstance(a, list):
            raise ValueError("buttons[].actions must be a list")
    if "action" in entry:
        act = entry["action"]
        if isinstance(act, dict):
            return [act]
        raise ValueError("buttons[].action must be a mapping")
    return []


def actions_for_page_event(
    pages: list[dict[str, Any]],
    page_index: int,
    ev: NormalizedEvent,
    global_buttons: dict[str, Any] | None = None,
) -> tuple[str | None, list[dict[str, Any]], dict[str, Any] | None]:
    """Returns ``(control_id, actions, entry)``; ``entry`` is the matched button's own config

    (used by callers that also need its visual fields, e.g. ``press_animation``), or ``None``
    when nothing matched.
    """

    if not pages:
        return None, [], None
    page = pages[page_index % len(pages)]
    buttons = page.get("buttons") or {}
    if not isinstance(buttons, dict):
        return None, [], None

    gb = global_buttons if isinstance(global_buttons, dict) else {}

    cids = [c for c in control_ids_for_lookup(ev) if c]
    logger.debug(
        "Page button lookup page_index=%s page=%r control_ids=%s",
        page_index,
        page.get("name"),
        cids,
    )
    for cid in cids:
        if is_page_scoped_control(cid):
            entry = buttons.get(cid)
        else:
            # Prefer global_buttons for non-touch controls, but don't let an empty global entry
            # (e.g. {} from normalization) shadow a valid per-page binding.
            raw_gb = gb.get(cid)
            entry_gb = raw_gb if isinstance(raw_gb, dict) else None
            if isinstance(entry_gb, dict):
                acts_gb = _actions_from_entry(entry_gb)
                if acts_gb:
                    logger.debug("Matched global button %s (%s action(s))", cid, len(acts_gb))
                    return cid, acts_gb, entry_gb
            entry = buttons.get(cid)
        if not isinstance(entry, dict):
            continue
        acts = _actions_from_entry(entry)
        if acts:
            logger.debug("Matched page button %s (%s action(s))", cid, len(acts))
            return cid, acts, entry
    logger.debug("No page button match for page %r", page.get("name"))
    return None, [], None


class PageNavigator:
    """Mutable page index + async redraw hook for agent.* actions."""

    def __init__(
        self,
        get_pages: Callable[[], list[dict[str, Any]]],
        get_index: Callable[[], int],
        set_index: Callable[[int], None],
        on_change: Callable[[], Awaitable[None]],
    ) -> None:
        self._get_pages = get_pages
        self._get_index = get_index
        self._set_index = set_index
        self._on_change = on_change

    def current_name(self) -> str:
        pages = self._get_pages()
        if not pages:
            return ""
        p = pages[self._get_index() % len(pages)]
        return str(p.get("name", ""))

    async def next_page(self) -> None:
        pages = self._get_pages()
        if not pages:
            return
        i = (self._get_index() + 1) % len(pages)
        self._set_index(i)
        logger.info("Page -> %s (%s)", i, self.current_name())
        await self._on_change()

    async def prev_page(self) -> None:
        pages = self._get_pages()
        if not pages:
            return
        i = (self._get_index() - 1) % len(pages)
        self._set_index(i)
        logger.info("Page -> %s (%s)", i, self.current_name())
        await self._on_change()

    async def goto_page(
        self,
        index: int | None = None,
        name: str | None = None,
        page_id: str | None = None,
    ) -> None:
        pages = self._get_pages()
        if not pages:
            return
        if page_id is not None:
            ids = [str(p.get("id", "")) for p in pages]
            try:
                idx = ids.index(str(page_id))
            except ValueError:
                logger.warning("Unknown page id %r", page_id)
                return
            self._set_index(idx)
        elif name is not None:
            names = [str(p.get("name", "")) for p in pages]
            try:
                idx = names.index(str(name))
            except ValueError:
                logger.warning("Unknown page name %r", name)
                return
            self._set_index(idx)
        elif index is not None:
            self._set_index(int(index) % len(pages))
        await self._on_change()
