"""Resolve the look (label, icon, colours, content mode) of a key from its config entry.

Principle ("smart defaults"): choosing an action gives the key a proposed look taken from
``action_catalog.DEFAULT_LOOKS``. Any visual field present in the entry is *modified* (it wins and
stops following the action); absent fields are *proposed*. No new storage format: the existing
``button_render`` keys are used -- ``text``/``label``, ``icon``/``image``, ``background`` (or the
``background_gradient_*`` keys) and ``text_color`` (or ``text_gradient_*``), plus the optional content
``mode`` key (text/icon/both).

The device renders exactly what :func:`resolve_look` reports: :func:`proposed_entry` fills every
untouched field from the proposed look (so customising only the background keeps the proposed label
and icon) and records the content mode in ``mode`` for ``button_render``. When no mode is stored and
the proposed one would hide content the user set explicitly (a custom icon on a text key, a custom
label on an icon key), the key shows both.
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


def effective_mode(stored: str, proposed: str, *, label_mod: bool, icon_mod: bool) -> str:
    """Content mode a key is shown in: the stored ``mode``, else the proposed one widened to ``both``
    when it would hide a label or icon the user set explicitly. ``""`` when there is neither."""

    s = str(stored or "").strip().lower()
    if s in MODES:
        return s
    p = str(proposed or "").strip().lower()
    if p not in MODES:
        return ""
    if (p == "text" and icon_mod) or (p == "icon" and label_mod):
        return "both"
    return p


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
    mode = effective_mode(raw_mode, str(dl.get("mode") or ""), label_mod=label_mod, icon_mod=icon_mod)

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
        "mode": mode,
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


def proposed_entry(entry: dict[str, Any], lang: str | None = None) -> dict[str, Any] | None:
    """Entry with its final look written in the keys ``button_render`` understands, or ``None``.

    For an action with a default look, every field the entry does not set is taken from the proposed
    look (see :func:`resolve_look`): colours, label (the live value for live keys -- a dash while there
    is none, drawn in the offline colours), icon, and the content ``mode`` (always written, so the
    renderer lays the key out as text / icon / both). Entries without a known action are returned
    as-is (``None``); a stored ``mode`` on them is still honoured by the renderer.
    """

    act = first_action(entry)
    if act is None:
        return None
    dl = default_look_for(str(act["type"]))
    if dl is None:
        return None
    look = resolve_look(entry, lang)
    src = look["source"]
    out = dict(entry)
    live = dl.get("live")
    if live:
        # The text of a live key comes from its source at runtime (or the preview); none yet -> dash.
        waiting = "text" not in entry and "label" not in entry
        if waiting:
            out["text"] = LIVE_PLACEHOLDER
        if src["bg"] == "proposed":
            out["background"] = live["offline_bg"] if waiting else look["bg"]
        if src["fg"] == "proposed":
            out["text_color"] = live["offline_fg"] if waiting else look["fg"]
    else:
        if src["bg"] == "proposed":
            out["background"] = look["bg"]
        if src["fg"] == "proposed":
            out["text_color"] = look["fg"]
        if src["label"] == "proposed" and look["label"]:
            out["text"] = look["label"]
    if src["icon"] == "proposed" and look["icon"] and look["mode"] in ("icon", "both"):
        out["icon"] = look["icon"]
    if look["mode"]:
        out["mode"] = look["mode"]
    return out
