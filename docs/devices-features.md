# Feature-driven devices (design)

Status: decided, being implemented in lots (see "Plan"). English is the source language of the docs.

## Goal
A device **model** declares what it *has* (a list of typed controls, each with its own capabilities and
a position). The application derives from it, in the backend, (1) the **configuration** that can be
attached to each control and (2) the **editor UI**. Assigning actions to keys, buttons and knobs must
not care about the physical shape: a future "mega" Loupedeck (64 keys, 12 buttons, 6 knobs), a Stream
Deck, or a **virtual device** (a browser-rendered one, no hardware) is only a new model description.

## Model
* `DeviceModel`: `id`, `family` (backend that drives it), `name`, `config_names`, `layout` (abstract
  size, used to draw the device and to compute proximity) and `controls`.
* `Control`: `id`, `kind`, `name`, `position` (x, y, w, h in layout units), and its own capabilities:
  * **inputs** it can emit: `press` (press+release), `rotate` (delta), `touch` (x, y), `value`
    (absolute 0..1, sliders/potentiometers). *Long press is not a hardware capability*: the backend
    core derives it from press/release timing for every control that has `press`.
  * **outputs** it can receive: `image` (pixel size), `led` (`rgb` | `mono`), or nothing.
  * `feedback_key` (optional): the display control used to show feedback about this control (knob
    turn, button press). Default: the nearest control with an `image` output by position; none = no
    visual feedback (the UI shows a toast instead).
* Device-wide only: `brightness` (bool). No other global flag: everything else is per control.
* Kinds: `key` (display key), `button`, `knob`, `slider`, `strip` (touch area), `pedal`.

## Control ids (stable, model-independent)
* Display keys: `key_<col>_<row>`, zero-based, column first (`key_0_0` = top-left).
* Others: `knob_<n>`, `button_<n>`, `slider_<n>`, `strip_<n>`, `pedal_<n>`, zero-based in the model's
  declared order (by position, left to right then top to bottom).
* A configuration entry for a control the connected device does not have is **kept but inactive**
  (never deleted), so switching between devices is lossless.

## Bindings and pages (one rule for every control)
Not a device property: application logic.
* Each control may have a **global** binding and, per page, a binding that **overrides** it.
* Resolution at runtime: the current page's binding if present, else the global one.
* Display keys are normally page-bound; the buttons that switch page are simply global bindings
  "go to page N", created by default when a device has buttons (a default, not a hardware fact).
* A binding's shape follows the control's capabilities (key: action + look; knob: rotate role +
  press action; button: action + LED colour; slider: a value action).

## Backend protocol
`open/close`, `set_image(control_id, image)`, `set_led(control_id, rgb)`, `set_brightness(pct)`,
events delivered as `ControlEvent(control_id, type, value)` where `type` is `press|release|rotate|
touch|value`; unplug signal. The virtual device backend implements the same protocol, with events
coming from the browser and images going to the browser.

## Config schema (`config_version: 2`, lot 1)
```yaml
config_version: 2
device: {model: auto}          # auto | live_s | live: the grid key coordinates refer to
global:                        # control id -> binding, active on every page
  button_0: {action: {type: agent.goto_page, index: 0}, button_color: "#3b6bff"}
  knob_0: {rotate: {duo: system_volume}}          # a knob role on every page
pages:
  - name: Main
    controls:                  # control id -> binding, overrides `global` on this page
      key_0_0: {text: BRB, action: {type: obs.set_scene, scene: BRB}}
      knob_0: {rotate: {duo: spotify_volume}, press: {type: spotify.play_pause}}
bindings: []                   # optional flat rules, last resort (legacy form still read)
```
* One map per scope, keyed by control id: `global` and `pages[].controls` (they replace
  `global_buttons`, `pages[].buttons` and `pages[].knobs`). The entry shape follows the control's
  kind: key / button / strip = `action`|`actions` + look fields (+ `button_color` for a button
  LED); knob = `rotate` (duo or `left`/`right`) + `press` + `feedback_sec`.
