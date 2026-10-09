"""Knob roles per deck page: what each encoder does depends on the deck page being shown.

Schema (on each entry of ``pages``)::

    knobs:
      knobTL:
        rotate: {duo: system_volume, params: {step: 5}}   # a linked "duo" (see knob_duos.py)
        press: {type: sound.mute_toggle}                  # optional, independent
        feedback_sec: 1.5                                 # optional, overrides knob_page_feedback
      knobCL:
        rotate:                                           # advanced: split left and right
          left: {type: agent.prev_page}                   # an action or a list of actions
          right: [{type: agent.next_page}]
        press: null

A knob without an entry (or a page without ``knobs``) does nothing. The legacy top-level
``knob_pages`` (per-knob page stacks, push cycles them) is migrated by
:func:`migrate_legacy_knob_pages`; see ``docs/ui-redesign/knobs-model.md``.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from .i18n import t
from .knob_duos import duo_feedback, expand_duo, get_duo, match_duo, missing_params, validate_duo_params
from .knob_pages import (
    KNOB_ENCODER_IDS,
    KNOB_PAGE_FEEDBACK_MAX_SEC,
    _actions_from_side_value,
    feedback_touch_key_for_knob_page_name,
    pages_list_for_knob,
)

LEGACY_KEY = "legacy_knob_pages"


def actions_list(val: Any) -> list[dict[str, Any]]:
    """An action, a list of actions or ``None`` -> list of action dicts (entries without type dropped)."""

    return _actions_from_side_value(val)


# --- schema validation ------------------------------------------------------------------------


def _validate_action_value(val: Any, where: str) -> list[str]:
    if val is None:
        return []
    items = val if isinstance(val, list) else [val]
    errors: list[str] = []
    for i, item in enumerate(items):
        w = f"{where}[{i}]" if isinstance(val, list) else where
        if not isinstance(item, dict):
            errors.append(f"{w} must be an action object")
        elif not isinstance(item.get("type"), str) or not item["type"].strip():
            errors.append(f"{w}.type must be a non-empty string")
    return errors


def validate_knob_entry(entry: Any, where: str) -> list[str]:
    if entry is None:
        return []
    if not isinstance(entry, dict):
        return [f"{where} must be an object"]
    errors: list[str] = []
    rot = entry.get("rotate")
    if rot is not None:
        if not isinstance(rot, dict):
            errors.append(f"{where}.rotate must be an object")
        elif "duo" in rot and ("left" in rot or "right" in rot):
            errors.append(f"{where}.rotate: use either duo or left/right, not both")
        elif "duo" in rot:
            duo = get_duo(rot.get("duo"))
            if duo is None:
                errors.append(f"{where}.rotate.duo: unknown duo {rot.get('duo')!r}")
            else:
                errors.extend(validate_duo_params(duo, rot.get("params"), f"{where}.rotate"))
        else:
            errors.extend(_validate_action_value(rot.get("left"), f"{where}.rotate.left"))
            errors.extend(_validate_action_value(rot.get("right"), f"{where}.rotate.right"))
    errors.extend(_validate_action_value(entry.get("press"), f"{where}.press"))
    fs = entry.get("feedback_sec")
    if fs is not None:
        try:
            ok = not isinstance(fs, bool) and 0 <= float(fs) <= KNOB_PAGE_FEEDBACK_MAX_SEC
        except (TypeError, ValueError):
            ok = False
        if not ok:
            errors.append(f"{where}.feedback_sec must be a number between 0 and {KNOB_PAGE_FEEDBACK_MAX_SEC:g}")
    return errors


def validate_knobs_config(raw: dict[str, Any]) -> list[str]:
    """Problems in every ``pages[].knobs`` (empty list = valid). Unknown extra keys are tolerated."""

    pages = raw.get("pages")
    if not isinstance(pages, list):
        return []
    errors: list[str] = []
    for pi, page in enumerate(pages):
        if not isinstance(page, dict) or page.get("knobs") is None:
            continue
        knobs = page["knobs"]
        where = f"pages[{pi}].knobs"
        if not isinstance(knobs, dict):
            errors.append(f"{where} must be an object")
            continue
        for kid, entry in knobs.items():
            if str(kid) not in KNOB_ENCODER_IDS:
                errors.append(f"{where}: unknown knob {kid!r} (expected one of {', '.join(sorted(KNOB_ENCODER_IDS))})")
                continue
            errors.extend(validate_knob_entry(entry, f"{where}.{kid}"))
    return errors


# --- migration from knob_pages ----------------------------------------------------------------


def role_from_legacy_knob_page(page: dict[str, Any]) -> dict[str, Any] | None:
    """Knob role equivalent to one legacy knob page (rotate only: the old push cycled pages)."""

    left = actions_list(page.get("rotate_left") or page.get("left"))
    right = actions_list(page.get("rotate_right") or page.get("right"))
    if not left and not right:
        return None
    hit = match_duo(left, right)
    if hit is not None:
        duo_id, params = hit
        rotate: dict[str, Any] = {"duo": duo_id}
        if params:
            rotate["params"] = params
        return {"rotate": rotate}
    return {"rotate": {"left": deepcopy(left), "right": deepcopy(right)}}


def migrate_legacy_knob_pages(raw: dict[str, Any]) -> bool:
    """Move legacy ``knob_pages`` into per-page ``knobs`` roles, in place. Returns True if changed.

    For each knob with legacy pages, the *first* knob page's rotation becomes that knob's role on
    every deck page that has no role for it yet (existing roles are never overwritten). The legacy
    data is kept verbatim under ``legacy_knob_pages`` (never overwritten either: a differing entry
    for the same knob is stored as ``<knob>_2``, ``<knob>_3``...) and ``knob_pages`` is removed.
    Idempotent. Without deck pages nothing is migrated (the legacy runtime path keeps working).
    """

    kp = raw.get("knob_pages")
    if not isinstance(kp, dict):
        if "knob_pages" not in raw:
            return False
        if kp is not None:  # malformed but kept: nothing is lost
            legacy = raw.get(LEGACY_KEY) if isinstance(raw.get(LEGACY_KEY), dict) else {}
            legacy.setdefault("_unparsed", deepcopy(kp))
            raw[LEGACY_KEY] = legacy
        raw.pop("knob_pages")
        return True
    pages = raw.get("pages")
    if not kp:
        raw.pop("knob_pages")
        return True
    if not isinstance(pages, list) or not any(isinstance(p, dict) for p in pages):
        return False

    legacy = raw.get(LEGACY_KEY)
    if not isinstance(legacy, dict):
        legacy = {}
    for kid, spec in kp.items():
        kid = str(kid)
        plist = pages_list_for_knob({"knob_pages": kp}, kid)
        if kid in KNOB_ENCODER_IDS and plist:
            role = role_from_legacy_knob_page(plist[0])
            if role is not None:
                for page in pages:
                    if not isinstance(page, dict):
                        continue
                    knobs = page.get("knobs")
                    if not isinstance(knobs, dict):
                        knobs = {}
                    if knobs.get(kid) is None:
                        knobs[kid] = deepcopy(role)
                    page["knobs"] = knobs
        # Keep the original data whatever it was (even malformed): nothing is lost.
        key, n = kid, 1
        while key in legacy and legacy[key] != spec:
            n += 1
            key = f"{kid}_{n}"
        legacy[key] = deepcopy(spec)
    raw[LEGACY_KEY] = legacy
    raw.pop("knob_pages")
    return True


# --- runtime resolution -----------------------------------------------------------------------


@dataclass
class KnobResolution:
    """What an encoder event does on the current deck page."""

    actions: list[dict[str, Any]] = field(default_factory=list)
    feedback: str = ""
    feedback_sec: float | None = None
    """Per-knob override of the feedback duration (``None`` = global ``knob_page_feedback``)."""


def knob_entry_for_page(raw: dict[str, Any], page_index: int, knob_id: str) -> dict[str, Any] | None:
    pages = raw.get("pages")
    if not isinstance(pages, list) or not pages:
        return None
    page = pages[int(page_index) % len(pages)]
    if not isinstance(page, dict):
        return None
    knobs = page.get("knobs")
    if not isinstance(knobs, dict):
        return None
    entry = knobs.get(knob_id)
    return entry if isinstance(entry, dict) else None


def _action_feedback(actions: list[dict[str, Any]], lang: str | None) -> str:
    """Short label for free actions: the action catalog's name ("Spotify — next track")."""

    if not actions:
        return ""
    kind = str(actions[0].get("type") or "")
    key = f"action.{kind}.label"
    label = t(key, lang)
    return kind if label == key else label


