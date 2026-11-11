# Devices: models and backends

Open-Loupedeck talks to hardware through a small device layer in
`src/open_loupedeck/devices/`. The agent, the skin renderer, the knob feedback, the brightness
controller and the web UI only know two things about a device:

- its **model descriptor** (`DeviceModel`): pure data, what the device has and can do;
- its **backend** (`DeviceBackend`): the opened device, addressed by control id.

Everything driver-specific (pixel formats, serial threads, protocol names, upstream patches)
stays inside one backend package. Today there are two backends: `loupedeck` (Live and Live S) and
`virtual` (a browser-rendered device, see `docs/virtual-device.md`; chosen by name only, never by `auto`).

```
devices/
  model.py        DeviceModel, Control, Position, control id helpers   (pure data)
  base.py         DeviceBackend protocol, BackendFactory, DiscoveredDevice
  registry.py     registered backends, discover_devices(), open_backend(settings)
  loupedeck/
    models.py     LOUPEDECK_LIVE, LOUPEDECK_LIVE_S descriptors (+ legacy-id tables)
    backend.py    LoupedeckBackend (wraps the driver), open_loupedeck(), factory
    live_s.py     Live S driver subclass (touch geometry, 480x270 framebuffer)
    patches.py    upstream driver fixes (init, serial reader exits on unplug)
    discovery.py  USB VID/PID lookup of serial ports
    events.py     driver callback dict -> ControlEvent
```

The old module paths (`hardware/live_s_device.py`, `loupedeck_patch.py`,
`device_discovery.py`, `events.normalize_loupedeck_message`) are thin re-export shims.

## Model descriptor (`DeviceModel`)

The feature model of `docs/devices-features.md`: a model declares the controls it has; nothing
device-wide except `brightness`.

| Field | Meaning |
| --- | --- |
| `id` | Stable model id (`loupedeck_live`, `loupedeck_live_s`). |
| `family` | Backend that drives it (`loupedeck`). |
| `name` | Display name. |
| `layout` | Abstract size `(width, height)`; control positions use these units (a key is 1 x 1). |
| `controls` | `Control(id, kind, name, position, inputs, image, led, default_led, feedback_key)`. |
| `brightness` | The screen brightness can be set. |
| `config_names` | `device.model` values that select it (`live`, `live_s`); the first is canonical. |
| `legacy_ids` | `(legacy id, control id)` pairs read by the config migration (`touch_N`, `knobTL`...). |

A `Control` has a `kind` (`key`, `button`, `knob`, `slider`, `strip`, `pedal`), a `position`
(`x, y, w, h`), the `inputs` it emits (`press`, `rotate`, `touch`, `value`) and its outputs:
`image` (pixel size) and/or `led` (`rgb` | `mono`, with `default_led`). `feedback_key` names the
display control showing feedback about it; without one, `model.feedback_key_for(id)` takes the
nearest control with an image output.

Control ids are stable and model-independent: `key_<col>_<row>` (zero-based, column first) for
display keys, `knob_<n>`, `button_<n>`, `strip_<n>`... numbered by position (left to right, then
top to bottom). They are the keys of `config.yaml` (`config_version: 2`): **never renumber them**
for an existing model. `model.problems()` checks a descriptor (ids vs kinds and positions,
layout bounds, feedback keys, legacy table); the tests run it on every model.

Helpers: `keys()` (row by row), `control(id)`, `controls_of_kind()`, `grid_of_keys()` ->
`(cols, rows)`, `image_controls()`, `led_controls()`, `image_size(id)`, `nearest_display(id)`,
`feedback_key_for(id)`, `to_dict()`.

`GET /api/device_model` returns `model` (the connected device's `to_dict()`, else the configured
`device.model`'s, `null` for `auto` without a device), `config_model` (what the config's key
coordinates refer to: `auto` -> Live S) and every known model under `models`.

## Backend (`DeviceBackend`)

