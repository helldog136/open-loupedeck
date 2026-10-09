"""Starter packs: ready-made key layouts + knob roles offered on first launch (``packs/*.json``).

A pack is data only. Each entry of ``pages`` maps to the deck page of the same index and holds
``keys`` (touch key index -> config entry, using existing action types and look keys) and ``knobs``
(knob id -> role, see ``docs/ui-redesign/knobs-model.md``). ``text_key`` in an entry is a locale key
turned into the plain ``text`` of the key when the pack is listed (user text is never re-translated
afterwards). The UI applies a pack client-side (one Undo step) and only fills what is empty.
"""

from __future__ import annotations

import json
import logging
from copy import deepcopy
from pathlib import Path
from typing import Any

from . import i18n
from .look_defaults import resolve_look
from .package_paths import package_root

logger = logging.getLogger(__name__)

# Live S touch grid; the original Live (4x3) only uses the first 12 indices (the UI skips the others).
KEY_COUNT = 15
PREVIEW_MAX = 8
ORDER = ("streamer", "music", "smart_home", "blank")


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


def _preview(pages: list[dict[str, Any]], lang: str) -> list[dict[str, str]]:
    """Label + colour of the first keys of the first page (for the pack card)."""

    if not pages:
        return []
    keys = pages[0].get("keys") or {}
    items = []
    for idx in sorted(keys, key=int):
        look = resolve_look(keys[idx], lang)
        label = look["label"] or str(keys[idx].get("text") or "")
        if label:
            items.append({"label": label, "bg": look["bg"] or "", "fg": look["fg"] or ""})
    return items[:PREVIEW_MAX]


def list_packs(lang: str) -> list[dict[str, Any]]:
    """Packs with translated name / description, resolved keys and a small preview."""

    result = []
    for raw in load_raw_packs():
        pages = []
        for page in raw.get("pages") or []:
            pages.append(
                {
                    "keys": {str(i): _resolve_entry(e, lang) for i, e in (page.get("keys") or {}).items()},
                    "knobs": deepcopy(page.get("knobs") or {}),
                }
            )
        result.append(
            {
                "id": raw["id"],
                "name": i18n.t(raw["name_key"], lang),
                "description": i18n.t(raw["description_key"], lang),
                "icon": raw.get("icon") or "",
                "services": list(raw.get("services") or []),
                "pages": pages,
                "preview": _preview(pages, lang),
            }
        )
    return result
