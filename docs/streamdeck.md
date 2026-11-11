# Elgato Stream Deck (experimental)

Open-Loupedeck can drive an Elgato Stream Deck through
[python-elgato-streamdeck](https://github.com/abcminiuser/python-elgato-streamdeck) (MIT), installed
with the app. **This backend has not been tested on real hardware yet**: everything below follows
the library's code and documentation. The status chip and the log say so whenever a Stream Deck is
opened. Reports (it works / it does not) are very welcome, see the end of this page.

## Supported models

| Model | `device.model` | Controls (config ids) | Key image |
| --- | --- | --- | --- |
| Stream Deck Mini (and Mini MK.2, Discord edition) | `streamdeck_mini` | 3 x 2 keys `key_0_0`..`key_2_1` | 80 x 80 |
| Stream Deck Original, Original V2, MK.2 | `streamdeck_mk2` (`streamdeck_original`) | 5 x 3 keys | 72 x 72 |
| Stream Deck XL (and XL V2) | `streamdeck_xl` | 8 x 4 keys | 96 x 96 |
| Stream Deck + | `streamdeck_plus` | 4 x 2 keys, touch strip `strip_0` (800 x 100, touch + image), push dials `knob_0`..`knob_3` | 120 x 120 |
| Stream Deck Neo | `streamdeck_neo` | 4 x 2 keys, touch buttons `button_0` / `button_1` (RGB LED), info screen `strip_0` (248 x 58, image only) | 96 x 96 |
| Stream Deck Pedal | `streamdeck_pedal` | pedals `pedal_0`..`pedal_2` (press only, no display, no brightness) | none |

* `device.model: auto` (default) tries a Loupedeck first, then a Stream Deck: a connected
  Loupedeck always wins. `device.model: streamdeck` opens whichever Stream Deck is attached (its key
  coordinates refer to the 5 x 3 grid); a model name prefers that model when several decks are
  attached.
* `device.path` selects one deck when several are attached: its HID path (shown in the status chip
  and the log) or its **serial number** (stable across USB ports). A serial-port path (`/dev/tty*`,
  `COM5`) is a Loupedeck path and never selects a Stream Deck.
* Key ids follow the usual scheme: `key_<col>_<row>`, top-left = `key_0_0` (the library numbers the
  keys row by row from the top-left; the backend maps them).
* Image sizes come from the library when the deck is opened (the table shows the documented ones);
  the library applies each model's rotation / mirroring and encoding (BMP or JPEG).
* Dials: turning gives `rotate` (+n = clockwise, as the library reports it), pushing gives
  `press` / `release`. Feedback about a dial is drawn on the key above it.
* Touch strip: taps and drags become `touch` events with the strip pixel coordinates (a drag reports
  where it started). Nothing is bound to strip touches yet (same as on the Loupedeck Live).
* The Stream Deck Studio and Stream Deck + XL are recognised by the library but not supported yet;
  they are skipped with a log line.

## Before you start

* **Quit the Elgato Stream Deck software.** The device can only be opened by one program at a time;
  while the Elgato app runs, Open-Loupedeck reports "a Stream Deck is attached but could not be
  opened" and keeps retrying every 2 seconds.
* **hidapi.** The library talks to the deck through the native hidapi library. The installers bundle
  it; from source install it yourself: Windows `hidapi.dll` next to `python.exe` or on `PATH`
  ([libusb/hidapi releases](https://github.com/libusb/hidapi/releases)), macOS `brew install hidapi`,
  Debian / Ubuntu `sudo apt install libhidapi-libusb0`, Fedora `sudo dnf install hidapi`. Without it
  the Stream Deck backend is simply skipped (debug log), the Loupedeck backend is unaffected.
* **Linux permissions.** Install the udev rules, then unplug and replug the deck:

  ```bash
  sudo cp udev/70-streamdeck.rules /etc/udev/rules.d/
  sudo udevadm control --reload-rules && sudo udevadm trigger
  ```

  The rules give the logged-in user access (`uaccess`) and the `plugdev` group.

## How it works

`src/open_loupedeck/devices/streamdeck/`: `models.py` holds the descriptors (pure data), `backend.py`
the `DeviceBackend` (see `docs/devices.md`). The library is imported only when a Stream Deck is
looked for, so the app starts without it. Input arrives on the library's reader thread and is
handed to the agent as `ControlEvent`s; a watchdog checks once a second that the deck is still open
and connected and signals the unplug, after which the agent's reconnect loop opens it again. On
shutdown the deck is reset to the Elgato standby screen.

## Not verified yet (needs a real deck)

* Every key draws in the right place and the right way up on every model (rotation / mirroring).
* Key presses map to the right `key_<col>_<row>` (library order), Neo touch buttons to `button_0`
  (left) / `button_1` (right), pedals left to right.
* Dial direction (clockwise = positive) and push; touch strip coordinates and drag behaviour.
* Touch strip and Neo info screen images; Neo touch button LEDs (`set_key_color` index 8 / 9).
* Brightness on every model; unplug and replug (reconnect within a few seconds); two decks with
  `device.path`; behaviour while the Elgato software runs.
* The bundled hidapi in the Windows / macOS / Linux packages.

## Reporting problems

Open an issue with: the model (and the `deck_type` / serial shown in the log), the OS, the app
version, what you did and what happened, and the log file with `-v` (verbose) if possible. A photo
of a wrongly drawn deck helps a lot.
