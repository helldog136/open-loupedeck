"""Config schema versions: legacy (no ``config_version``) -> ``config_version: 2``.

Legacy configs used Loupedeck ids (``touch_N``, ``knobTL``, ``btn_circle``, ``strip_left``),
per-page ``buttons`` (touch keys) + ``knobs`` (knob roles), a top-level ``global_buttons`` (round
buttons, strips) and hard-wired "the four Live S round buttons open pages 1..4". Version 2 uses
model control ids, one ``controls`` map per page, one ``global`` map and the resolution rule of
:mod:`open_loupedeck.bindings`; the page buttons are ordinary global bindings
``agent.goto_page`` created by default.

:func:`migrate_config` converts once, keyed on the grid of ``device.model`` (``auto`` -> Live S).
It is idempotent and never deletes anything: an entry that was inactive in the legacy runtime (a
touch key in ``global_buttons``, a page-level entry for a Live S page button, a key beyond the
grid...) keeps its legacy id, which no control has, so it stays inactive and is still there when
the config is used with another device. :func:`to_ui_view` is the exact inverse used by the web
UI until it speaks control ids (``migrate_config(to_ui_view(v2)) == v2``).
"""

from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any

from .bindings import GLOBAL_KEY, PAGE_CONTROLS_KEY, actions_of, global_bindings, page_bindings
from .control_ids import LEGACY_ALIASES, control_to_legacy_id, legacy_to_control_id
from .devices.model import DeviceModel, control_kind_from_id, is_control_id, parse_indexed_id
from .devices.registry import config_model, model_by_name

logger = logging.getLogger(__name__)

CONFIG_VERSION = 2
VERSION_KEY = "config_version"
UNMIGRATED_KEY = "legacy_unmigrated"
"""Where an entry goes when both its new id and its legacy id are taken (never expected)."""
UI_MODEL_KEY = "_ui_model"
"""Model a UI view was made for (so saving it converts back with the same grid)."""
UI_ACTION_KEYS = ("_v2_action", "_v2_actions")
"""In a UI view: the action of a page button that is not its default ``agent.goto_page``."""
UI_UNBOUND_KEY = "_v2_unbound"
"""In a UI view: page buttons that have no global binding (so saving does not create one)."""
UI_INACTIVE_KEY = "_v2_inactive"
"""In a UI view (top level and on each page): inactive entries under their old id, set aside so
the old UI neither shows nor re-interprets them (``touch_12`` means a key on another grid)."""


def config_version(raw: dict[str, Any]) -> int:
    v = raw.get(VERSION_KEY) if isinstance(raw, dict) else None
    if isinstance(v, bool):
        return 1
    try:
        return int(v) if v is not None else 1
    except (TypeError, ValueError):
        return 1


def needs_migration(raw: dict[str, Any]) -> bool:
    return config_version(raw) < CONFIG_VERSION


def page_button_ids(model: DeviceModel) -> list[str]:
    """Buttons that open pages 1, 2, 3... by default: the round buttons with an LED, in id order."""

    btns = [c for c in model.controls_of_kind("button") if c.has_led]
    return [c.id for c in sorted(btns, key=lambda c: (parse_indexed_id(c.id) or ("", 0))[1])]


def goto_page_action(index: int) -> dict[str, Any]:
    return {"type": "agent.goto_page", "index": int(index)}


def default_global_bindings(model: DeviceModel) -> dict[str, Any]:
    """Global bindings a new config starts with: page buttons open their page."""

    return {cid: {"action": goto_page_action(i)} for i, cid in enumerate(page_button_ids(model))}


def _has_actions(entry: Any) -> bool:
    if not isinstance(entry, dict):
        return False
    try:
        return bool(actions_of(entry))
    except ValueError:
        return False


