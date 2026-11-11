# Devices: models and backends

Open-Loupedeck talks to hardware through a small device layer in
`src/open_loupedeck/devices/`. The agent, the skin renderer, the knob feedback, the brightness
controller and the web UI only know two things about a device:

- its **model descriptor** (`DeviceModel`): pure data, what the device has and can do;
- its **backend** (`DeviceBackend`): the opened device, addressed by control id.

Everything driver-specific (pixel formats, serial threads, protocol names, upstream patches)
stays inside one backend package. Today there is one backend, `loupedeck` (Live and Live S).

```
devices/
  model.py        DeviceModel, KeyGrid, ControlSpec, Capabilities   (pure data)
  base.py         DeviceBackend protocol, BackendFactory, DiscoveredDevice
  registry.py     registered backends, discover_devices(), open_backend(settings)
  loupedeck/
    models.py     LOUPEDECK_LIVE, LOUPEDECK_LIVE_S descriptors
    backend.py    LoupedeckBackend (wraps the driver), open_loupedeck(), factory
    live_s.py     Live S driver subclass (touch geometry, 480x270 framebuffer)
    patches.py    upstream driver fixes (init, serial reader exits on unplug)
    discovery.py  USB VID/PID lookup of serial ports
    events.py     driver callback dict -> NormalizedEvent
```

The old module paths (`hardware/live_s_device.py`, `loupedeck_patch.py`,
`device_discovery.py`, `events.normalize_loupedeck_message`) are thin re-export shims.

## Model descriptor (`DeviceModel`)

| Field | Meaning |
| --- | --- |
| `id` | Stable model id (`loupedeck_live`, `loupedeck_live_s`). |
| `family` | Backend that drives it (`loupedeck`). |
| `name` | Display name. |
| `grid` | `KeyGrid(rows, cols, key_size, id_prefix="touch_")`: key `n` is `touch_n`, numbered row by row. |
| `controls` | `ControlSpec(id, kind, name, size)` for everything outside the grid; `kind` is `button`, `knob`, `strip` or `led_button`; `size` is set when the control takes an image. |
| `capabilities` | `brightness`, `button_led`, `touch`, `knobs`. |
| `config_names` | `device.model` values that select it (`live`, `live_s`); the first is canonical. |
| `knob_feedback_keys` | Knob id -> the grid key next to it, where knob feedback is flashed. |
| `page_buttons` | Physical buttons that open deck page 0, 1, 2... directly. |
| `default_button_rgb` | LED colour of an `led_button` without `button_color`. |

Control ids are the keys of `config.yaml` (`touch_N`, `knobTL`, `btn_circle`, `btn_1`,
`strip_left`...). They are part of the config format: **never rename them** for an existing
model, or existing configs stop working.

`GET /api/device_model` returns the descriptor (`DeviceModel.to_dict()`) of the connected device,
else of the configured `device.model` (`null` for `auto` without a device).

## Backend (`DeviceBackend`)

```python
backend.model                      # DeviceModel
backend.path                       # where it was opened (status page, logs)
backend.is_open / backend.unplugged
backend.open(); backend.close()
with backend: ...                  # update lock for a batch of draws
backend.set_key_image(control_id, pil_image)   # sized with model.key_size_for(control_id)
backend.set_brightness(pct)                     # 0..100
backend.set_button_color(control_id, (r, g, b)) # led_button controls
backend.set_event_callback(fn)     # fn(NormalizedEvent), called from the backend's thread
backend.set_unplugged_callback(fn) # fn(), once, from any thread (also fired late if already gone)
```

Events are `open_loupedeck.events.NormalizedEvent(kind, id, edge, raw)`:

- `touch`: `id` is the key index (int), `edge` `down`/`up`;
- `button`: `id` is a button id understood by `control_ids.control_ids_for_lookup`
  (`btn_circle`, `btn_3`, or the Loupedeck's bare `circle` / `3`), `edge` `down`/`up`.
  A knob press is a `button` event whose id is the knob id (`knobTL`);
- `knob`: `id` is the knob id, `edge` `left`/`right`.

The agent (`app.py`) opens the device with `devices.registry.open_backend(settings)`, registers
the event and unplug callbacks, and on unplug the reconnect loop opens a fresh backend every 2 s.
`runtime.deck` holds the current backend (the attribute name is kept for compatibility).

## Registry

`devices.registry` keeps one `BackendFactory` per family (`family`, `models`, `discover()`,
`open(settings)`, `normalize_message(msg)`). Built-in backends are registered lazily, so importing
the registry imports no driver.

- `discover_devices()` lists `DiscoveredDevice(backend, path, model)` from every backend.
- `open_backend(settings)`: a `device.model` naming a known model goes to that model's backend;
  `auto` (or an unknown value) tries each backend in registration order. With one backend its
  error message is raised unchanged. `device.path` and `device.baudrate` are the backend's
  business (the Loupedeck backend honours them exactly as before).
- `DeviceRegistry([...])` builds a registry with injected factories (tests).

## Checklist: adding a device backend

1. **Descriptor.** Create `devices/<family>/models.py` with one `DeviceModel` per model. Pick
   control ids that match the existing scheme where the hardware matches (`touch_N` for the key
   grid, `btn_*` for buttons, `knob*` for encoders) so pages, packs and the UI keep working.
   Fill `capabilities`, `config_names`, `knob_feedback_keys` (if it has knobs) and `page_buttons`
   (if physical buttons should switch pages).
2. **Backend class.** Implement every method of `DeviceBackend` (see `devices/base.py`). Keep all
   driver imports inside the package. `set_key_image` receives an RGBA PIL image already sized
   with `model.key_size_for(control_id)`; convert it to the device format there. Ignore (log)
   ids the model cannot draw.
3. **Events.** Translate native input to `NormalizedEvent` in the backend's thread and pass it to
   the event callback; drop what is not a press / release / turn. Never block that thread on the
   agent.
4. **Unplug.** Detect disconnects (read errors, HID removal) and call the unplugged callback once;
   `close()` must be safe afterwards. The agent's reconnect loop does the rest.
5. **Factory.** Provide a `BackendFactory` (`family`, `models`, `discover()`, `open(settings)`
   raising a clear `RuntimeError` when nothing answers, `normalize_message()` returning `None` for
   foreign dicts) and add it to `_builtin_factories()` / `_builtin_models()` in
   `devices/registry.py` (and to `hiddenimports` in `packaging/pyinstaller.spec`, since the
   registry imports backends lazily).
6. **Config.** Document the new `device.model` values. Existing `live` / `live_s` / `auto`
   configs must keep working untouched.
7. **Tests.** Add descriptor tests (counts, ids, sizes), a backend test over a fake driver
   (key mapping, events, unplug), and run the agent tests with `tests/fake_backend.FakeBackend`
   built on the new model.
8. **Hardware check.** Before building on it: every key draws in the right place, presses /
   turns map to the right control ids, brightness, LEDs, unplug + replug reconnects.
