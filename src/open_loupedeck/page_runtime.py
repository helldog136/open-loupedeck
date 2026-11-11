"""Binding lookup for a press, and page navigation."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from .bindings import Binding, actions_of, resolve_binding

logger = logging.getLogger(__name__)


def actions_for_control(
    raw: dict[str, Any],
    page_index: int,
    control_id: str,
) -> tuple[Binding | None, list[dict[str, Any]]]:
    """``(binding, actions)`` of a press on ``control_id`` on the current page.

    The binding comes from the one resolution rule (page binding, else global; see
    :mod:`.bindings`); ``binding`` is ``None`` when the control has none on this page. Its entry
    also carries the visual fields (e.g. ``press_animation``).
    """

    b = resolve_binding(raw, page_index, control_id)
    if b is None:
        logger.debug("No binding for %s on page %s", control_id, page_index)
        return None, []
    acts = actions_of(b.entry)
    logger.debug("Matched %s binding %s (%s action(s))", b.scope, control_id, len(acts))
    return b, acts


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
