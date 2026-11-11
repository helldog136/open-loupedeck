"""Starter packs: ready-made key layouts + knob roles offered on first launch (``packs/*.json``).

A pack is data only. Each entry of ``pages`` maps to the deck page of the same index and holds
``controls``: control id -> binding (``key_<col>_<row>`` with an action + look, ``knob_<n>`` with
a role, see ``docs/ui-redesign/knobs-model.md``), in the coordinates of the pack's ``grid``
(``[cols, rows]``, the Live S 5 x 3 by default). On another device a pack keeps the coordinates:
keys outside the device's grid and controls it does not have are dropped, with a note.
``text_key`` in an entry is a locale key turned into the plain ``text`` of the key when the pack is
listed (user text is never re-translated afterwards). The current UI applies a pack client-side
(one Undo step, only filling what is empty); :func:`apply_pack` is the same logic on a config.
"""

from __future__ import annotations

import json
import logging
from copy import deepcopy
from pathlib import Path
from typing import Any

from . import i18n
from .bindings import PAGE_CONTROLS_KEY, actions_of
from .control_ids import control_to_legacy_id
from .devices.model import DeviceModel, control_kind_from_id, parse_key_id
from .devices.registry import default_model
from .look_defaults import resolve_look
from .package_paths import package_root

logger = logging.getLogger(__name__)

DEFAULT_GRID = (5, 3)
"""Grid packs are designed for when they do not say (the Live S key grid)."""
PREVIEW_MAX = 8
ORDER = ("streamer", "music", "smart_home", "wow", "blank")


def packs_dir() -> Path:
    return package_root() / "packs"