def _with_key_replaced(d: dict[str, Any], old: str, new: str, value: Any) -> dict[str, Any]:
    """``d`` with ``old`` replaced by ``new`` = ``value`` at the same position (appended if absent)."""

    out: dict[str, Any] = {}
    placed = False
    for k, v in d.items():
        if k == old:
            out[new] = value
            placed = True
        elif k != new:
            out[k] = v
    if not placed:
        out[new] = value
    return out


class _Notes:
    def __init__(self) -> None:
        self.items: list[str] = []

    def add(self, msg: str) -> None:
        self.items.append(msg)


def _place(
    target: dict[str, Any],
    new_id: str,
    legacy_id: str,
    entry: Any,
    unmigrated: dict[str, Any],
    where: str,
    notes: _Notes,
) -> None:
    if new_id not in target:
        target[new_id] = entry
    elif legacy_id not in target:
        target[legacy_id] = entry
        notes.add(f"{where}.{legacy_id}: {new_id} already set; kept under its old id (inactive)")
    else:
        unmigrated.setdefault(where, {})[legacy_id] = entry
        notes.add(f"{where}.{legacy_id}: kept under {UNMIGRATED_KEY}")


def _ordered(items: dict[str, Any]) -> list[tuple[str, Any]]:
    """Control ids first (they win a clash), then legacy / unknown ids, each in file order."""

    pairs = [(str(k), v) for k, v in items.items()]
    return [p for p in pairs if is_control_id(p[0])] + [p for p in pairs if not is_control_id(p[0])]


