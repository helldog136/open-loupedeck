"""UI metadata for action types (merged with live registry in /api/action_catalog)."""

from __future__ import annotations

from typing import Any

from . import i18n

# Structure only: no user-visible English lives here. Every text is a locale key derived from the
# type / field name (see ``label_key`` & co. below) and translated through ``i18n.t``:
#   action.<type>.label                                 category.<category>
#   action.<type>.help                                  (optional)
#   action.<type>.field.<name>.label | placeholder | help   (placeholder/help optional)
#   action.<type>.field.<name>.option.<value>           (select options; see ``option_has_key``)
#   look.<type>.label                                   (default key label, see DEFAULT_LOOKS)
# Each entry: type, category (a slug), fields. Field input types: text, number, select, json, asset (path +
# Browse uploads via /api/upload; optional "accept"), key_sequence. A purely numeric placeholder is stored
# here as-is (not translatable). Check completeness with ``python scripts/check_catalog_keys.py``.
ACTION_CATALOG: list[dict[str, Any]] = [
    {"type": "obs.set_scene", "category": "obs", "fields": [{"name": "scene", "input": "text"}]},
    {"type": "obs.scene_step", "category": "obs", "fields": [{"name": "step", "input": "number"}]},
    {"type": "obs.toggle_mute", "category": "obs", "fields": [{"name": "input_name", "input": "text"}]},
    {
        "type": "obs.input_volume_set",
        "category": "obs",
        "fields": [{"name": "input_name", "input": "text"}, {"name": "percent", "input": "number"}],
    },
    {
        "type": "obs.input_volume_delta",
        "category": "obs",
        "fields": [{"name": "input_name", "input": "text"}, {"name": "delta", "input": "number"}],
    },
    {
        "type": "ha.turn_on",
        "category": "home_assistant",
        "fields": [{"name": "entity_id", "input": "text"}, {"name": "data", "input": "json", "optional": True}],
    },
    {
        "type": "ha.turn_off",
        "category": "home_assistant",
        "fields": [{"name": "entity_id", "input": "text"}, {"name": "data", "input": "json", "optional": True}],
    },
    {
        "type": "ha.toggle",
        "category": "home_assistant",
        "fields": [{"name": "entity_id", "input": "text"}, {"name": "data", "input": "json", "optional": True}],
    },
    {"type": "ha.run_script", "category": "home_assistant", "fields": [{"name": "script", "input": "text"}]},
    {
        "type": "ha.call_service",
        "category": "home_assistant",
        "fields": [
            {"name": "domain", "input": "text"},
            {"name": "service", "input": "text"},
            {"name": "entity_id", "input": "text", "optional": True},
            {"name": "data", "input": "json", "optional": True},
        ],
    },
    {
        "type": "http.request",
        "category": "http",
        "fields": [
            {
                "name": "method",
                "input": "select",
                "options": ["GET", "POST", "PUT", "PATCH", "DELETE"],
                "default": "GET",
            },
            {"name": "url", "input": "text"},
            {"name": "headers", "input": "json", "optional": True},
            {"name": "json", "input": "json", "optional": True},
            {"name": "body", "input": "text", "optional": True},
            {"name": "timeout", "input": "number", "optional": True, "placeholder": "15"},
        ],
    },
    {
        "type": "overlay.show_media",
        "category": "obs_overlay",
        "fields": [
            {
                "name": "file",
                "input": "asset",
                "accept": (
                    "video/*,image/gif,image/webp,image/png,image/jpeg,.mp4,.webm,.mov,.gif,.webp,.png,.jpg,.jpeg"
                ),
            },
            {"name": "x", "input": "number", "optional": True},
            {"name": "y", "input": "number", "optional": True},
            {"name": "width", "input": "number", "optional": True},
            {"name": "duration_sec", "input": "number", "optional": True},
            {"name": "muted", "input": "select", "options": ["false", "true"], "default": "false", "optional": True},
        ],
    },
    {
        "type": "overlay.play_sound",
        "category": "obs_overlay",
        "fields": [
            {"name": "file", "input": "asset", "accept": "audio/*,.wav,.mp3,.ogg,.flac,.m4a,.opus,.aac"},
            {"name": "volume", "input": "number", "optional": True, "placeholder": "1"},
        ],
    },
    {"type": "overlay.clear", "category": "obs_overlay", "fields": []},
    {
        "type": "sound.play",
        "category": "sound",
        "fields": [
            {"name": "file", "input": "asset", "accept": "audio/*,.wav,.mp3,.ogg,.flac,.m4a,.opus,.aac"},
            {"name": "volume", "input": "number", "optional": True, "placeholder": "100"},
            {"name": "mode", "input": "select", "options": ["play", "toggle", "restart"], "default": "play"},
            {
                "name": "player",
                "input": "select",
                "options": ["auto", "afplay", "mpv", "paplay", "aplay", "ffplay"],
                "default": "auto",
            },
        ],
    },
    {"type": "sound.stop_all", "category": "sound", "fields": []},
    {
        "type": "sound.volume_set",
        "category": "sound",
        "fields": [{"name": "percent", "input": "number"}, {"name": "sink", "input": "text", "optional": True}],
    },
    {
        "type": "sound.volume_delta",
        "category": "sound",
        "fields": [{"name": "delta", "input": "number"}, {"name": "sink", "input": "text", "optional": True}],
    },
    {
        "type": "sound.mute_toggle",
        "category": "sound",
        "fields": [
            {"name": "mode", "input": "select", "options": ["toggle", "mute", "unmute"], "default": "toggle"},
            {"name": "sink", "input": "text", "optional": True},
        ],
    },
    {"type": "agent.next_page", "category": "deck", "fields": []},
    {"type": "agent.prev_page", "category": "deck", "fields": []},
    {
        "type": "agent.goto_page",
        "category": "deck",
        "fields": [
            {"name": "id", "input": "text", "optional": True},
            {"name": "name", "input": "text", "optional": True},
            {"name": "index", "input": "number", "optional": True, "placeholder": "0"},
        ],
    },
    {
        "type": "display.clock",
        "category": "display",
        "fields": [
            {"name": "time_format", "input": "text", "optional": True},
            {"name": "date_format", "input": "text", "optional": True},
            {"name": "timezone", "input": "text", "optional": True},
        ],
    },
    {
        "type": "display.twitch_live",
        "category": "display",
        "fields": [
            {"name": "login", "input": "text"},
            {"name": "template", "input": "text", "optional": True},
            {"name": "interval_seconds", "input": "number", "optional": True, "placeholder": "60"},
        ],
    },
    {
        "type": "display.obs_stream",
        "category": "display",
        "fields": [
            {"name": "template", "input": "text", "optional": True},
            {"name": "interval_seconds", "input": "number", "optional": True, "placeholder": "5"},
        ],
    },
    {
        "type": "display.obs_scene",
        "category": "display",
        "fields": [
            {"name": "template", "input": "text", "optional": True},
            {"name": "interval_seconds", "input": "number", "optional": True, "placeholder": "2"},
        ],
    },
    {
        "type": "display.battery",
        "category": "display",
        "fields": [
            {"name": "template", "input": "text", "optional": True},
            {"name": "interval_seconds", "input": "number", "optional": True, "placeholder": "30"},
        ],
    },
    {
        "type": "display.ha_sensor",
        "category": "display",
        "fields": [
            {"name": "entity_id", "input": "text"},
            {"name": "template", "input": "text", "optional": True},
            {"name": "interval_seconds", "input": "number", "optional": True, "placeholder": "30"},
        ],
    },
    {
        "type": "display.ha_weather",
        "category": "display",
        "fields": [
            {"name": "entity_id", "input": "text"},
            {"name": "template", "input": "text", "optional": True},
            {"name": "interval_seconds", "input": "number", "optional": True, "placeholder": "300"},
        ],
    },
    {
        "type": "display.live_message",
        "category": "display",
        "fields": [
            {"name": "template", "input": "text"},
            {"name": "url", "input": "text", "optional": True},
            {"name": "interval_seconds", "input": "number", "optional": True, "default": 60, "placeholder": "60"},
            {"name": "extract_mode", "input": "select", "options": ["text", "json", "regex"], "default": "text"},
            {"name": "json_path", "input": "text", "optional": True},
            {"name": "regex", "input": "text", "optional": True},
            {"name": "headers", "input": "json", "optional": True},
            {"name": "timeout", "input": "number", "optional": True, "default": 15},
        ],
    },
    {
        "type": "spotify.play_pause",
        "category": "spotify",
        "fields": [
            {"name": "device_id", "input": "text", "optional": True},
            {"name": "icon_playing", "input": "text", "optional": True},
            {"name": "icon_paused", "input": "text", "optional": True},
        ],
    },
    {
        "type": "spotify.next",
        "category": "spotify",
        "fields": [{"name": "device_id", "input": "text", "optional": True}],
    },
    {
        "type": "spotify.previous",
        "category": "spotify",
        "fields": [{"name": "device_id", "input": "text", "optional": True}],
    },
    {
        "type": "spotify.volume_set",
        "category": "spotify",
        "fields": [{"name": "percent", "input": "number"}, {"name": "device_id", "input": "text", "optional": True}],
    },
    {
        "type": "spotify.volume_delta",
        "category": "spotify",
        "fields": [{"name": "delta", "input": "number"}, {"name": "device_id", "input": "text", "optional": True}],
    },
    {
        "type": "spotify.play_playlist",
        "category": "spotify",
        "fields": [{"name": "playlist", "input": "text"}, {"name": "device_id", "input": "text", "optional": True}],
    },
    {
        "type": "twitch.create_clip",
        "category": "twitch",
        "fields": [
            {"name": "open", "input": "select", "options": ["false", "true"], "default": "false", "optional": True}
        ],
    },
    {
        "type": "twitch.start_commercial",
        "category": "twitch",
        "fields": [
            {"name": "length", "input": "select", "options": ["30", "60", "90", "120", "150", "180"], "default": "30"}
        ],
    },
    {"type": "twitch.snooze_ad", "category": "twitch", "fields": []},
    {
        "type": "twitch.create_marker",
        "category": "twitch",
        "fields": [{"name": "description", "input": "text", "optional": True}],
    },
    {
        "type": "twitch.update_channel",
        "category": "twitch",
        "fields": [
            {"name": "title", "input": "text", "optional": True},
            {"name": "game", "input": "text", "optional": True},
        ],
    },
    {
        "type": "twitch.chat_mode",
        "category": "twitch",
        "fields": [
            {
                "name": "setting",
                "input": "select",
                "options": ["slow", "followers", "subscribers", "emote", "unique"],
                "default": "slow",
            },
            {"name": "state", "input": "select", "options": ["toggle", "on", "off"], "default": "toggle"},
            {"name": "duration", "input": "number", "optional": True},
        ],
    },
    {
        "type": "twitch.announce",
        "category": "twitch",
        "fields": [
            {"name": "message", "input": "text"},
            {
                "name": "color",
                "input": "select",
                "options": ["primary", "blue", "green", "orange", "purple"],
                "default": "primary",
                "optional": True,
            },
        ],
    },
    {"type": "twitch.send_chat", "category": "twitch", "fields": [{"name": "message", "input": "text"}]},
    {"type": "twitch.clear_chat", "category": "twitch", "fields": []},
    {"type": "twitch.raid", "category": "twitch", "fields": [{"name": "channel", "input": "text"}]},
    {"type": "twitch.cancel_raid", "category": "twitch", "fields": []},
    {"type": "twitch.shoutout", "category": "twitch", "fields": [{"name": "channel", "input": "text"}]},
    {
        "type": "keyboard.play_sequence",
        "category": "keyboard",
        "fields": [
            {"name": "steps", "input": "key_sequence"},
            {"name": "delay_ms", "input": "number", "optional": True, "placeholder": "30"},
        ],
    },
    {
        "type": "command.run",
        "category": "shell",
        "fields": [
            {"name": "argv", "input": "json", "optional": True},
            {"name": "shell", "input": "text", "optional": True},
        ],
    },
]