* Resolution (`bindings.resolve_binding`): the page entry if it is a mapping, else the global
  one, for every kind (images, LEDs, presses, knob roles). Runtime caches use the binding's
  storage key `p<page>:<id>` / `g:<id>`.
* Default bindings: buttons with an LED output open pages 1..n (`agent.goto_page`), created when
  a config is created or migrated. On the Live S that is `button_0..3`, as before.
* Flat `bindings`: `match: {control: key_0_0, type: press}` (or `rotate` + `direction`), or the
  legacy `type: touch|button|knob` rules, mapped on the device model.
* Kept as is: any id that is not a control of the device (another model's control, a legacy id
  that was inactive, an unknown key) stays in its map and never resolves.

### Web UI compatibility (until lot 3)
The current front-end still edits the legacy shape. `GET /api/config` returns a *view* of the v2
config in that shape (`config_migrate.to_ui_view`, for the model the UI lays out: `device.model`,
else the connected device, else Live S); `PUT /api/config` accepts that view (converted back by
the migration, `migrate_config(to_ui_view(c)) == c`), a legacy config, or a v2 one as is
(`config_version: 2`). Bindings without a legacy equivalent ride along in the view under their
control id, `_v2_inactive` (inactive ids), `_v2_action(s)` (a page button whose action is not its
default) and `_v2_unbound` (page buttons without a global binding). `GET /api/config?format=v2`
returns the stored document. The other endpoints (`simulate_press`, `preview_key`, `/api/packs`,
`touch_errors` in `/api/status`) accept or emit legacy ids for the UI and accept control ids.

## Migration
Config gets a `config_version`. Legacy configs (`touch_N`, `knobTL`, `btn_circle`, `global_buttons`,
per-knob legacy pages already migrated to `pages[].knobs`) are converted once at load, after a backup
copy of the file, using the grid of `device.model` (`auto` → Live S). Idempotent, covered by tests on
realistic configs (`config.example.yaml`, `examples/`, packs). The old ids stay readable forever.

Implemented in `config_migrate.migrate_config` (lot 1), run by `ConfigState` when it loads a file
without `config_version` (backup first: `open-loupedeck-backups/<name>.pre-v2`, never rotated nor
overwritten), and in memory for any legacy body the API receives:
* `touch_N` -> `key_<N % cols>_<N // cols>` on the grid of `device.model` (`auto` -> Live S);
  `knobTL..knobBR` -> `knob_0..5`, `btn_circle` (and `btn_0`) -> `button_0`, `btn_N` ->
  `button_N`, `strip_left`/`left` -> `strip_0`, `strip_right`/`right` -> `strip_1` (same on every
  Loupedeck: a Live id in a Live S config becomes an inactive control there).
* Legacy runtime rules are preserved, not reinterpreted: an entry the old runtime never used keeps
  its old id (inactive): touch keys / knobs in `global_buttons`, strips / Live S page buttons in a
  page, a page round-button entry whose global one had actions (the old global-first rule), keys
  beyond the grid. The Live S page buttons get `action: agent.goto_page N`; an action they had
  (never run) is kept as `legacy_action(s)`.
* Legacy `knob_pages` are first turned into page knob roles (as before), then into `controls`.
* Packs (`packs/*.json`) are written in control ids for a 5 x 3 grid (`grid`); on another device
  a key keeps its coordinates and is dropped (with a note) when it is outside the grid.

## Plan (lots, in order)
1. Model + ids + bindings core + migration + runtime on control ids (backend, no UI change beyond what
   the migration forces). Loupedeck Live / Live S become model descriptions.
2. Virtual device backend (browser) + `/api/device_model` with layout; it is also the test bench.
3. Generic editor UI rendered from the model (deck, inspector per capability, global vs page scope).
4. Stream Deck backend (`python-elgato-streamdeck`, experimental until tested on hardware).
5. Polish pass (UI beauty and ergonomics), docs, packs for any grid size, release notes.