def load_raw_packs() -> list[dict[str, Any]]:
    """Every pack file, parsed, in display order (unreadable files are skipped with a warning)."""

    out: dict[str, dict[str, Any]] = {}
    for path in sorted(packs_dir().glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.warning("Could not read starter pack %s", path, exc_info=True)
            continue
        if isinstance(data, dict) and data.get("id"):
            out[str(data["id"])] = data
    ids = [i for i in ORDER if i in out] + sorted(i for i in out if i not in ORDER)
    return [out[i] for i in ids]


def _resolve_entry(entry: dict[str, Any], lang: str) -> dict[str, Any]:
    e = deepcopy(entry)
    key = e.pop("text_key", None)
    if key:
        e["text"] = i18n.t(str(key), lang)
    return e


def _sort_key(cid: str) -> tuple[int, int, int, str]:
    kc = parse_key_id(cid)
    if kc is not None:
        return (0, kc[1], kc[0], cid)  # keys row by row
    return (1, 0, 0, cid)


def fit_page_to_model(controls: dict[str, Any], model: DeviceModel) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """``(kept controls, dropped notes)``: the pack page's controls that exist on ``model``.

    Keys keep their coordinates (``key_4_0`` is the top-right key of a 5-column grid, it has no
    place on a 4-column one). Each note is ``{"control_id", "reason"}``.
    """

    kept: dict[str, Any] = {}
    dropped: list[dict[str, str]] = []
    cols, rows = model.grid_of_keys()
    for cid in sorted(controls, key=_sort_key):
        if model.has_control(cid):
            kept[cid] = controls[cid]
            continue
        kc = parse_key_id(cid)
        if kc is not None:
            reason = f"{cid} is outside the {cols}x{rows} key grid of the {model.name}"
        else:
            reason = f"the {model.name} has no {cid}"
        dropped.append({"control_id": cid, "reason": reason})
    return kept, dropped


def fit_pack_to_model(pack: dict[str, Any], model: DeviceModel) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Pages of ``pack`` (``[{"controls": ...}]``) fitted to ``model`` + every dropped control."""

    pages: list[dict[str, Any]] = []
    notes: list[dict[str, str]] = []
    for pi, page in enumerate(pack.get("pages") or []):
        controls = page.get(PAGE_CONTROLS_KEY) if isinstance(page, dict) else None
        kept, dropped = fit_page_to_model(controls if isinstance(controls, dict) else {}, model)
        pages.append({PAGE_CONTROLS_KEY: kept})
        notes.extend({**n, "page": str(pi)} for n in dropped)
    if notes:
        logger.debug("Pack %s on %s: %s control(s) dropped", pack.get("id"), model.id, len(notes))
    return pages, notes


def _has_action(entry: Any) -> bool:
    if not isinstance(entry, dict):
        return False
    try:
        return bool(actions_of(entry))
    except ValueError:
        return False


def apply_pack(raw: dict[str, Any], pack: dict[str, Any], model: DeviceModel) -> list[dict[str, str]]:
    """Fill ``raw`` (``config_version: 2``, in place) from ``pack`` on ``model``; returns the notes.

    Only what is empty is filled: a key without an action, a knob without a role. Pack page ``i``
    goes to deck page ``i`` (pages the config does not have are skipped).
    """

    pages, notes = fit_pack_to_model(pack, model)
    deck = raw.get("pages")
    if not isinstance(deck, list):
        return notes
    for i, src in enumerate(pages):
        if i >= len(deck) or not isinstance(deck[i], dict):
            continue
        controls = deck[i].get(PAGE_CONTROLS_KEY)
        if not isinstance(controls, dict):
            controls = deck[i][PAGE_CONTROLS_KEY] = {}
        for cid, entry in src[PAGE_CONTROLS_KEY].items():
            current = controls.get(cid)
            empty = not current if control_kind_from_id(cid) == "knob" else not _has_action(current)
            if empty:
                controls[cid] = deepcopy(entry)
    raw["onboarding_pack"] = pack.get("id")
    return notes


def _preview(controls: dict[str, Any], lang: str) -> list[dict[str, str]]:
    """Label + colour of the first keys (row by row) of the first page (for the pack card)."""

    items = []
    for cid in sorted(controls, key=_sort_key):
        if control_kind_from_id(cid) != "key":
            continue
        look = resolve_look(controls[cid], lang)
        label = look["label"] or str(controls[cid].get("text") or "")
        if label:
            items.append({"label": label, "bg": look["bg"] or "", "fg": look["fg"] or ""})
    return items[:PREVIEW_MAX]


def _legacy_page(controls: dict[str, Any], model: DeviceModel) -> dict[str, Any]:
    """``keys`` (touch index -> entry) + ``knobs`` (legacy knob id -> role) for the current UI."""

    keys: dict[str, Any] = {}
    knobs: dict[str, Any] = {}
    for cid, entry in controls.items():
        lid = control_to_legacy_id(cid, model)
        if lid is None:
            continue
        if lid.startswith("touch_"):
            keys[lid[len("touch_") :]] = entry
        elif control_kind_from_id(cid) == "knob":
            knobs[lid] = entry
    return {"keys": keys, "knobs": knobs}


def list_packs(lang: str, model: DeviceModel | None = None) -> list[dict[str, Any]]:
    """Packs with translated name / description, controls fitted to ``model`` and a small preview.

    Each page has ``controls`` (control ids) and, for the current UI, the same as legacy ``keys``
    (touch index) + ``knobs``; ``dropped`` lists what does not fit ``model`` (Live S by default).
    """

    model = model or default_model()
    result = []
    for raw in load_raw_packs():
        resolved = {
            "pages": [
                {
                    PAGE_CONTROLS_KEY: {
                        str(cid): (_resolve_entry(e, lang) if isinstance(e, dict) else e)
                        for cid, e in ((page or {}).get(PAGE_CONTROLS_KEY) or {}).items()
                    }
                }
                for page in raw.get("pages") or []
            ]
        }
        pages, dropped = fit_pack_to_model(resolved, model)
        out_pages = [{**p, **_legacy_page(p[PAGE_CONTROLS_KEY], model)} for p in pages]
        result.append(
            {
                "id": raw["id"],
                "name": i18n.t(raw["name_key"], lang),
                "description": i18n.t(raw["description_key"], lang),
                "icon": raw.get("icon") or "",
                "services": list(raw.get("services") or []),
                "model": model.id,
                "pages": out_pages,
                "dropped": dropped,
                "preview": _preview(pages[0][PAGE_CONTROLS_KEY], lang) if pages else [],
            }
        )
    return result