# --- Proposed default looks -------------------------------------------------------------------
# Colour families (one per product area, so the deck reads at a glance):
#   OBS scenes / OBS overlay  blue     #1f6fe0 / #2b4a8f      OBS audio            violet  #33266f
#   Twitch (incl. display)    purple   #9146ff                 Spotify              green   #1a9a48
#   Sound (local + overlay)   amber    #e08a00                 Home Assistant       cyan    #0f8fb8
#   Deck / pages, HTTP, shell slate    #2a3345 / #3a3f4b       Display (live info)  indigo  #4a4f8f
# Text keys (white, big) are the default; transport controls are icon-only. ``live`` gives the
# offline look of keys whose text comes from a runtime source. Labels live in the locale files
# (``look.<type>.label``, stored here as ``label_key``).
_LIVE_OFFLINE = {"offline_bg": "#2b2f45", "offline_fg": "#9aa0bd"}
_OBS_SCENE, _OBS_AUDIO, _OBS_OVERLAY = "#1f6fe0", "#33266f", "#2b4a8f"
_TWITCH, _SPOTIFY, _SOUND, _HA = "#9146ff", "#1a9a48", "#e08a00", "#0f8fb8"
_SLATE, _SLATE2, _DISPLAY = "#2a3345", "#3a3f4b", "#4a4f8f"

