"""Match normalized events against binding rules."""

from __future__ import annotations

import logging
from typing import Any

from .events import NormalizedEvent

logger = logging.getLogger(__name__)


def event_matches_rule(match: dict[str, Any], ev: NormalizedEvent) -> bool:
    m_type = match.get("type")
    if m_type != ev.kind:
        return False

    if ev.kind == "touch":
        want = match.get("key")
        if want is None:
            return False
        if int(want) != int(ev.id):
            return False
    else:
        want_id = match.get("id")
        if want_id is None:
            return False
        if str(want_id) != str(ev.id):
            return False

    edge = match.get("edge")
    return edge is None or str(edge) == ev.edge


def actions_for_event(bindings: list[dict[str, Any]], ev: NormalizedEvent) -> list[dict[str, Any]]:
    """First matching binding wins; returns list of action dicts."""

    for b in bindings:
        match = b.get("match") or {}
        if not event_matches_rule(match, ev):
            continue
        if "actions" in b:
            acts = b["actions"]
            if isinstance(acts, list) and len(acts) > 0:
                logger.debug("Flat binding matched %s -> %s action(s)", match, len(acts))
                return list(acts)
            if acts is not None and not isinstance(acts, list):
                raise ValueError("bindings[].actions must be a list")
        if "action" in b:
            a = b["action"]
            if isinstance(a, dict):
                logger.debug("Flat binding matched %s -> single action", match)
                return [a]
            raise ValueError("bindings[].action must be a mapping")
        logger.debug("Flat binding matched %s but no actions", match)
        return []
    logger.debug("No flat binding for event kind=%s id=%s edge=%s", ev.kind, ev.id, ev.edge)
    return []
