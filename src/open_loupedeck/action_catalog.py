"""UI metadata for action types (merged with live registry in /api/action_catalog)."""

from __future__ import annotations

from typing import Any

# Each entry: type, label, optional fields (see static/js/action-fields.js), optional params_json for plugins.
# Field input types: text, number, select, json, asset (path + Browse uploads via /api/upload; optional "accept").
ACTION_CATALOG: list[dict[str, Any]] = [
    {
        "type": "obs.set_scene",
        "category": "OBS",
        "label": "OBS — set program scene",
        "fields": [
            {
                "name": "scene",
                "label": "Scene name",
                "input": "text",
                "placeholder": "e.g. Starting Soon",
            },
        ],
    },
    {
        "type": "obs.toggle_mute",
        "category": "OBS",
        "label": "OBS — toggle input mute",
        "fields": [
            {
                "name": "input_name",
                "label": "Input name",
                "input": "text",
                "placeholder": "As in OBS audio mixer",
            },
        ],
    },
    {
        "type": "obs.input_volume_set",
        "category": "OBS",
        "label": "OBS — set source volume",
        "fields": [
            {
                "name": "input_name",
                "label": "Input name",
                "input": "text",
                "placeholder": "As in OBS audio mixer",
            },
            {
                "name": "percent",
                "label": "Volume (%)",
                "input": "number",
                "placeholder": "0–100",
            },
        ],
    },
    {
        "type": "obs.input_volume_delta",
        "category": "OBS",
        "label": "OBS — source volume up / down",
        "fields": [
            {
                "name": "input_name",
                "label": "Input name",
                "input": "text",
                "placeholder": "As in OBS audio mixer",
            },
            {
                "name": "delta",
                "label": "Change (percent points)",
                "input": "number",
                "placeholder": "e.g. 5 or -5",
            },
        ],
    },
    {
        "type": "ha.turn_on",
        "category": "Home Assistant",
        "label": "Home Assistant — turn on",
        "fields": [
            {
                "name": "entity_id",
                "label": "Entity ID",
                "input": "text",
                "placeholder": "e.g. light.living_room",
            },
            {
                "name": "data",
                "label": "Extra service data (JSON object)",
                "input": "json",
                "optional": True,
                "placeholder": '{"brightness_pct": 60, "rgb_color": [255, 120, 0]}',
            },
        ],
    },
    {
        "type": "ha.turn_off",
        "category": "Home Assistant",
        "label": "Home Assistant — turn off",
        "fields": [
            {
                "name": "entity_id",
                "label": "Entity ID",
                "input": "text",
                "placeholder": "e.g. light.living_room",
            },
            {
                "name": "data",
                "label": "Extra service data (JSON object)",
                "input": "json",
                "optional": True,
            },
        ],
    },
    {
        "type": "ha.toggle",
        "category": "Home Assistant",
        "label": "Home Assistant — toggle",
        "fields": [
            {
                "name": "entity_id",
                "label": "Entity ID",
                "input": "text",
                "placeholder": "e.g. switch.desk_lamp",
            },
            {
                "name": "data",
                "label": "Extra service data (JSON object)",
                "input": "json",
                "optional": True,
            },
        ],
    },
    {
        "type": "ha.run_script",
        "category": "Home Assistant",
        "label": "Home Assistant — run script",
        "fields": [
            {
                "name": "script",
                "label": "Script object id or entity id",
                "input": "text",
                "placeholder": "e.g. good_night or script.good_night",
            },
        ],
    },
    {
        "type": "ha.call_service",
        "category": "Home Assistant",
        "label": "Home Assistant — call service (advanced)",
        "fields": [
            {
                "name": "domain",
                "label": "Domain",
                "input": "text",
                "placeholder": "e.g. cover, climate, automation, scene",
            },
            {
                "name": "service",
                "label": "Service",
                "input": "text",
                "placeholder": "e.g. open_cover, set_temperature, trigger, turn_on",
            },
            {
                "name": "entity_id",
                "label": "Entity ID",
                "input": "text",
                "optional": True,
                "placeholder": "e.g. climate.bedroom",
            },
            {
                "name": "data",
                "label": "Extra service data (JSON object)",
                "input": "json",
                "optional": True,
                "placeholder": '{"temperature": 21}',
            },
        ],
    },
    {
        "type": "http.request",
        "category": "HTTP",
        "label": "HTTP request",
        "fields": [
            {
                "name": "method",
                "label": "Method",
                "input": "select",
                "options": ["GET", "POST", "PUT", "PATCH", "DELETE"],
                "default": "GET",
            },
            {"name": "url", "label": "URL", "input": "text", "placeholder": "https://…"},
            {
                "name": "headers",
                "label": "Headers (JSON object)",
                "input": "json",
                "optional": True,
                "placeholder": '{"Authorization": "Bearer …"}',
            },
            {
                "name": "json",
                "label": "JSON body",
                "input": "json",
                "optional": True,
                "placeholder": '{"key": "value"}',
            },
            {
                "name": "body",
                "label": "Raw body",
                "input": "text",
                "optional": True,
            },
            {
                "name": "timeout",
                "label": "Timeout (seconds)",
                "input": "number",
                "optional": True,
                "placeholder": "15",
            },
        ],
    },
    {
        "type": "overlay.show_media",
        "category": "OBS Overlay",
        "label": "OBS overlay — video or image (GIF)",
        "fields": [
            {
                "name": "file",
                "label": "Media file (under config)",
                "input": "asset",
                "accept": (
                    "video/*,image/gif,image/webp,image/png,image/jpeg,.mp4,.webm,.mov,.gif,.webp,.png,.jpg,.jpeg"
                ),
                "placeholder": "library/videos/… or library/images/…",
            },
            {
                "name": "x",
                "label": "Left (px)",
                "input": "number",
                "optional": True,
                "placeholder": "empty = centered horizontally",
            },
            {
                "name": "y",
                "label": "Top (px)",
                "input": "number",
                "optional": True,
                "placeholder": "empty = centered vertically",
            },
            {
                "name": "width",
                "label": "Width (px, height keeps aspect ratio)",
                "input": "number",
                "optional": True,
                "placeholder": "empty = maximize in overlay (contain)",
            },
            {
                "name": "duration_sec",
                "label": "Display time (seconds)",
                "input": "number",
                "optional": True,
                "placeholder": "empty = one video play or one GIF loop",
            },
            {
                "name": "muted",
                "label": "Mute video (no sound in OBS — use if autoplay fails)",
                "input": "select",
                "options": ["false", "true"],
                "default": "false",
                "optional": True,
            },
        ],
    },
    {
        "type": "overlay.play_sound",
        "category": "OBS Overlay",
        "label": "OBS overlay — play sound in browser",
        "fields": [
            {
                "name": "file",
                "label": "Audio file (under config)",
                "input": "asset",
                "accept": "audio/*,.wav,.mp3,.ogg,.flac,.m4a,.opus,.aac",
                "placeholder": "library/sounds/…",
            },
            {
                "name": "volume",
                "label": "Volume (0–1 or 0–100)",
                "input": "number",
                "optional": True,
                "placeholder": "1",
            },
        ],
    },
    {
        "type": "overlay.clear",
        "category": "OBS Overlay",
        "label": "OBS overlay — clear all media",
        "fields": [],
    },
    {
        "type": "sound.play",
        "category": "Sound",
        "label": "Play sound file",
        "fields": [
            {
                "name": "file",
                "label": "Sound file",
                "input": "asset",
                "accept": "audio/*,.wav,.mp3,.ogg,.flac,.m4a,.opus,.aac",
                "placeholder": "library/sounds/… or absolute path",
            },
            {
                "name": "player",
                "label": "Player",
                "input": "select",
                "options": ["auto", "afplay", "mpv", "paplay", "aplay", "ffplay"],
                "default": "auto",
            },
        ],
    },
    {
        "type": "sound.volume_set",
        "category": "Sound",
        "label": "System — set output volume",
        "fields": [
            {
                "name": "percent",
                "label": "Volume (%)",
                "input": "number",
                "placeholder": "0–120 (capped)",
            },
            {
                "name": "sink",
                "label": "Sink",
                "input": "text",
                "optional": True,
                "placeholder": "Linux only (pactl/wpctl); default sink if empty",
            },
        ],
    },
    {
        "type": "sound.volume_delta",
        "category": "Sound",
        "label": "System — volume up / down",
        "fields": [
            {
                "name": "delta",
                "label": "Change (percent points)",
                "input": "number",
                "placeholder": "e.g. 5 or -5",
            },
            {
                "name": "sink",
                "label": "Sink",
                "input": "text",
                "optional": True,
                "placeholder": "Leave empty for default output",
            },
        ],
    },
    {
        "type": "sound.mute_toggle",
        "category": "Sound",
        "label": "System — mute output",
        "fields": [
            {
                "name": "mode",
                "label": "Mode",
                "input": "select",
                "options": ["toggle", "mute", "unmute"],
                "default": "toggle",
            },
            {
                "name": "sink",
                "label": "Sink",
                "input": "text",
                "optional": True,
                "placeholder": "Leave empty for default output",
            },
        ],
    },
    {
        "type": "agent.next_page",
        "category": "Deck / Pages",
        "label": "Deck — next page",
        "fields": [],
    },
    {
        "type": "agent.prev_page",
        "category": "Deck / Pages",
        "label": "Deck — previous page",
        "fields": [],
    },
    {
        "type": "agent.goto_page",
        "category": "Deck / Pages",
        "label": "Deck — go to page",
        "fields": [
            {
                "name": "id",
                "label": "Page id",
                "input": "text",
                "optional": True,
                "placeholder": "Exact pages[].id (if you use ids in YAML)",
            },
            {
                "name": "name",
                "label": "Page name",
                "input": "text",
                "optional": True,
                "placeholder": "Exact name from YAML",
            },
            {
                "name": "index",
                "label": "Page index (0-based)",
                "input": "number",
                "optional": True,
                "placeholder": "0",
            },
        ],
    },
    {
        "type": "display.clock",
        "category": "Display",
        "label": "Display — clock (time + date, two lines; press does nothing)",
        "fields": [
            {
                "name": "time_format",
                "label": "Time line (strftime)",
                "input": "text",
                "optional": True,
                "placeholder": "%H:%M",
            },
            {
                "name": "date_format",
                "label": "Date line (strftime)",
                "input": "text",
                "optional": True,
                "placeholder": "%a %d %b",
            },
            {
                "name": "timezone",
                "label": "Timezone (e.g. UTC or Europe/London)",
                "input": "text",
                "optional": True,
                "placeholder": "empty = system local",
            },
        ],
    },
    {
        "type": "display.twitch_live",
        "category": "Display",
        "label": "Display — Twitch stream status (Helix; press does nothing)",
        "fields": [
            {
                "name": "login",
                "label": "Streamer login",
                "input": "text",
                "placeholder": "e.g. twitch",
            },
            {
                "name": "template",
                "label": "Template",
                "input": "text",
                "optional": True,
                "placeholder": "{twitch_status}\n{twitch_uptime} · {twitch_viewers} viewers",
            },
            {
                "name": "interval_seconds",
                "label": "Refresh interval (seconds)",
                "input": "number",
                "optional": True,
                "placeholder": "60",
            },
        ],
    },
    {
        "type": "display.obs_stream",
        "category": "Display",
        "label": "Display — OBS stream status (WebSocket; press does nothing)",
        "fields": [
            {
                "name": "template",
                "label": "Template",
                "input": "text",
                "optional": True,
                "placeholder": "{obs_status}\n{obs_duration} · {obs_timecode}",
            },
            {
                "name": "interval_seconds",
                "label": "Poll interval (seconds)",
                "input": "number",
                "optional": True,
                "placeholder": "5",
            },
        ],
    },
    {
        "type": "display.obs_scene",
        "category": "Display",
        "label": "Display — OBS current scene (WebSocket; press does nothing)",
        "fields": [
            {
                "name": "template",
                "label": "Template",
                "input": "text",
                "optional": True,
                "placeholder": "{obs_scene}",
            },
            {
                "name": "interval_seconds",
                "label": "Poll interval (seconds)",
                "input": "number",
                "optional": True,
                "placeholder": "2",
            },
        ],
    },
    {
        "type": "display.battery",
        "category": "Display",
        "label": "Display — computer battery (press does nothing)",
        "fields": [
            {
                "name": "template",
                "label": "Template",
                "input": "text",
                "optional": True,
                "placeholder": "{battery_percent}\n{battery_status} · {battery_ac}",
            },
            {
                "name": "interval_seconds",
                "label": "Refresh interval (seconds)",
                "input": "number",
                "optional": True,
                "placeholder": "30",
            },
        ],
    },
    {
        "type": "display.ha_sensor",
        "category": "Display",
        "label": "Display — Home Assistant entity state (press does nothing)",
        "fields": [
            {
                "name": "entity_id",
                "label": "Entity ID",
                "input": "text",
                "placeholder": "e.g. sensor.living_room_temperature",
            },
            {
                "name": "template",
                "label": "Template",
                "input": "text",
                "optional": True,
                "placeholder": "{state}{unit}",
            },
            {
                "name": "interval_seconds",
                "label": "Poll interval (seconds)",
                "input": "number",
                "optional": True,
                "placeholder": "30",
            },
        ],
    },
    {
        "type": "display.ha_weather",
        "category": "Display",
        "label": "Display — Home Assistant weather (press does nothing)",
        "fields": [
            {
                "name": "entity_id",
                "label": "Weather entity ID",
                "input": "text",
                "placeholder": "e.g. weather.home",
            },
            {
                "name": "template",
                "label": "Template",
                "input": "text",
                "optional": True,
                "placeholder": "{condition}\n{temperature}{temperature_unit}",
            },
            {
                "name": "interval_seconds",
                "label": "Poll interval (seconds)",
                "input": "number",
                "optional": True,
                "placeholder": "300",
            },
        ],
    },
    {
        "type": "display.live_message",
        "category": "Display",
        "label": "Display — live text (HTTP / page info; press does nothing)",
        "fields": [
            {
                "name": "template",
                "label": "Template",
                "input": "text",
                "placeholder": "e.g. {http} viewers  |  {page_name} ({page_number}/{page_count})",
            },
            {
                "name": "url",
                "label": "HTTP URL",
                "input": "text",
                "optional": True,
                "placeholder": "https://… (GET; value goes into {http} and {value})",
            },
            {
                "name": "interval_seconds",
                "label": "HTTP refresh interval (seconds)",
                "input": "number",
                "optional": True,
                "default": 60,
                "placeholder": "60",
            },
            {
                "name": "extract_mode",
                "label": "How to read HTTP body",
                "input": "select",
                "options": ["text", "json", "regex"],
                "default": "text",
            },
            {
                "name": "json_path",
                "label": "JSON path (dot segments, for json mode)",
                "input": "text",
                "optional": True,
                "placeholder": "e.g. data.viewer_count",
            },
            {
                "name": "regex",
                "label": "Regex (first capture group, for regex mode)",
                "input": "text",
                "optional": True,
            },
            {
                "name": "headers",
                "label": "HTTP headers (JSON object)",
                "input": "json",
                "optional": True,
            },
            {
                "name": "timeout",
                "label": "HTTP timeout (seconds)",
                "input": "number",
                "optional": True,
                "default": 15,
            },
        ],
    },
    {
        "type": "spotify.play_pause",
        "category": "Spotify",
        "label": "Spotify — play / pause",
        "fields": [
            {
                "name": "device_id",
                "label": "Device ID",
                "input": "text",
                "optional": True,
                "placeholder": "Active Connect device if empty",
            },
            {
                "name": "icon_playing",
                "label": "Icon while playing",
                "input": "text",
                "optional": True,
                "placeholder": "lucide:pause (default)",
            },
            {
                "name": "icon_paused",
                "label": "Icon while paused",
                "input": "text",
                "optional": True,
                "placeholder": "lucide:play (default)",
            },
        ],
    },
    {
        "type": "spotify.next",
        "category": "Spotify",
        "label": "Spotify — next track",
        "fields": [
            {
                "name": "device_id",
                "label": "Device ID",
                "input": "text",
                "optional": True,
                "placeholder": "Active Connect device if empty",
            },
        ],
    },
    {
        "type": "spotify.previous",
        "category": "Spotify",
        "label": "Spotify — previous track",
        "fields": [
            {
                "name": "device_id",
                "label": "Device ID",
                "input": "text",
                "optional": True,
                "placeholder": "Active Connect device if empty",
            },
        ],
    },
    {
        "type": "spotify.volume_set",
        "category": "Spotify",
        "label": "Spotify — set playback volume (%)",
        "fields": [
            {
                "name": "percent",
                "label": "Volume (0–100)",
                "input": "number",
                "placeholder": "e.g. 50",
            },
            {
                "name": "device_id",
                "label": "Device ID",
                "input": "text",
                "optional": True,
                "placeholder": "Active Connect device if empty",
            },
        ],
    },
    {
        "type": "spotify.volume_delta",
        "category": "Spotify",
        "label": "Spotify — volume up / down",
        "fields": [
            {
                "name": "delta",
                "label": "Change",
                "input": "number",
                "placeholder": "e.g. 5 or -5",
            },
            {
                "name": "device_id",
                "label": "Device ID",
                "input": "text",
                "optional": True,
                "placeholder": "Active Connect device if empty",
            },
        ],
    },
    {
        "type": "spotify.play_playlist",
        "category": "Spotify",
        "label": "Spotify — play playlist",
        "fields": [
            {
                "name": "playlist",
                "label": "Playlist",
                "input": "text",
                "placeholder": "URI, open.spotify.com link, or 22-char id",
            },
            {
                "name": "device_id",
                "label": "Device ID",
                "input": "text",
                "optional": True,
                "placeholder": "Active Connect device if empty",
            },
        ],
    },
    {
        "type": "twitch.create_clip",
        "category": "Twitch",
        "label": "Twitch — create clip",
        "fields": [
            {
                "name": "open",
                "label": "Open the clip editor afterwards",
                "input": "select",
                "options": ["false", "true"],
                "default": "false",
                "optional": True,
            }
        ],
    },
    {
        "type": "twitch.start_commercial",
        "category": "Twitch",
        "label": "Twitch — run ads",
        "fields": [
            {
                "name": "length",
                "label": "Ad length (seconds)",
                "input": "select",
                "options": ["30", "60", "90", "120", "150", "180"],
                "default": "30",
            }
        ],
    },
    {
        "type": "twitch.snooze_ad",
        "category": "Twitch",
        "label": "Twitch — snooze next ad (+5 min)",
        "fields": [],
    },
    {
        "type": "twitch.create_marker",
        "category": "Twitch",
        "label": "Twitch — add stream marker",
        "fields": [
            {
                "name": "description",
                "label": "Description",
                "input": "text",
                "optional": True,
                "placeholder": "Shown in the VOD timeline",
            }
        ],
    },
    {
        "type": "twitch.update_channel",
        "category": "Twitch",
        "label": "Twitch — set title / category",
        "fields": [
            {"name": "title", "label": "Stream title", "input": "text", "optional": True},
            {
                "name": "game",
                "label": "Category (exact name)",
                "input": "text",
                "optional": True,
                "placeholder": "e.g. Just Chatting",
            },
        ],
    },
    {
        "type": "twitch.chat_mode",
        "category": "Twitch",
        "label": "Twitch — chat mode (slow, followers, subs, emotes)",
        "fields": [
            {
                "name": "setting",
                "label": "Mode",
                "input": "select",
                "options": ["slow", "followers", "subscribers", "emote", "unique"],
                "default": "slow",
            },
            {
                "name": "state",
                "label": "State",
                "input": "select",
                "options": ["toggle", "on", "off"],
                "default": "toggle",
            },
            {
                "name": "duration",
                "label": "Slow: seconds (3-120) / Followers: minutes",
                "input": "number",
                "optional": True,
                "placeholder": "slow 30 / followers 0",
            },
        ],
    },
    {
        "type": "twitch.announce",
        "category": "Twitch",
        "label": "Twitch — chat announcement",
        "fields": [
            {"name": "message", "label": "Message", "input": "text"},
            {
                "name": "color",
                "label": "Color",
                "input": "select",
                "options": ["primary", "blue", "green", "orange", "purple"],
                "default": "primary",
                "optional": True,
            },
        ],
    },
    {
        "type": "twitch.send_chat",
        "category": "Twitch",
        "label": "Twitch — send chat message",
        "fields": [{"name": "message", "label": "Message", "input": "text"}],
    },
    {
        "type": "twitch.clear_chat",
        "category": "Twitch",
        "label": "Twitch — clear chat",
        "fields": [],
    },
    {
        "type": "twitch.raid",
        "category": "Twitch",
        "label": "Twitch — start raid",
        "fields": [{"name": "channel", "label": "Channel to raid", "input": "text", "placeholder": "login name"}],
    },
    {
        "type": "twitch.cancel_raid",
        "category": "Twitch",
        "label": "Twitch — cancel raid",
        "fields": [],
    },
    {
        "type": "twitch.shoutout",
        "category": "Twitch",
        "label": "Twitch — shoutout",
        "fields": [{"name": "channel", "label": "Channel to shout out", "input": "text", "placeholder": "login name"}],
    },
    {
        "type": "keyboard.play_sequence",
        "category": "Keyboard",
        "label": "Keyboard — play recorded key sequence",
        "fields": [
            {
                "name": "steps",
                "label": "Key sequence",
                "input": "key_sequence",
                "placeholder": "Click Record, then press keys in this window, in order",
            },
            {
                "name": "delay_ms",
                "label": "Delay between steps (ms)",
                "input": "number",
                "optional": True,
                "placeholder": "30",
            },
        ],
    },
    {
        "type": "command.run",
        "category": "Shell",
        "label": "Run shell command",
        "fields": [
            {
                "name": "argv",
                "label": "Argv (JSON array)",
                "input": "json",
                "optional": True,
                "placeholder": '["notify-send", "Loupedeck", "Hello"]',
            },
            {
                "name": "shell",
                "label": "Shell command (alternative to argv)",
                "input": "text",
                "optional": True,
                "placeholder": "Only if not using argv",
            },
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
# offline look of keys whose text comes from a runtime source. Labels live in
# ``look_defaults.DEFAULT_LABELS_*`` under ``label_key``.
_LIVE_OFFLINE = {"offline_bg": "#2b2f45", "offline_fg": "#9aa0bd"}
_OBS_SCENE, _OBS_AUDIO, _OBS_OVERLAY = "#1f6fe0", "#33266f", "#2b4a8f"
_TWITCH, _SPOTIFY, _SOUND, _HA = "#9146ff", "#1a9a48", "#e08a00", "#0f8fb8"
_SLATE, _SLATE2, _DISPLAY = "#2a3345", "#3a3f4b", "#4a4f8f"

# action type -> (icon, bg, mode, label_from or None, live offline colours or None)
_LOOK_SPECS: dict[str, tuple[str, str, str, str | None, dict[str, str] | None]] = {
    "obs.set_scene": ("lucide:clapperboard", _OBS_SCENE, "text", "scene", None),
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


def merged_catalog() -> list[dict[str, Any]]:
    """Registered kinds with labels/fields; unknown kinds get params JSON editor."""

    import open_loupedeck.actions  # noqa: F401 — register builtins + spotify

    from .actions.registry import registered_action_kinds

    reg = registered_action_kinds()
    known = {c["type"]: c for c in ACTION_CATALOG}
    out: list[dict[str, Any]] = []
    for t in reg:
        if t in known:
            base = known[t]
            entry = {
                "type": base["type"],
                "category": base.get("category") or "Other",
                "label": base["label"],
                "fields": list(base.get("fields") or []),
                "params_json": bool(base.get("params_json", False)),
                "default_look": base.get("default_look"),
            }
        else:
            # Plugin-registered kind with no catalog entry: bucket it by its type prefix (e.g.
            # "myplugin.foo" -> "Myplugin") so it still gets a sensible category in the UI.
            prefix = t.split(".", 1)[0].replace("_", " ")
            entry = {
                "type": t,
                "category": prefix[:1].upper() + prefix[1:] if prefix else "Other",
                "label": t,
                "fields": [],
                "params_json": True,
                "default_look": None,
            }
        out.append(entry)
    out.sort(key=lambda e: (str(e.get("category") or "").lower(), str(e.get("label") or e["type"]).lower()))
    return out
