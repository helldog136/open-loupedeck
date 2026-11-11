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

## Migration
Config gets a `config_version`. Legacy configs (`touch_N`, `knobTL`, `btn_circle`, `global_buttons`,
per-knob legacy pages already migrated to `pages[].knobs`) are converted once at load, after a backup
copy of the file, using the grid of `device.model` (`auto` → Live S). Idempotent, covered by tests on
realistic configs (`config.example.yaml`, `examples/`, packs). The old ids stay readable forever.

## Plan (lots, in order)
1. Model + ids + bindings core + migration + runtime on control ids (backend, no UI change beyond what
   the migration forces). Loupedeck Live / Live S become model descriptions.
2. Virtual device backend (browser) + `/api/device_model` with layout; it is also the test bench.
3. Generic editor UI rendered from the model (deck, inspector per capability, global vs page scope).
4. Stream Deck backend (`python-elgato-streamdeck`, experimental until tested on hardware).
5. Polish pass (UI beauty and ergonomics), docs, packs for any grid size, release notes.
