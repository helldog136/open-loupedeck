"""UI metadata for action types (merged with live registry in /api/action_catalog)."""

from __future__ import annotations

from typing import Any

# Each entry: type, label, optional fields (see static app.js), optional params_json for plugins.
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
            }
        out.append(entry)
    out.sort(key=lambda e: (str(e.get("category") or "").lower(), str(e.get("label") or e["type"]).lower()))
    return out