# action type -> (icon, bg, mode, label_from or None, live offline colours or None)
_LOOK_SPECS: dict[str, tuple[str, str, str, str | None, dict[str, str] | None]] = {
    "obs.set_scene": ("lucide:clapperboard", _OBS_SCENE, "text", "scene", None),
    "obs.scene_step": ("lucide:clapperboard", _OBS_SCENE, "both", None, None),
    "obs.toggle_mute": ("lucide:mic-off", _OBS_AUDIO, "both", "input_name", None),
    "obs.input_volume_set": ("lucide:sliders-horizontal", _OBS_AUDIO, "both", "input_name", None),
    "obs.input_volume_delta": ("lucide:volume-2", _OBS_AUDIO, "both", "input_name", None),
    "ha.turn_on": ("lucide:lightbulb", _HA, "both", "entity_id", None),
    "ha.turn_off": ("lucide:lightbulb-off", _HA, "both", "entity_id", None),
    "ha.toggle": ("lucide:toggle-right", _HA, "both", "entity_id", None),
    "ha.run_script": ("lucide:scroll-text", _HA, "both", "script", None),
    "ha.call_service": ("lucide:settings-2", _HA, "both", None, None),
    "http.request": ("lucide:globe", _SLATE2, "text", None, None),
    "overlay.show_media": ("lucide:image", _OBS_OVERLAY, "both", "file", None),
    "overlay.play_sound": ("lucide:volume-2", _SOUND, "both", "file", None),
    "overlay.clear": ("lucide:eraser", _OBS_OVERLAY, "both", None, None),
    "sound.play": ("lucide:volume-2", _SOUND, "both", "file", None),
    "sound.stop_all": ("lucide:square", _SOUND, "icon", None, None),
    "sound.volume_set": ("lucide:sliders-horizontal", _SOUND, "icon", None, None),
    "sound.volume_delta": ("lucide:volume-1", _SOUND, "icon", None, None),
    "sound.mute_toggle": ("lucide:volume-x", _SOUND, "icon", None, None),
    "agent.next_page": ("lucide:chevron-right", _SLATE, "icon", None, None),
    "agent.prev_page": ("lucide:chevron-left", _SLATE, "icon", None, None),
    "agent.goto_page": ("lucide:layers", _SLATE, "text", "name", None),
    "display.clock": ("lucide:clock", _DISPLAY, "text", None, _LIVE_OFFLINE),
    "display.twitch_live": (
        "si:twitch",
        _TWITCH,
        "text",
        None,
        {"offline_bg": "#3a2a63", "offline_fg": "#b7a2e6"},
    ),
    "display.obs_stream": ("lucide:radio", _DISPLAY, "text", None, _LIVE_OFFLINE),
    "display.obs_scene": ("lucide:clapperboard", _DISPLAY, "text", None, _LIVE_OFFLINE),
    "display.battery": ("lucide:battery-medium", _DISPLAY, "text", None, _LIVE_OFFLINE),
    "display.ha_sensor": ("lucide:gauge", _DISPLAY, "text", None, _LIVE_OFFLINE),
    "display.ha_weather": ("lucide:cloud-sun", _DISPLAY, "text", None, _LIVE_OFFLINE),
    "display.live_message": ("lucide:message-square", _DISPLAY, "text", None, _LIVE_OFFLINE),
    "spotify.play_pause": ("lucide:play", _SPOTIFY, "icon", None, None),
    "spotify.next": ("lucide:skip-forward", _SPOTIFY, "icon", None, None),
    "spotify.previous": ("lucide:skip-back", _SPOTIFY, "icon", None, None),
    "spotify.volume_set": ("lucide:sliders-horizontal", _SPOTIFY, "icon", None, None),
    "spotify.volume_delta": ("lucide:volume-2", _SPOTIFY, "icon", None, None),
    "spotify.play_playlist": ("lucide:list-music", _SPOTIFY, "both", "playlist", None),
    "twitch.create_clip": ("lucide:scissors", _TWITCH, "text", None, None),
    "twitch.start_commercial": ("lucide:megaphone", _TWITCH, "text", None, None),
    "twitch.snooze_ad": ("lucide:alarm-clock-off", _TWITCH, "text", None, None),
    "twitch.create_marker": ("lucide:bookmark", _TWITCH, "text", None, None),
    "twitch.update_channel": ("lucide:pencil", _TWITCH, "text", "game", None),
    "twitch.chat_mode": ("lucide:message-circle", _TWITCH, "text", None, None),
    "twitch.announce": ("lucide:bell", _TWITCH, "text", None, None),
    "twitch.send_chat": ("lucide:message-square", _TWITCH, "text", None, None),
    "twitch.clear_chat": ("lucide:eraser", _TWITCH, "text", None, None),
    "twitch.raid": ("lucide:swords", _TWITCH, "text", None, None),
    "twitch.cancel_raid": ("lucide:circle-x", _TWITCH, "text", None, None),
    "twitch.shoutout": ("lucide:megaphone", _TWITCH, "text", None, None),
    "keyboard.play_sequence": ("lucide:keyboard", _SLATE2, "text", None, None),
    "command.run": ("lucide:terminal", _SLATE2, "text", None, None),
}


