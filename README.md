<p align="center">
  <img src="press-kit/logo/wordmark-transparent.png" alt="Open-Loupedeck" width="480">
</p>

**Open-Loupedeck** is a background app that connects to **Loupedeck Live** or **Loupedeck Live S** hardware over USB and turns button presses, touches, and knob rotations into actions: switching **OBS** scenes, controlling **Home Assistant** devices, firing webhooks, playing sounds, controlling **Spotify**, showing live stats, and drawing fully custom text/graphics (with gradients and animations) on the keys.

It's an alternative to the official Loupedeck application — install it, and it runs quietly in the background (tray icon), with a native configuration window you open on demand. No official Loupedeck software required.

> **Heads-up:** this project is almost entirely "vibe-coded" — built collaboratively with [Claude Code](https://claude.com/claude-code) (Anthropic's AI coding agent) rather than hand-written line by line. See [Acknowledgments](#acknowledgments) below. It works, it's tested against real hardware, but review the code yourself before trusting it with anything critical.

---

## Install (Windows)

1. Grab the latest installer from [Releases](../../releases).
2. Run it. It installs to Program Files, adds a Start Menu shortcut, and launches Open-Loupedeck.
3. A tray icon appears; the configuration window opens automatically. Close the window any time — the app keeps running in the tray. Right-click the tray icon for **Restart** (applies changes that need a fresh start) or **Quit**.
4. Plug in your Loupedeck. The web-based config UI (opened in a native window, not a browser) will pick it up automatically.

macOS and Linux packages ([`.dmg`](packaging/macos/build_dmg.sh) / [AppImage](packaging/linux/build_appimage.sh)) are built but not yet tested on real hardware — see [Building from source](#building-from-source) to run it there today.

**Updating:** the tray menu checks for updates automatically and asks for confirmation before installing (never silent — this app can be mid-stream when a release lands). Windows only for now; macOS/Linux users get a link to the release page instead.

---

## What you can do with it

| Area | Highlights |
|---|---|
| **OBS Studio** | Switch scenes, toggle mute, set/adjust source volume (WebSocket v5). |
| **Home Assistant** | Turn devices on/off/toggle (lights, switches, anything), run scripts, call any service; show a sensor's state or the weather forecast on a key. |
| **Spotify** | Play/pause, skip, volume, play a specific playlist (PKCE OAuth, no client secret needed). |
| **Twitch** | Show live/offline status, viewer count, uptime for one or more channels. |
| **OBS browser overlay** | A transparent 1920×1080 browser source that plays videos/GIFs/images/sounds on command, driven by the same actions. |
| **HTTP / shell / system audio** | Webhooks, local sound playback, shell commands, system output volume. |
| **Keyboard macros** | Record a sequence of real keystrokes in the UI and replay them in order on a key press — sent to whatever app has focus. |
| **Custom key graphics** | Text or images on every key, fully previewable before you press anything: solid colors *or* gradients (text and background, any angle), continuous "idle" animations (shake, pulse, rotating gradient, color cycle), one-shot "press" animations (flash, invert, zoom, slide-out-and-back), custom fonts, icon packs (Simple Icons, Lucide, Heroicons, MDI) or your own images. |
| **Pages** | As many pages as you want, reordered by drag-and-drop, with the 4 hardware page-switch buttons (Live S) clearly marked. |

Hardware protocol via [python-loupedeck-live](https://github.com/devleaks/python-loupedeck-live).

---

## The configuration window

Open it from the tray icon ("Open configuration"). Two tabs:

- **Buttons** — the page list (left rail: drag to reorder, click to switch, ✕ to remove), the deck grid, and the button editor. Editing a button autosaves as you type (a red outline means the value isn't valid yet, so it's never saved half-broken) and pushes the update to the physical device live. **Ctrl+Z / Ctrl+Shift+Z** undo/redo anything you just did, for the current session.
- **Services** — OBS, Home Assistant, Spotify, Twitch, and logging credentials/settings; hardware model override; "Launch at startup"; config backups (one is taken automatically every time the app starts, and you can restore any of the last 3 from here); a button to open the config folder directly.

Drag one button onto another to swap their entire configuration (action, text, colors, animations — everything).

---

## Building from source

Needs **Python 3.10+**.

```bash
git clone https://github.com/helldog136/open-loupedeck.git
cd open-loupedeck
python3 -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e .
```

Run it:

```bash
# Full agent + config UI (opens a browser tab instead of a native window in this mode)
open-loupedeck --web 127.0.0.1:8765

# Config UI only, no hardware required (e.g. to edit a config on a machine without the deck)
open-loupedeck --web 127.0.0.1:8765 --no-device

# Tray app (native window, same as the installed version)
python -m open_loupedeck.tray_app
```

| CLI option | Meaning |
|---|---|
| `--config PATH` | Path to `config.yaml`. Default: per-OS path, see below. |
| `-v`, `--verbose` | Verbose logging. |
| `--web [HOST:PORT]` | Start the embedded HTTP server (default `127.0.0.1:8765` if given with no value). |
| `--no-device` | Don't open the Loupedeck serial device — pairs with `--web` to edit config without hardware. |
| `--log-dir DIR` | Override the log directory. |

Building the installers locally: `packaging/pyinstaller.spec` (PyInstaller onedir build, all 3 OSes) then `packaging/windows/installer.iss` (Inno Setup, Windows) / `packaging/macos/build_dmg.sh` / `packaging/linux/build_appimage.sh`.

Running the test suite: `pytest` (unit tests, no hardware needed) and `ruff check` / `ruff format --check` (lint).

### Linux serial permissions

If opening `/dev/ttyACM*` fails with "permission denied":

```bash
sudo usermod -aG dialout $USER   # then log out and back in
sudo cp udev/99-loupedeck.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
```

---

## Configuration file

The config lives at:

| OS | Path |
|---|---|
| Windows | `%APPDATA%\open-loupedeck\config.yaml` |
| macOS | `~/Library/Application Support/open-loupedeck/config.yaml` |
| Linux | `~/.config/open-loupedeck/config.yaml` |

Editing it by hand is possible (it's plain YAML) but the config window covers everything and validates as you go — see **[docs/configuration.md](docs/configuration.md)** for the full schema (every action type and its parameters, dispatch order between pages/global_buttons/bindings, the button design fields, troubleshooting) if you want to script it directly or write a plugin.

Extra Python actions: `plugin_modules: ["/path/to/file.py"]` in the config, `@register_action("my.action")` in the file — see `examples/custom_action.py`.

---

## License

[PolyForm Noncommercial 1.0.0](LICENSE): fork it, modify it, use it for anything non-commercial. No reselling. Third-party dependencies keep their own licenses — see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Acknowledgments

This project — the Python agent, the packaging, the auto-updater, the web-based config UI, and this documentation — was built through an extended pair-programming session with **[Claude Code](https://claude.com/claude-code)**, Anthropic's AI coding agent, working directly against real Loupedeck hardware. If something looks a little inconsistent in a corner we haven't revisited, that's why — issues and PRs welcome.
