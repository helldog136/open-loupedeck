"""Resolve the look (label, icon, colours, content mode) of a key from its config entry.

Principle ("smart defaults"): choosing an action gives the key a proposed look taken from
``action_catalog.DEFAULT_LOOKS``. Any visual field present in the entry is *modified* (it wins and
stops following the action); absent fields are *proposed*. No new storage format: the existing
``button_render`` keys are used -- ``text``/``label``, ``icon``/``image``, ``background`` (or the
``background_gradient_*`` keys) and ``text_color`` (or ``text_gradient_*``). The content ``mode`` has
no stored key yet: an optional ``mode`` key (text/icon/both) is honoured when present.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from pathlib import PurePosixPath
from typing import Any

logger = logging.getLogger(__name__)

MODES = ("text", "icon", "both")
FIELDS = ("label", "icon", "bg", "fg", "mode")

DEFAULT_LABELS_EN: dict[str, str] = {
    "look.obs.set_scene.label": "Scene",
    "look.obs.toggle_mute.label": "Mute",
    "look.obs.input_volume_set.label": "Volume",
    "look.obs.input_volume_delta.label": "Volume",
    "look.ha.turn_on.label": "Turn on",
    "look.ha.turn_off.label": "Turn off",
    "look.ha.toggle.label": "Toggle",
    "look.ha.run_script.label": "Script",
    "look.ha.call_service.label": "Service",
    "look.http.request.label": "Request",
    "look.overlay.show_media.label": "Media",
    "look.overlay.play_sound.label": "Sound",
    "look.overlay.clear.label": "Clear",
    "look.sound.play.label": "Sound",
    "look.sound.volume_set.label": "Volume",
    "look.sound.volume_delta.label": "Volume",
    "look.sound.mute_toggle.label": "Mute",
    "look.agent.next_page.label": "Next",
    "look.agent.prev_page.label": "Back",
    "look.agent.goto_page.label": "Page",
    "look.display.clock.label": "Clock",
    "look.display.twitch_live.label": "Live",
    "look.display.obs_stream.label": "Stream",
    "look.display.obs_scene.label": "Scene",
    "look.display.battery.label": "Battery",
    "look.display.ha_sensor.label": "Sensor",
    "look.display.ha_weather.label": "Weather",
    "look.display.live_message.label": "Message",
    "look.spotify.play_pause.label": "Play",
    "look.spotify.next.label": "Next",
    "look.spotify.previous.label": "Previous",
    "look.spotify.volume_set.label": "Volume",
    "look.spotify.volume_delta.label": "Volume",
    "look.spotify.play_playlist.label": "Playlist",
    "look.twitch.create_clip.label": "Clip",
    "look.twitch.start_commercial.label": "Ad break",
    "look.twitch.snooze_ad.label": "Snooze ad",
    "look.twitch.create_marker.label": "Marker",
    "look.twitch.update_channel.label": "Channel",
    "look.twitch.chat_mode.label": "Chat mode",
    "look.twitch.announce.label": "Announce",
    "look.twitch.send_chat.label": "Chat",
    "look.twitch.clear_chat.label": "Clear chat",
    "look.twitch.raid.label": "Raid",
    "look.twitch.cancel_raid.label": "Cancel raid",
    "look.twitch.shoutout.label": "Shoutout",
    "look.keyboard.play_sequence.label": "Keys",
    "look.command.run.label": "Command",
}

DEFAULT_LABELS_FR: dict[str, str] = {
    "look.obs.set_scene.label": "Scène",
    "look.obs.toggle_mute.label": "Muet",
    "look.obs.input_volume_set.label": "Volume",
    "look.obs.input_volume_delta.label": "Volume",
    "look.ha.turn_on.label": "Allumer",
    "look.ha.turn_off.label": "Éteindre",
    "look.ha.toggle.label": "Basculer",
    "look.ha.run_script.label": "Script",
    "look.ha.call_service.label": "Service",
    "look.http.request.label": "Requête",
    "look.overlay.show_media.label": "Média",
    "look.overlay.play_sound.label": "Son",
    "look.overlay.clear.label": "Effacer",
    "look.sound.play.label": "Son",
    "look.sound.volume_set.label": "Volume",
    "look.sound.volume_delta.label": "Volume",
    "look.sound.mute_toggle.label": "Muet",
    "look.agent.next_page.label": "Suivant",
    "look.agent.prev_page.label": "Retour",
    "look.agent.goto_page.label": "Page",
    "look.display.clock.label": "Heure",
    "look.display.twitch_live.label": "Live",
    "look.display.obs_stream.label": "Stream",
    "look.display.obs_scene.label": "Scène",
    "look.display.battery.label": "Batterie",
    "look.display.ha_sensor.label": "Capteur",
    "look.display.ha_weather.label": "Météo",
    "look.display.live_message.label": "Message",
    "look.spotify.play_pause.label": "Lecture",
    "look.spotify.next.label": "Suivant",
    "look.spotify.previous.label": "Précédent",
    "look.spotify.volume_set.label": "Volume",
    "look.spotify.volume_delta.label": "Volume",
    "look.spotify.play_playlist.label": "Playlist",
    "look.twitch.create_clip.label": "Clip",
    "look.twitch.start_commercial.label": "Pub",
    "look.twitch.snooze_ad.label": "Reporter pub",
    "look.twitch.create_marker.label": "Repère",
    "look.twitch.update_channel.label": "Chaîne",
    "look.twitch.chat_mode.label": "Mode chat",
    "look.twitch.announce.label": "Annonce",
    "look.twitch.send_chat.label": "Chat",
    "look.twitch.clear_chat.label": "Vider chat",
    "look.twitch.raid.label": "Raid",
    "look.twitch.cancel_raid.label": "Annuler raid",
    "look.twitch.shoutout.label": "Dédicace",
    "look.keyboard.play_sequence.label": "Touches",
    "look.command.run.label": "Commande",
}

_TABLES = {"en": DEFAULT_LABELS_EN, "fr": DEFAULT_LABELS_FR}
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_GRADIENT_BG = ("background_gradient_from", "background_gradient_to")
_GRADIENT_FG = ("text_gradient_from", "text_gradient_to")
# Placeholder shown by a live key (clock, OBS scene...) before its first value arrives.
LIVE_PLACEHOLDER = "—"

Translate = Callable[[str, "str | None"], str]


def table_translate(key: str, lang: str | None = None) -> str:
    """Built-in fallback: ``lang`` table, then English, then the key itself."""

    code = (lang or "en").lower().split("-")[0].split("_")[0]
    return _TABLES.get(code, DEFAULT_LABELS_EN).get(key) or DEFAULT_LABELS_EN.get(key) or key


def default_translate(key: str, lang: str | None = None) -> str:
    """Use the app's i18n module when it provides a translation, else the built-in tables."""

    try:  # i18n is built by another package; stay importable without it.
        from . import i18n  # type: ignore[attr-defined]

        fn = getattr(i18n, "translate", None) or getattr(i18n, "t", None)
        if callable(fn):
            out = fn(key, lang)
            if isinstance(out, str) and out and out != key:
                return out
    except Exception:  # ImportError, or an i18n bug must not break key rendering
        logger.debug("i18n translate failed for %r", key, exc_info=True)
    return table_translate(key, lang)


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
