"""Resolve the look (label, icon, colours, content mode) of a key from its config entry.

Principle ("smart defaults"): choosing an action gives the key a proposed look taken from
``action_catalog.DEFAULT_LOOKS``. Any visual field present in the entry is *modified* (it wins and
stops following the action); absent fields are *proposed*. No new storage format: the existing
``button_render`` keys are used -- ``text``/``label``, ``icon``/``image``, ``background`` (or the
``background_gradient_*`` keys) and ``text_color`` (or ``text_gradient_*``). The content ``mode`` has
no stored key yet: an optional ``mode`` key (text/icon/both) is honoured when present.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import PurePosixPath
from typing import Any

from . import i18n

MODES = ("text", "icon", "both")
FIELDS = ("label", "icon", "bg", "fg", "mode")

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_GRADIENT_BG = ("background_gradient_from", "background_gradient_to")
_GRADIENT_FG = ("text_gradient_from", "text_gradient_to")
# Placeholder shown by a live key (clock, OBS scene...) before its first value arrives.
LIVE_PLACEHOLDER = "—"

Translate = Callable[[str, "str | None"], str]


def default_translate(key: str, lang: str | None = None) -> str:
    """Translate a ``look.<type>.label`` key; ``lang`` may be a region tag (``fr-FR``) or unknown (-> English)."""

    code = i18n.resolve_language(lang) if lang else None
    return i18n.t(key, code)


def first_action(entry: dict[str, Any]) -> dict[str, Any] | None:
    a = entry.get("action")
    if isinstance(a, dict) and a.get("type"):
        return a
    acts = entry.get("actions")
    if isinstance(acts, list):
        for x in acts:
            if isinstance(x, dict) and x.get("type"):
                return x
    return None


def default_look_for(action_type: str) -> dict[str, Any] | None:
    from .action_catalog import DEFAULT_LOOKS

    return DEFAULT_LOOKS.get(action_type)


def _set(entry: dict[str, Any], *keys: str) -> bool:
    return any(str(entry.get(k) or "").strip() for k in keys)


def _param_label(param: str, value: Any) -> str:
    s = str(value or "").strip()
    if not s or s.startswith("{"):
        return ""
    if param in ("file", "path"):
        return PurePosixPath(s.replace("\\", "/").split("?", 1)[0]).stem
    if param == "entity_id":
        s = s.split(",")[0].strip().split(".", 1)[-1].replace("_", " ")
        return s[:1].upper() + s[1:]
    return s


def resolve_look(
    entry: dict[str, Any],
    lang: str | None = None,
    *,
    translate: Translate | None = None,
) -> dict[str, Any]:
    """Final look of a key: ``{label, icon, bg, fg, mode, source}``.

    ``source[field]`` is ``"modified"`` when the entry sets the field, else ``"proposed"``. Entries
    without a known action just get the entry's own values (empty/None for absent ones).
    """

    tr = translate or default_translate
    act = first_action(entry)
    dl = default_look_for(str(act["type"])) if act else None
    dl = dl or {}

    label_mod = _set(entry, "text", "label")
    icon_mod = _set(entry, "icon", "image")
    bg_mod = _set(entry, "background") or all(entry.get(k) for k in _GRADIENT_BG)
    fg_mod = _set(entry, "text_color") or all(entry.get(k) for k in _GRADIENT_FG)
    raw_mode = str(entry.get("mode") or "").strip().lower()
    mode_mod = raw_mode in MODES

    label = ""
    if label_mod:
        label = str(entry.get("text") or entry.get("label") or "").strip()
    elif dl:
        src = dl.get("label_from")
        if src and act:
            label = _param_label(str(src), act.get(src))
        if not label and dl.get("label_key"):
            label = tr(str(dl["label_key"]), lang)

    icon = str(entry.get("icon") or entry.get("image")).strip() if icon_mod else str(dl.get("icon") or "")

    out = {
        "label": label,
        "icon": icon,
        "bg": str(entry.get("background")) if _set(entry, "background") else str(dl.get("bg") or ""),
        "fg": str(entry.get("text_color")) if _set(entry, "text_color") else str(dl.get("fg") or ""),
        "mode": raw_mode if mode_mod else str(dl.get("mode") or ""),
    }
    out["source"] = {
        "label": "modified" if label_mod else "proposed",
        "icon": "modified" if icon_mod else "proposed",
        "bg": "modified" if bg_mod else "proposed",
        "fg": "modified" if fg_mod else "proposed",
        "mode": "modified" if mode_mod else "proposed",
    }
    if dl.get("live"):
        out["live"] = dict(dl["live"])
    return out


def _has_any_visual(entry: dict[str, Any]) -> bool:
    keys = ("text", "label", "icon", "image", "background", "text_color", *_GRADIENT_BG, *_GRADIENT_FG)
    return any(str(entry.get(k) or "").strip() for k in keys)


def proposed_entry(entry: dict[str, Any], lang: str | None = None) -> dict[str, Any] | None:
    """Entry with the proposed look written in the keys ``button_render`` understands, or ``None``.

    Applies only when the entry has an action with a default look and sets no visual field at all,
    so configs that already define visuals render exactly as before. Live display actions (clock,
    OBS scene...) whose text arrives at runtime but that set no colours get the proposed colours.
    """

    act = first_action(entry)
    if act is None:
        return None
    dl = default_look_for(str(act["type"]))
    if dl is None:
        return None
    live = dl.get("live")
    has_text = _set(entry, "text", "label")
    if live and has_text:
        if _set(entry, "background", "text_color", *_GRADIENT_BG, *_GRADIENT_FG, "icon", "image"):
            return None
        return {**entry, "background": dl["bg"], "text_color": dl["fg"]}
    if _has_any_visual(entry):
        return None
    look = resolve_look(entry, lang)
    out = dict(entry)
    if live:  # no value yet: offline look with a dash
        out.update(text=LIVE_PLACEHOLDER, background=live["offline_bg"], text_color=live["offline_fg"])
        return out
    out["background"], out["text_color"] = look["bg"], look["fg"]
    if look["mode"] in ("text", "both") and look["label"]:
        out["text"] = look["label"]
    if look["mode"] in ("icon", "both") and look["icon"]:
        out["icon"] = look["icon"]
    if look["mode"] == "both":
        out["graphic_text_layout"] = "split"
    return out