def _build_default_look(action: str, spec: tuple[Any, ...]) -> dict[str, Any]:
    icon, bg, mode, label_from, live = spec
    look: dict[str, Any] = {
        "icon": icon,
        "bg": bg,
        "fg": "#ffffff",
        "mode": mode,
        "label_key": f"look.{action}.label",
    }
    if label_from:
        look["label_from"] = label_from
    if live:
        look["live"] = dict(live)
    return look


DEFAULT_LOOKS: dict[str, dict[str, Any]] = {t: _build_default_look(t, s) for t, s in _LOOK_SPECS.items()}
for _entry in ACTION_CATALOG:
    if _entry["type"] in DEFAULT_LOOKS:
        _entry["default_look"] = DEFAULT_LOOKS[_entry["type"]]


# --- Locale keys ------------------------------------------------------------------------------
# Select options that are technical identifiers (HTTP verbs, player binaries, numbers) are shown as-is
# and have no locale key.
_RAW_OPTIONS = frozenset({"afplay", "mpv", "paplay", "aplay", "ffplay"})


def label_key(action: str) -> str:
    return f"action.{action}.label"


def help_key(action: str) -> str:
    return f"action.{action}.help"


def field_key(action: str, name: str, part: str) -> str:
    """``part`` is ``label``, ``placeholder`` or ``help``."""

    return f"action.{action}.field.{name}.{part}"