def _feedback_sec(entry: dict[str, Any]) -> float | None:
    v = entry.get("feedback_sec")
    if v is None or isinstance(v, bool):
        return None
    try:
        return max(0.0, min(KNOB_PAGE_FEEDBACK_MAX_SEC, float(v)))
    except (TypeError, ValueError):
        return None


def resolve_knob_event(
    raw: dict[str, Any],
    page_index: int,
    knob_id: str,
    event: str,
    lang: str | None = None,
) -> KnobResolution | None:
    """Actions + feedback for ``event`` (``left``, ``right`` or ``press``) on the current page.

    Returns ``None`` when the knob has no role on this page (the knob does nothing).
    """

    entry = knob_entry_for_page(raw, page_index, knob_id)
    if entry is None:
        return None
    fsec = _feedback_sec(entry)
    if event == "press":
        acts = actions_list(entry.get("press"))
        if not acts:
            return None
        return KnobResolution(deepcopy(acts), _action_feedback(acts, lang), fsec)
    if event not in ("left", "right"):
        return None
    rot = entry.get("rotate")
    if not isinstance(rot, dict):
        return None
    if "duo" in rot:
        duo = get_duo(rot.get("duo"))
        if duo is None:
            return None
        params = rot.get("params") if isinstance(rot.get("params"), dict) else {}
        if missing_params(duo, params):
            return KnobResolution([], t("knob.feedback.needs_setup", lang, name=t(duo.label_key, lang)), fsec)
        return KnobResolution(expand_duo(duo.id, params, event), duo_feedback(duo.id, params, event, lang), fsec)
    acts = actions_list(rot.get(event))
    if not acts:
        return None
    return KnobResolution(deepcopy(acts), _action_feedback(acts, lang), fsec)


def effective_model(configured: str, deck: Any = None) -> str:
    """``live`` / ``live_s`` from the config, or from the opened driver class when ``auto``."""

    m = (configured or "auto").lower()
    if m in ("live", "live_s") or deck is None:
        return m
    name = type(deck).__name__
    if name == "LoupedeckLiveS":
        return "live_s"
    if name == "LoupedeckLive":
        return "live"
    return m


def feedback_touch_key(knob_id: str, model: str) -> str | None:
    """The touch key next to ``knob_id`` on this device model (where its feedback is drawn)."""

    return feedback_touch_key_for_knob_page_name(knob_id, model)