```python
backend.model                      # DeviceModel
backend.path                       # where it was opened (status page, logs)
backend.is_open / backend.unplugged
backend.open(); backend.close()
with backend: ...                  # update lock for a batch of draws
backend.set_image(control_id, pil_image)  # controls with an image output, sized model.image_size(id)
backend.set_led(control_id, (r, g, b))    # controls with an led output
backend.set_brightness(pct)               # 0..100
backend.set_event_callback(fn)     # fn(ControlEvent), called from the backend's thread
backend.set_unplugged_callback(fn) # fn(), once, from any thread (also fired late if already gone)
```

Events are `open_loupedeck.events.ControlEvent(control_id, type, value, raw)` with `type`
`press` / `release` (no value), `rotate` (`value` = signed steps, +1 = right), `touch`
(`value` = `(x, y)`) or `value` (0..1). A knob press is a `press` of the knob. Long press is not
a hardware capability; it is not derived yet.

The agent resolves every event through one rule (`bindings.resolve_binding`: page binding, else
global) and draws every image / LED output from the same rule (`deck_skin.apply_page_skin`).

The agent (`app.py`) opens the device with `devices.registry.open_backend(settings)`, registers
the event and unplug callbacks, and on unplug the reconnect loop opens a fresh backend every 2 s.
`runtime.deck` holds the current backend (the attribute name is kept for compatibility).

## Registry

`devices.registry` keeps one `BackendFactory` per family (`family`, `models`, `discover()`,
`open(settings)`, `normalize_message(msg, model)`). Built-in backends are registered lazily, so importing
the registry imports no driver.

- `discover_devices()` lists `DiscoveredDevice(backend, path, model)` from every backend.
- `open_backend(settings)`: a `device.model` naming a known model goes to that model's backend;
  `auto` (or an unknown value) tries each backend in registration order. With one backend its
  error message is raised unchanged. `device.path` and `device.baudrate` are the backend's
  business (the Loupedeck backend honours them exactly as before).
- `resolve_model(configured, device)`: the device's model, else `device.model`'s, else the
  default (Live S); `config_model(configured)` ignores the device.
- `DeviceRegistry([...])` builds a registry with injected factories (tests).

## Checklist: adding a device backend

1. **Descriptor.** Create `devices/<family>/models.py` with one `DeviceModel` per model: every
   control with its position, inputs and outputs, `config_names`, and `feedback_key` for knobs
   whose nearest display is not the right one. Ids follow the model-independent scheme above, so
   pages, packs and the UI work unchanged. `model.problems()` must be empty.
2. **Backend class.** Implement every method of `DeviceBackend` (see `devices/base.py`). Keep all
   driver imports inside the package. `set_image` receives an RGBA PIL image already sized
   with `model.image_size(control_id)`; convert it to the device format there. Ignore (log)
   ids the model cannot draw or light.
3. **Events.** Translate native input to `ControlEvent` in the backend's thread and pass it to
   the event callback; drop what is not a press / release / turn / touch. Never block that thread
   on the agent.
4. **Unplug.** Detect disconnects (read errors, HID removal) and call the unplugged callback once;
   `close()` must be safe afterwards. The agent's reconnect loop does the rest.
5. **Factory.** Provide a `BackendFactory` (`family`, `models`, `discover()`, `open(settings)`
   raising a clear `RuntimeError` when nothing answers, `normalize_message()` returning `None` for
   foreign dicts) and add it to `_builtin_factories()` / `_builtin_models()` in
   `devices/registry.py` (and to `hiddenimports` in `packaging/pyinstaller.spec`, since the
   registry imports backends lazily).
6. **Config.** Document the new `device.model` values. Existing `live` / `live_s` / `auto`
   configs must keep working untouched.
7. **Tests.** Add descriptor tests (counts, ids, positions, sizes), a backend test over a fake driver
   (key mapping, events, unplug), and run the agent tests with `tests/fake_backend.FakeBackend`
   built on the new model.
8. **Hardware check.** Before building on it: every key draws in the right place, presses /
   turns map to the right control ids, brightness, LEDs, unplug + replug reconnects.
