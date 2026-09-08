# Configuration guide

The config window (see the [README](../README.md)) covers everything below and validates as you go — this document is for scripting a config directly, writing a plugin, or understanding exactly how dispatch works. The authoritative schema is whatever the agent loads (`config_io.py`, `ensure_minimal_structure`); when in doubt, use the config window and inspect the saved YAML.

---

## Config file location

- **Windows:** `%APPDATA%\open-loupedeck\config.yaml`
- **macOS:** `~/Library/Application Support/open-loupedeck/config.yaml`
- **Linux:** `~/.config/open-loupedeck/config.yaml` (or `$XDG_CONFIG_HOME/open-loupedeck/config.yaml`)

Pass a different path with `open-loupedeck --config /path/to/config.yaml`.

## Directory layout next to `config.yaml`

| Path | Purpose |
|---|---|
| `library/images/`, `library/videos/`, `library/sounds/`, `library/fonts/` | Uploaded/materialized media — external paths get copied in here on save so the config stays portable. |
| `open-loupedeck-backups/` | Rotating `.bak1`–`.bak3` snapshots (see [Backups](#backups)). |
| `spotify_tokens.json` | Spotify OAuth tokens. |

## Minimal working example

```yaml
logging:
  level: INFO
  file: true
  console: true

obs:
  host: 127.0.0.1
  port: 4455
  password: "your-obs-websocket-password"

device:
  path: ""
  model: auto

pages:
  - name: Main
    buttons:
      touch_0:
        text: BRB
        background: "#222238"
        text_color: "#ffffff"
        action:
          type: obs.set_scene
          scene: "Starting Soon"

global_buttons: {}
knob_pages: {}
bindings: []
plugin_modules: []
```

---

## Dispatch order (how an input picks actions)

1. **Knob rotation** — if `knob_pages` defines a page stack for that encoder, `rotate_left` / `rotate_right` runs and no `pages` / `bindings` lookup happens for that rotation.
2. **Knob push** — cycles the virtual knob page (and may flash its name on a touch key); tied to `knob_pages` + `knob_page_feedback`.
3. **Loupedeck Live S physical keys** — a short press on `btn_circle`, `btn_1`, `btn_2`, `btn_3` switches the deck page **index** (0–3 only) and redraws the skin. This path does **not** run `pages[].buttons` actions for those keys — the hardware is reserved for page switching, and only the first four pages are reachable this way (the config window's page rail marks them ①–④).
4. **Otherwise** — `actions_for_page_event`: for `touch_*`, only the current page's `buttons` map is used; for non-touch controls (strips, side buttons, knobs not handled by `knob_pages`), `global_buttons` is tried first if it has real actions, then the current page's `buttons` for that id.
5. If still nothing — `bindings` (legacy): first matching rule wins.

Then `run_actions` executes the list (OBS, Home Assistant, HTTP, sound, …) in order.

---

## Top-level keys

| Key | Purpose |
|---|---|
| `logging` | Console + rotating file logs. |
| `obs` | OBS WebSocket host, port, password. |
| `ha` | Home Assistant base URL + long-lived access token. |
| `device` | Serial port path, baud rate, hardware model. |
| `pages` | Primary UI: list of pages, each with a `buttons` map. |
| `global_buttons` | Controls shared across pages: knobs, strips, side buttons (not the center touch grid). |
| `knob_pages` | Per-knob stacks of virtual pages (rotate = actions, push = cycle). |
| `bindings` | Legacy event → actions list (fallback when `pages` matching fails). |
| `spotify` | Client ID + redirect URI for PKCE (tokens stored beside config). |
| `twitch` | Client ID/secret or token for `display.twitch_live`. |
| `plugin_modules` | Paths to extra Python files that register custom actions. |

### `obs`

```yaml
obs:
  host: 127.0.0.1
  port: 4455
  password: ""   # OBS → Tools → WebSocket Server Settings → Show Connect Info
```

### `ha` (Home Assistant)

```yaml
ha:
  base_url: "http://homeassistant.local:8123"
  token: ""   # Profile → Security → Long-Lived Access Tokens → Create Token
```

### `device`

```yaml
device:
  path: ""          # empty = auto-discover; or e.g. /dev/ttyACM0, COM5
  model: auto        # auto | live_s | live
  # baudrate: 460800  # optional; try if handshake fails
```

`auto` picks the driver from USB VID `0x2ec2` + PID (`0x0006` = Live S, `0x0004` = Live) when possible. `live_s` = 5×3 touch, two knobs, four physical keys, any number of `pages` (only indices 0–3 reachable from hardware). `live` = original Loupedeck Live (4×3 touch + strips + more buttons/knobs).

### `pages`

```yaml
pages:
  - id: 0
    name: Scenes
    buttons:
      touch_0:
        text: Live
        action: { type: obs.set_scene, scene: "Live" }
      touch_1:
        text: BRB
        actions:
          - { type: http.request, method: GET, url: "https://example.com/alert" }
          - { type: sound.play, file: library/sounds/ping.wav, player: auto }
```

`action` (single object) or `actions` (list, runs in order) — use a list for a macro.

### `global_buttons`

Knobs, strips, physical side buttons — same shape as under `pages[].buttons`. Touch cells (`touch_*`) always belong under `pages[].buttons`, never here.

```yaml
global_buttons:
  strip_left: { text: Prev, action: { type: agent.prev_page } }
  knobTL: { text: Vol, action: { type: sound.volume_delta, delta: 2 } }
```

Lookup: for a non-touch control, `global_buttons.<id>` wins if it has an action; otherwise the current page's `buttons.<id>` is used.

### `knob_pages`

```yaml
knob_page_feedback:
  duration_sec: 1.5   # cap on how long the page name flashes on a touch key after cycling

knob_pages:
  knobTL:
    pages:
      - name: System volume
        rotate_left: { type: sound.volume_delta, delta: -2 }
        rotate_right: { type: sound.volume_delta, delta: 2 }
      - name: Deck pages
        rotate_left: { type: agent.prev_page }
        rotate_right: { type: agent.next_page }
```

`rotate_left`/`rotate_right` (aliases `left`/`right`) take one action or a list. Push cycles to the next inner page. Don't put knob rotation in `global_buttons` with fake ids like `knobTL_left` — use `knob_pages` only.

### `bindings` (legacy)

```yaml
bindings:
  - match: { type: touch, key: 0, edge: down }   # type: touch | button | knob
    actions:
      - { type: obs.set_scene, scene: "Fallback scene" }
```

Only used when `pages` matching returns nothing. First matching rule wins. Prefer `pages` + `global_buttons` for new configs.

### `spotify`

```yaml
spotify:
  client_id: ""
  redirect_uri: "http://127.0.0.1:8765/api/spotify/callback"
```

Complete OAuth from the config window's Services tab; tokens persist in `spotify_tokens.json`.

### `twitch`

```yaml
twitch:
  client_id: ""
  client_secret: ""
  # access_token: ""   # optional static bearer
```

### `plugin_modules`

```yaml
plugin_modules:
  - "/absolute/path/to/my_actions.py"
```

Each file is imported once; register actions with `@register_action("my.namespace.action")` and `async def run(self, ctx, params)` — see `examples/custom_action.py`.

---

## Button entries: visuals

Every value under `buttons` is a mapping of optional visuals plus one or more actions.

| Field | Role |
|---|---|
| `text`, `label` | Line(s) of text; font scales down to fit. |
| `image` | Bitmap background (path relative to config dir, or absolute). |
| `icon` | `si:slug` / `simpleicons:slug` (Simple Icons), `lucide:name`, `heroicons:24/solid/name`, `mdi:name`, or any `https://…` SVG URL. |
| `background`, `text_color` | Solid color (`#rrggbb` or CSS name). |
| `font_size`, `font_file` | Optional typography (`.ttf`/`.otf`/`.ttc`, path under `library/fonts/`). |
| `graphic_text_layout` | `split` (graphic on top, text below) or `overlay` (text on top of the graphic) — only relevant when both a graphic and text are set. |
| `button_color` | Live S physical keys only: LED color for `btn_circle`, `btn_1`–`btn_3`. |

### Gradients and animations

Any text or background color can be a gradient instead of solid — set both stops and it takes over automatically:

```yaml
text_gradient_from: "#ff0000"
text_gradient_to: "#0000ff"
text_gradient_angle: 45          # degrees, optional (default 0)
background_gradient_from: "#222222"
background_gradient_to: "#8844ff"
background_gradient_angle: 90
```

Continuous "idle" animation (plays while the key is at rest):

```yaml
idle_animation: shake            # none | shake | pulse | gradient_rotate | color_cycle
idle_animation_speed: 1.0        # 0.1–10
```

One-shot "press" animation (plays once when the key is pressed):

```yaml
press_animation: slide_reappear  # none | flash | invert | zoom_text | slide_reappear
press_animation_direction: left  # left | right | up | down — slide_reappear only
press_flash_color: "#ffffff"     # flash only
```

Everything above is previewable in the config window before you touch the real hardware (design rule: any text on a key must be previewable and fully customizable this way).

### Actions

`action` (single object, `{ type: …, … }`) or `actions` (list). `type` is one of the strings below; parameters match the built-in catalog (`GET /api/action_catalog`, also what drives the config window's form).

---

## Action types reference

### OBS

| `type` | Parameters |
|---|---|
| `obs.set_scene` | `scene` |
| `obs.toggle_mute` | `input_name` (or `input`) |
| `obs.input_volume_set` | `input_name`, `percent` (0–100) |
| `obs.input_volume_delta` | `input_name`, `delta` |

### Home Assistant

| `type` | Parameters |
|---|---|
| `ha.turn_on` | `entity_id`; optional `data` (JSON object forwarded to `homeassistant.turn_on` — e.g. `{brightness_pct: 60, rgb_color: [255,120,0]}` for a light) |
| `ha.turn_off` | `entity_id`; optional `data` |
| `ha.toggle` | `entity_id`; optional `data` |
| `ha.run_script` | `script` — object id (`good_night`) or full entity id (`script.good_night`) |
| `ha.call_service` | `domain`, `service`, optional `entity_id`, optional `data` — fully generic (e.g. `climate.set_temperature`, `cover.open_cover`, `automation.trigger`) |

### HTTP / shell

| `type` | Parameters |
|---|---|
| `http.request` | `url`, `method`, optional `headers`, `json`, `body`, `timeout` |
| `command.run` | `argv` (list of strings) **or** `shell` (string) — not both |

### Local sound / system volume

| `type` | Parameters |
|---|---|
| `sound.play` | `file`; optional `player` (`auto`, `mpv`, `ffplay`, `afplay`) |
| `sound.volume_set` | `percent`; optional `sink` (Linux `pactl`/`wpctl` only) |
| `sound.volume_delta` | `delta`; optional `sink` |
| `sound.mute_toggle` | `mode`: `toggle`, `mute`, `unmute` |

### OBS overlay (browser source)

| `type` | Parameters |
|---|---|
| `overlay.show_media` | `file`; optional `x`, `y`, `width`, `duration_sec`, `muted` |
| `overlay.play_sound` | `file`; optional `volume` |
| `overlay.clear` | — |

### Agent / pages

| `type` | Parameters |
|---|---|
| `agent.next_page`, `agent.prev_page` | — |
| `agent.goto_page` | `index` and/or `name` and/or `id` |

### Display (agent-driven; press does nothing)

| `type` | Parameters |
|---|---|
| `display.clock` | `time_format`, `date_format`, `timezone` (strftime; optional) |
| `display.live_message` | `template`; optional `url` + `interval_seconds` for an HTTP-backed value |
| `display.twitch_live` | `login`, `template`, `interval_seconds` |
| `display.obs_stream` | `template`, `interval_seconds` |
| `display.obs_scene` | `template`, `interval_seconds` |
| `display.battery` | `template`, `interval_seconds` — host battery/AC |
| `display.ha_sensor` | `entity_id`, `template` (default `{state}{unit}`), `interval_seconds` |
| `display.ha_weather` | `entity_id` (a `weather.*` entity), `template` (default `{condition}\n{temperature}{temperature_unit}`), `interval_seconds` |

### Spotify (after OAuth)

| `type` | Parameters |
|---|---|
| `spotify.play_pause`, `spotify.next`, `spotify.previous` | optional `device_id` |
| `spotify.volume_set`, `spotify.volume_delta` | volume params, optional `device_id` |
| `spotify.play_playlist` | `playlist` (URI, link, or id), optional `device_id` |

---

## Backups

- One rotating backup is taken automatically every time the app starts (best-effort, never blocks startup).
- The config window's Services tab lists the last 3 (`.bak1`–`.bak3`) with a **Restore** button on each — restoring is itself undoable with Ctrl+Z.
- Manual "Backup config" / "Remove backups" buttons are also there if you want an extra snapshot before a risky edit.

## Linux serial permissions

```bash
sudo usermod -aG dialout $USER   # then log out and back in
sudo cp udev/99-loupedeck.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
```

Use `--no-device` until permissions work.

## Troubleshooting

| Symptom | Check |
|---|---|
| No actions on key | Wrong control id (canonical ids only); empty `action`/`actions`; Live S `btn_circle`/`btn_1-3` are reserved for page switching; knob rotation only via `knob_pages`. |
| OBS errors | `obs.password`, firewall, WebSocket server enabled on `obs.port`. |
| Home Assistant errors | `ha.base_url` reachable from this machine, `ha.token` valid (Services tab shows Connected/Offline). |
| Overlay blank | Browser source URL/port; agent running with `--web`; file under `library/` and path correct in YAML. |
| Volume fails | Linux: install `pactl`/`wpctl`; Windows: bundled `pycaw`; macOS: Automation permission for the agent if `osascript` is blocked. |
| Config not saving | Permissions on the config directory; check the save-status indicator in the header. |

## See also

- [README](../README.md) — install, features, building from source
- `config.example.yaml` — commented starter file in the repo root