def migrate_config(raw: dict[str, Any], model: DeviceModel | None = None) -> tuple[dict[str, Any], list[str]]:
    """Legacy config -> ``config_version: 2`` (a new dict). Returns ``(config, notes)``.

    A config already at version 2 is returned unchanged (a copy). ``model`` defaults to the model
    of ``device.model`` (``auto`` -> Live S).
    """

    if not isinstance(raw, dict):
        raise TypeError("Config root must be a mapping")
    if not needs_migration(raw):
        return deepcopy(raw), []
    out = deepcopy(raw)
    ui_model = out.pop(UI_MODEL_KEY, None)
    if model is None:
        model = model_by_name(str(ui_model)) if ui_model else None
    if model is None:
        dev = out.get("device") if isinstance(out.get("device"), dict) else {}
        model = config_model(str(dev.get("model") or "auto"))
    notes = _Notes()

    # Legacy per-knob page stacks -> legacy pages[].knobs first (converted below with the rest).
    from .knob_roles import migrate_legacy_knob_pages

    migrate_legacy_knob_pages(out)

    unmigrated: dict[str, Any] = deepcopy(out.get(UNMIGRATED_KEY)) if isinstance(out.get(UNMIGRATED_KEY), dict) else {}
    pbids = page_button_ids(model)

    # --- global_buttons -> global ---------------------------------------------------------------
    gb = out.get("global_buttons")
    gb = gb if isinstance(gb, dict) else {}
    glob: dict[str, Any] = dict(global_bindings(out))
    inactive_global = out.pop(UI_INACTIVE_KEY, None)
    unbound = out.pop(UI_UNBOUND_KEY, None)
    unbound = {str(u) for u in unbound} if isinstance(unbound, list) else set()
    explicit: set[str] = set()
    for lid, entry in _ordered(gb):
        e = deepcopy(entry)
        if isinstance(e, dict) and any(k in e for k in UI_ACTION_KEYS):
            for k in ("action", "actions"):
                e.pop(k, None)
            for ui_key, key in zip(UI_ACTION_KEYS, ("action", "actions"), strict=True):
                if ui_key in e:
                    v = e.pop(ui_key)
                    if v is not None:
                        e[key] = v
            explicit.add(lid)
        target = lid
        if not is_control_id(lid):
            canonical = LEGACY_ALIASES.get(lid, lid)
            if canonical != lid and canonical in gb:
                canonical = lid  # the alias is shadowed by the real id: stays inactive
            cid = legacy_to_control_id(canonical, model, aliases=False)
            # Legacy runtime: round buttons and strips used global_buttons; touch keys and knobs
            # never did (those entries were inactive).
            if cid is not None and control_kind_from_id(cid) in ("button", "strip"):
                target = cid
        if target != lid and lid in explicit:
            explicit.add(target)
        _place(glob, target, lid, e, unmigrated, "global_buttons", notes)
    for lid, entry in (inactive_global if isinstance(inactive_global, dict) else {}).items():
        _place(glob, str(lid), str(lid), deepcopy(entry), unmigrated, "global_buttons", notes)

    for idx, cid in enumerate(pbids):
        if cid in unbound and cid not in glob:
            continue
        e = glob.get(cid)
        e = dict(e) if isinstance(e, dict) else {}
        if cid not in explicit:
            for k in ("action", "actions"):
                if k not in e:
                    continue
                v = e.pop(k)
                if v not in (None, [], {}) and f"legacy_{k}" not in e:
                    e[f"legacy_{k}"] = v
                    notes.add(f"global.{cid}: its {k} never ran (page button); kept as legacy_{k}")
            e["action"] = goto_page_action(idx)
        c = e.get("button_color")
        if c is not None and str(c).strip() != "":
            e["button_color"] = str(c).strip()
        else:
            e.pop("button_color", None)
        glob[cid] = e

    global_actions = {cid for cid, e in glob.items() if _has_actions(e)}

    # --- pages[].buttons + pages[].knobs -> pages[].controls -------------------------------------
    pages = out.get("pages")
    if isinstance(pages, list):
        for pi, page in enumerate(pages):
            if not isinstance(page, dict):
                continue
            controls: dict[str, Any] = dict(page_bindings(page))
            where = f"pages[{pi}]"
            buttons = page.get("buttons")
            for lid, entry in _ordered(buttons if isinstance(buttons, dict) else {}):
                target = lid
                if not is_control_id(lid):
                    cid = legacy_to_control_id(lid, model, aliases=False)
                    kind = control_kind_from_id(cid) if cid else None
                    # Legacy runtime: touch keys came from the page; a round button's page entry
                    # only ran when no global entry had actions, and never for the Live S page
                    # buttons; strips and knobs never used page entries.
                    if kind == "key" or (kind == "button" and cid not in pbids and cid not in global_actions):
                        target = cid  # type: ignore[assignment]
                _place(controls, target, lid, deepcopy(entry), unmigrated, f"{where}.buttons", notes)
            knobs = page.get("knobs")
            for kid, role in _ordered(knobs if isinstance(knobs, dict) else {}):
                target = kid
                if not is_control_id(kid):
                    cid = legacy_to_control_id(kid, model, aliases=False)
                    if cid is not None and control_kind_from_id(cid) == "knob":
                        target = cid
                _place(controls, target, kid, deepcopy(role), unmigrated, f"{where}.knobs", notes)
            inactive = page.get(UI_INACTIVE_KEY)
            for lid, entry in (inactive if isinstance(inactive, dict) else {}).items():
                _place(controls, str(lid), str(lid), deepcopy(entry), unmigrated, f"{where}.buttons", notes)
            new_page = _with_key_replaced(page, "buttons", PAGE_CONTROLS_KEY, controls)
            new_page.pop("knobs", None)
            new_page.pop(UI_INACTIVE_KEY, None)
            pages[pi] = new_page

    if "global_buttons" in out or GLOBAL_KEY in out or "pages" not in out:
        out = _with_key_replaced(out, "global_buttons", GLOBAL_KEY, glob)
    else:  # readable YAML: global bindings right before the pages
        reordered: dict[str, Any] = {}
        for k, v in out.items():
            if k == "pages":
                reordered[GLOBAL_KEY] = glob
            reordered[k] = v
        out = reordered
    if unmigrated:
        out[UNMIGRATED_KEY] = unmigrated
    result = {VERSION_KEY: CONFIG_VERSION}
    result.update({k: v for k, v in out.items() if k != VERSION_KEY})
    if notes.items:
        for n in notes.items:
            logger.info("Config migration: %s", n)
    return result, notes.items


