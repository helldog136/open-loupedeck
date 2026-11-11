# Changelog

## 0.3.0 (unreleased)

Open-Loupedeck stops being "a Loupedeck app" and becomes a deck app: the same editor, the same
bindings and the same engine drive a Loupedeck, an Elgato Stream Deck (experimental) or a virtual
device in your browser. Everything since 0.2.1:

### Highlights

* **Several devices.** Loupedeck Live and Live S, **Elgato Stream Deck** (Mini, MK.2, XL, +, Neo, Pedal,
  *experimental*) and a **virtual device** (15 keys, Mega, Mini) that needs no hardware.
* **Config v2.** One rule for every control: a setting "for every page" (`global`), overridden by the
  page's own (`pages[].controls`). Controls have model-independent ids (`key_<col>_<row>`, `knob_<n>`,
  `button_<n>`, `strip_<n>`, `pedal_<n>`). Automatic, reversible upgrade, see *Upgrade notes*.
* **A model-driven editor.** The deck picture, the inspector and the starter packs are drawn from the
  device's model, so a Mega deck, a Stream Deck + or a Live S all get a correct editor.
* **World of Warcraft support.** Keys that send a chord for an in-game macro, on-demand WoW icons
  (`wow:<name>`) and a starter pack ([docs/wow.md](docs/wow.md)).

### Architecture

* Device layer: typed controls with positions and capabilities, a `DeviceBackend` protocol, a registry
  (`device.model: auto` tries a Loupedeck first, then a Stream Deck; virtual devices only by name) and
  `ControlEvent`s, with the Loupedeck driver moved behind it ([docs/devices.md](docs/devices.md),
  [docs/devices-features.md](docs/devices-features.md)).
* The runtime dispatches events through bindings on control ids; skin, LEDs, knob feedback and
  brightness work per output the device actually has.
* `GET /api/device_model` and the v2 config in the web API; the editor reads the device from there.

### Stream Deck (experimental)

* Mini (and MK.2 / Discord), Original / V2 / MK.2, XL, +, Neo and Pedal through
  python-elgato-streamdeck: keys, dials, touch strip, Neo touch buttons, pedals, brightness.
* Status chip names the device and says it is experimental; the installers bundle hidapi; Linux udev
  rules in `udev/70-streamdeck.rules` ([docs/streamdeck.md](docs/streamdeck.md)).

### Virtual device

* `open-loupedeck --web --virtual [virtual | virtual_mega | virtual_mini]` or `device.model: virtual...`;
  the page `/assets/ui/virtual.html` draws it, clicks and key presses come back as real events
  ([docs/virtual-device.md](docs/virtual-device.md)).

### Editor

* Model-driven deck: positions, key sizes and captions come from the device; knob feedback keys are
  outlined; drag to swap keys, Ctrl+D duplicates, Delete clears; audio files dropped on an empty key
  make sound keys.
* Inspector: scope bar ("This page / Every page") with the inheritance spelled out, including a
  **summary of what a page inherits** (action and look) with "Override on this page"; the LED colour
  of a button is tagged **Default** (not "Proposed") when untouched.
* Small screens: the deck keeps a tappable size and **pans sideways** instead of shrinking; knob and
  button captions wrap on two lines and show their full name as a tooltip; the duplicate tool is a
  small round button that no longer covers a key's text.
* Starter packs and first-launch welcome card, "Next steps" under the deck, packs fitted to any grid
  (keys that do not fit are dropped with a note); Services hardware choice hint.
* New English/French strings throughout; dead CSS and front-end helpers from the old layouts removed.

### Fixes and smaller changes

* Screen brightness and night mode are now applied through the device backend (any model with an
  adjustable screen).
* Previews and fitted packs use the key size of the model being edited.
* Test and packaging fixes for the optional Stream Deck library.

### Upgrade notes

* **The config migrates automatically on first start.** A v1 config (no `config_version`) is converted
  to v2. Before anything is rewritten, the original file is copied to
  `open-loupedeck-backups/config.yaml.pre-v2` (never rotated or overwritten). To go back, quit the app,
  copy that file over `config.yaml` and reinstall 0.2.x. Your connections (OBS, Home Assistant,
  Spotify, Twitch) and media library are kept.
* Old `legacy_knob_pages` are kept in the file but no longer used at run time.
* A config saved by 0.3 is **not** readable by 0.2.x: restore the `.pre-v2` copy to downgrade.
* No action is needed for Loupedeck owners: keys, buttons, knobs and pages carry over (`touch_N` becomes
  `key_<col>_<row>`, `btn_N` becomes `button_N`, and so on).

### What to check on real hardware

Only the Loupedeck path has been run on a device; the rest follows library documentation.

* **Loupedeck Live S and Live** (regression): every key draws, touches and the 4 / 8 round buttons
  work, the page buttons light and switch pages, knob turns and pushes act and flash their feedback
  on the neighbouring key, brightness and night mode change the screen, a config migrated from 0.2.x
  behaves as before.
* **Stream Deck (all models, experimental):** with the Elgato software closed, the deck is found and the
  status chip says "experimental"; key images are the right way up and size; key presses and
  releases; dials (rotate direction, push) on the +; touch strip taps on the +; Neo touch buttons and
  info screen; Pedal presses; brightness; unplug / replug reconnects; Linux needs the udev rules.
  Please report what works and what does not.
* **Mixed set-ups:** with both a Loupedeck and a Stream Deck connected the Loupedeck wins in `auto`;
  `device.path` with a serial number picks one Stream Deck among several.
* **Editor on a real phone or tablet:** deck panning, tap targets, captions.
* **WoW:** the chords reach the game window and the downloaded icons render on a key.