def option_key(action: str, name: str, value: str) -> str:
    return f"action.{action}.field.{name}.option.{value}"


def category_key(slug: str) -> str:
    return f"category.{slug}"


def option_has_key(value: Any) -> bool:
    """False for options shown verbatim (``GET``, ``30``, ``mpv``...)."""

    v = str(value)
    return not (v.isdigit() or v.isupper() or v in _RAW_OPTIONS)


def _text(key: str, lang: str, fallback: str = "") -> str:
    """Translated text for ``key`` (English when missing in ``lang``), else ``fallback``."""

    out = i18n.t(key, lang)
    return fallback if out == key else out


def _translated_field(action: str, field: dict[str, Any], lang: str) -> dict[str, Any]:
    name = str(field["name"])
    out = dict(field)
    out["label_key"] = field_key(action, name, "label")
    out["label"] = _text(out["label_key"], lang, name)
    for part in ("placeholder", "help"):
        key = field_key(action, name, part)
        text = _text(key, lang)
        if text:
            out[part], out[f"{part}_key"] = text, key
    options = field.get("options")
    if options:
        keys = {str(o): option_key(action, name, str(o)) for o in options if option_has_key(o)}
        out["option_label_keys"] = keys
        out["option_labels"] = {
            str(o): _text(keys[str(o)], lang, str(o)) if str(o) in keys else str(o) for o in options
        }
    return out


