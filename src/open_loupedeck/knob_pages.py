"""Per-knob page stacks: rotate left/right actions; push cycles pages (no separate push binding)."""

from __future__ import annotations

from typing import Any

KNOB_ENCODER_IDS = frozenset({"knobTL", "knobCL", "knobBL", "knobTR", "knobCR", "knobBR"})

# Hard upper bound for on-screen page name after cycling (seconds).
KNOB_PAGE_FEEDBACK_MAX_SEC = 2.0


def knob_pages_root(raw: dict[str, Any]) -> dict[str, Any]:
    kp = raw.get("knob_pages")
    return kp if isinstance(kp, dict) else {}


def pages_list_for_knob(raw: dict[str, Any], knob_id: str) -> list[dict[str, Any]] | None:
    """Return knob page dicts, or ``None`` if this knob does not use the knob-pages system."""

    spec = knob_pages_root(raw).get(knob_id)
    if not isinstance(spec, dict):
        return None
    pages = spec.get("pages")
    if not isinstance(pages, list) or len(pages) == 0:
        return None
    return [p for p in pages if isinstance(p, dict)]


def knob_uses_page_layers(raw: dict[str, Any], knob_id: str) -> bool:
    return pages_list_for_knob(raw, knob_id) is not None


def knob_page_feedback_label(page: dict[str, Any]) -> str:
    """Human-readable label shown on the touch grid after cycling to this page."""

    return str(page.get("name") or page.get("page_change_message") or page.get("message") or "").strip()


def feedback_touch_key_for_knob_page_name(knob_id: str, model: str) -> str | None:
    """Touch cell that shows the knob page name when that encoder’s page is cycled."""

    m = (model or "auto").lower()
    if m == "live":
        col_top = {
            "knobTL": "touch_0",
            "knobCL": "touch_4",
            "knobBL": "touch_8",
            "knobTR": "touch_3",
            "knobCR": "touch_7",
            "knobBR": "touch_11",
        }
        return col_top.get(knob_id)
    # live_s (and auto default layout): top dial → touch_0, lower dial → touch_5
    return {"knobTL": "touch_0", "knobCL": "touch_5"}.get(knob_id)


def feedback_duration_sec(raw: dict[str, Any]) -> float:
    fb = raw.get("knob_page_feedback")
    if isinstance(fb, dict):
        d = fb.get("duration_sec") or fb.get("seconds")
        if d is not None:
            try:
                return max(0.3, min(KNOB_PAGE_FEEDBACK_MAX_SEC, float(d)))
            except (TypeError, ValueError):
                pass
    return KNOB_PAGE_FEEDBACK_MAX_SEC


def _actions_from_side_value(val: Any) -> list[dict[str, Any]]:
    if val is None:
        return []
    if isinstance(val, list):
        return [x for x in val if isinstance(x, dict) and x.get("type")]
    if isinstance(val, dict) and val.get("type"):
        return [val]
    return []


def actions_for_knob_rotation(
    raw: dict[str, Any],
    knob_id: str,
    edge_left_or_right: str,
    knob_page_indices: dict[str, int],
) -> list[dict[str, Any]] | None:
    """
    If ``knob_id`` has ``knob_pages``, return actions for the current page and edge.
    Return ``None`` if this knob is not configured for page layers (caller falls back to global/page UI).
    """

    pages = pages_list_for_knob(raw, knob_id)
    if pages is None:
        return None
    idx = knob_page_indices.get(knob_id, 0) % len(pages)
    page = pages[idx]
    if str(edge_left_or_right) == "left":
        val = page.get("rotate_left") or page.get("left")
    else:
        val = page.get("rotate_right") or page.get("right")
    acts = _actions_from_side_value(val)
    return acts


def cycle_knob_page_index(
    knob_page_indices: dict[str, int],
    knob_id: str,
    n_pages: int,
) -> int:
    cur = knob_page_indices.get(knob_id, 0)
    nxt = (cur + 1) % n_pages
    knob_page_indices[knob_id] = nxt
    return nxt


def walk_knob_pages_for_media(pages_root: dict[str, Any], visit_action: Any) -> None:
    """Call ``visit_action(action_dict)`` for each nested action in knob page configs."""

    if not isinstance(pages_root, dict):
        return
    for spec in pages_root.values():
        if not isinstance(spec, dict):
            continue
        pages = spec.get("pages")
        if not isinstance(pages, list):
            continue
        for pg in pages:
            if not isinstance(pg, dict):
                continue
            for side in ("rotate_left", "rotate_right", "left", "right"):
                val = pg.get(side)
                if isinstance(val, list):
                    for item in val:
                        if isinstance(item, dict) and item.get("type"):
                            visit_action(item)
                elif isinstance(val, dict) and val.get("type"):
                    visit_action(val)