# --- UI compatibility view (legacy-shaped config for the current web UI) -----------------------


def to_ui_view(raw: dict[str, Any], model: DeviceModel | None = None) -> dict[str, Any]:
    """A version-2 config in the legacy shape the current web UI edits.

    Bindings that have an exact legacy equivalent get their legacy id; any other binding keeps its
    control id (the UI ignores it, saving gives it back unchanged). Saving the view goes through
    :func:`migrate_config` with the same model, which restores the version-2 config exactly.
    """

    if needs_migration(raw):
        raw, _ = migrate_config(raw, model)
    if model is None:
        dev = raw.get("device") if isinstance(raw.get("device"), dict) else {}
        model = config_model(str(dev.get("model") or "auto"))
    pbids = page_button_ids(model)
    glob = global_bindings(raw)

    gb: dict[str, Any] = {}
    inactive_global: dict[str, Any] = {}
    for cid, entry in glob.items():
        cid = str(cid)
        if not is_control_id(cid):
            inactive_global[cid] = deepcopy(entry)
            continue
        kind = control_kind_from_id(cid)
        lid = control_to_legacy_id(cid, model) if kind in ("button", "strip") else None
        if lid is None or not isinstance(entry, dict):
            gb[cid] = deepcopy(entry)
            continue
        e = deepcopy(entry)
        if cid in pbids:
            act, acts = e.pop("action", None), e.pop("actions", None)
            default = acts is None and act == goto_page_action(pbids.index(cid))
            if not default:
                if act is not None:
                    e["_v2_action"] = act
                if acts is not None:
                    e["_v2_actions"] = acts
                if act is None and acts is None:
                    e["_v2_action"] = None  # no action at all (not even the default)
        gb[lid] = e

    global_actions = {str(cid) for cid, e in glob.items() if _has_actions(e)}
    out: dict[str, Any] = {}
    for k, v in raw.items():
        if k == VERSION_KEY:
            continue
        if k == GLOBAL_KEY:
            out["global_buttons"] = gb
            continue
        if k == "pages" and isinstance(v, list):
            out["pages"] = [_page_view(p, model, pbids, global_actions) for p in v]
            continue
        out[k] = deepcopy(v)
    out.setdefault("global_buttons", gb)
    if inactive_global:
        out[UI_INACTIVE_KEY] = inactive_global
    unbound = [cid for cid in pbids if not isinstance(glob.get(cid), dict)]
    if unbound:
        out[UI_UNBOUND_KEY] = unbound
    out[UI_MODEL_KEY] = model.id
    return out


def _page_view(page: Any, model: DeviceModel, pbids: list[str], global_actions: set[str]) -> Any:
    if not isinstance(page, dict):
        return deepcopy(page)
    controls = page_bindings(page)
    buttons: dict[str, Any] = {}
    knobs: dict[str, Any] = {}
    inactive: dict[str, Any] = {}
    for cid, entry in controls.items():
        cid = str(cid)
        e = deepcopy(entry)
        kind = control_kind_from_id(cid)
        lid = control_to_legacy_id(cid, model) if kind else None
        if kind is None:
            inactive[cid] = e
        elif kind == "knob" and lid is not None:
            knobs[lid] = e
        elif lid is not None and (
            kind == "key" or (kind == "button" and cid not in pbids and cid not in global_actions)
        ):
            buttons[lid] = e
        else:
            buttons[cid] = e
    out = _with_key_replaced(page, PAGE_CONTROLS_KEY, "buttons", buttons)
    if knobs:
        out["knobs"] = knobs
    if inactive:
        out[UI_INACTIVE_KEY] = inactive
    return deepcopy(out)


def from_ui_view(view: dict[str, Any], model: DeviceModel | None = None) -> dict[str, Any]:
    """A config saved by the UI (legacy shape, or already version 2) -> version 2."""

    out, _ = migrate_config(view, model)
    return out
