# Virtual device

A device with no hardware: it is drawn in the browser, key images and LEDs go to the page, clicks
and key presses come back as ordinary control events. It implements the same `DeviceBackend`
protocol as a Loupedeck (`docs/devices.md`), so it is also the test bench for any config and for the
generic editor.

## Run it

```bash
open-loupedeck --web --virtual                 # model "virtual" (15 keys)
open-loupedeck --web --virtual virtual_mega    # or virtual_mini
```

Then open `http://127.0.0.1:8765/assets/ui/virtual.html` (use your `--web HOST:PORT`). Instead of the
flag, `device.model: virtual` (or `virtual_mega`, `virtual_mini`) in `config.yaml` selects it.

Rules:

* The virtual device is only chosen **by name**. `device.model: auto` never falls back to it, even
  when no hardware answers.
* `--no-device` wins: `--virtual` is ignored with a warning.
* `--virtual` needs `--web`. The flag overrides `device.model` for this run only; the config file is
  never touched. The page's model selector does the same (it switches the running device within
  about two seconds, through the agent's reconnect loop) and is not saved either.

## Models

| `device.model` | Id | Controls |
| --- | --- | --- |
| `virtual`, `virtual_15` | `virtual_15` | Mirrors the Live S: 5 x 3 keys (90 px), 2 knobs, 4 buttons with RGB LEDs. Same control ids and legacy ids as the Live S. |
| `virtual_mega` | `virtual_mega` | 8 x 8 keys (72 px), 6 knobs (3 left, 3 right), 12 buttons with LEDs, 1 slider (`slider_0`, value 0..1). |
| `virtual_mini` | `virtual_mini` | 3 x 2 keys (96 px), nothing else. |

Descriptors live in `devices/virtual/models.py` (pure data, positions in layout units, a key is
1 x 1). Add a model by adding a `DeviceModel` to `VIRTUAL_MODELS`: the page renders any layout.

## Protocol

`WebSocket /ws/virtual` (JSON text frames) and `GET /api/virtual/state` (the same `snapshot`).

Server to browser:

| `t` | Fields | When |
| --- | --- | --- |
| `snapshot` | `model` (`DeviceModel.to_dict()`: `layout`, `controls[].position/kind/inputs/outputs`), `images` (control id to base64 PNG), `leds` (id to `[r,g,b]`), `brightness` (0..100), `models` (selectable models) | on connect, and when a client fell behind |
| `image` | `id`, `png` | a key (or strip) was redrawn; unchanged images are not resent |
| `led` | `id`, `rgb` | `set_led` |
| `brightness` | `value` | `set_brightness` |
| `bye` | `reason` | the device is going away (model switch); the socket then closes with 1012 and the browser reconnects |

Close code 1013 means no virtual device is running (the page shows how to start one and retries).

Browser to server: `{"t": "event", "id": "key_0_0", "type": "press|release|rotate|value|touch", "value": ...}`.
Validation (anything else is ignored): the control must exist and have that input; `rotate` is
rounded to whole steps and clamped to +-16 (positive = clockwise/right); `value` is clamped to
0..1; `touch` is `[x, y]` clamped to the control's pixels; a `release` needs a prior `press`.
Controls a closed tab left pressed are released. Several tabs can be open at once.

`POST /api/virtual/model` with `{"model": "virtual_mega"}` switches the running device (409 when
the agent is not running a virtual device, 400 for a non-virtual model).

## The page and the component

`static/virtual.html` mounts `mountVirtualDevice(container, options)` from
`static/js/virtual/device.js`, which any page can import (options: `url`, `modelUrl`, `showStatus`,
`showModelSelector`, `fit` = `viewport` | `container`, `t`, `onEvent`, `onStatus`; it returns
`{destroy, status, snapshot, element}`). Styles: `static/css/virtual.css` (with `tokens.css` and
`components.css`).

* Keys show their image; click or Space/Enter presses; arrow keys move between keys (one Tab stop).
* Knobs: mouse wheel or arrow keys turn, dragging around the dial rotates, a click (or Enter)
  presses, a still hold of 0.4 s is a long press.
* Buttons glow with their LED colour; sliders drag or use arrows, Page Up/Down, Home/End.
* Screen brightness dims the key images. The layout scales to the window (down to 400 px wide).

## Tests

`tests/test_virtual_device.py`: model sanity, the backend over the protocol, input validation, the
registry rules, the WebSocket round trip (Starlette `TestClient`) and a full flow where a press sent
over the WebSocket runs `agent.goto_page` in a real agent and the new page's key images come back.