def merged_catalog(lang: str | None = None) -> list[dict[str, Any]]:
    """Registered kinds with translated labels/fields; unknown kinds get a params JSON editor.

    ``lang`` (a language code; default: the current app language) selects the locale. Every translated
    text comes with its ``*_key`` so clients can re-translate after a language change. Actions without
    locale keys (plugins) keep their raw type as label.
    """

    import open_loupedeck.actions  # noqa: F401 — register builtins + spotify

    from .actions.registry import registered_action_kinds

    code = i18n.resolve_language(lang) if lang else i18n.get_language()
    reg = registered_action_kinds()
    known = {c["type"]: c for c in ACTION_CATALOG}
    out: list[dict[str, Any]] = []
    for t in reg:
        lk = label_key(t)
        if t in known:
            base = known[t]
            slug = str(base.get("category") or "other")
            entry = {
                "type": base["type"],
                "category": _text(category_key(slug), code, slug),
                "category_key": category_key(slug),
                "label": _text(lk, code, t),
                "label_key": lk,
                "fields": [_translated_field(t, f, code) for f in base.get("fields") or []],
                "params_json": bool(base.get("params_json", False)),
                "default_look": base.get("default_look"),
            }
        else:
            # Plugin-registered kind with no catalog entry: bucket it by its type prefix (e.g.
            # "myplugin.foo" -> "Myplugin") so it still gets a sensible category in the UI.
            raw_prefix = t.split(".", 1)[0]
            prefix = raw_prefix.replace("_", " ")
            fallback = prefix[:1].upper() + prefix[1:] if prefix else "Other"
            entry = {
                "type": t,
                "category": _text(category_key(raw_prefix), code, fallback),
                "category_key": category_key(raw_prefix or "other"),
                "label": _text(lk, code, t),
                "label_key": lk,
                "fields": [],
                "params_json": True,
                "default_look": None,
            }
        help_text = _text(help_key(t), code)
        if help_text:
            entry["help"], entry["help_key"] = help_text, help_key(t)
        out.append(entry)
    out.sort(key=lambda e: (str(e.get("category") or "").lower(), str(e.get("label") or e["type"]).lower()))
    return out
