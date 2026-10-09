# Knob model: roles per deck page

Knobs (encoders) have **no pages of their own and no screen**. What a knob does depends on the **deck page being
shown**: volume on page 1, microphone on page 3, nothing on page 4... For each deck page, each knob has:

- **`rotate`**: one *linked* setting, a **duo**, whose left / right rotation are its − / + directions (system volume
  −5 / +5, Spotify previous / next track, previous / next OBS scene...). *Advanced:* "split left and right" stores two
  free actions instead.
- **`press`**: an independent, optional action.

A knob without a role on the page shown does nothing (the default). After a turn or a push, a short text
("Volume +5", "Next track") is drawn on the **touch key next to the knob** and the key comes back after
`knob_page_feedback.duration_sec` (0–2 s, 0 = no feedback; default 2 s), or the per-knob `feedback_sec`.

Code: `src/open_loupedeck/knob_roles.py` (schema, resolution, migration), `knob_duos.py` (catalogue),
`knob_flash.py` (feedback drawing), `app.py` (`run_knob_role` in the encoder handler).

## Schema

On each entry of `pages`, an optional `knobs` mapping keyed by knob id:

```yaml
knob_page_feedback:
  duration_sec: 1.5            # global feedback duration, 0–2 s (0 = off)

pages:
  - name: Main
    buttons: { ... }
    knobs:
      knobTL:
        rotate: { duo: system_volume, params: { step: 5 } }
        press: { type: sound.mute_toggle }
      knobCL:
        rotate: { duo: obs_input_volume, params: { input_name: "Mic/Aux", step: 2 } }
  - name: Music
    buttons: { ... }
    knobs:
      knobTL:
        rotate: { duo: spotify_track }
        press: { type: spotify.play_pause }
        feedback_sec: 0.5      # optional per-knob override of the duration
      knobCL:
        rotate:                # advanced: split left and right (two free actions)
          left: { type: agent.prev_page }
          right: [ { type: spotify.next }, { type: sound.volume_delta, delta: 1 } ]
        press: null
  - name: Empty                # no knobs: both knobs do nothing on this page
    buttons: { ... }
```

| Field | Type | Notes |
|---|---|---|
| `knobs` | mapping | Keys: `knobTL`, `knobCL` (Live S), plus `knobBL`, `knobTR`, `knobCR`, `knobBR` (Live). Other keys are rejected. `null` entry = no role. |
| `rotate` | mapping or absent | Either `{duo, params}` or `{left, right}`, never both. |
| `rotate.duo` | string | A duo id from the catalogue (`GET /api/knob_duos`). Unknown ids are rejected. |
| `rotate.params` | mapping | Duo params (see catalogue). Numbers are clamped to the duo's range; a required param left empty is accepted (the UI autosaves while typing) and the knob then only shows "<duo>: needs setup". |
| `rotate.left` / `rotate.right` | action, list of actions, or `null` | Same action objects as `pages[].buttons[].action`. |
| `press` | action, list of actions, or `null` | Independent of the rotation. |
| `feedback_sec` | number 0–2 | Optional; overrides `knob_page_feedback.duration_sec` for this knob on this page. |

Unknown extra keys inside a knob entry are tolerated (kept as-is). `PUT /api/config` runs `validate_knobs_config`
after the migration and answers **400** with the list of problems (`error.invalid_knobs`) when the shape is wrong
(non-object `knobs`, unknown knob id, unknown duo, duo + left/right together, non-numeric number param, action
without `type`, `feedback_sec` outside 0–2).

## Duo catalogue (`knob_duos.py`, `GET /api/knob_duos`)

A duo is data: `id`, `category` (reuses the catalog's `category.<slug>` keys), a params schema and two action
templates built from existing action types. Only `{duo, params}` is stored; actions are expanded at run time.

| id | category | left / right | params |
|---|---|---|---|
| `system_volume` | sound | `sound.volume_delta` −step / +step | `step` (5, 1–25) |
| `obs_input_volume` | obs | `obs.input_volume_delta` −step / +step | `input_name` (required), `step` (5, 1–25) |
| `obs_scene` | obs | `obs.scene_step` −1 / +1 (wraps, Scenes dock order) | — |
| `ha_light_brightness` | home_assistant | `ha.call_service light.turn_on` `brightness_step_pct` −step / +step | `entity_id` (required), `step` (10, 1–50) |
| `spotify_volume` | spotify | `spotify.volume_delta` −step / +step | `step` (5, 1–25) |
| `spotify_track` | spotify | `spotify.previous` / `spotify.next` | — |
| `deck_page` | deck | `agent.prev_page` / `agent.next_page` | — |
| `keyboard_up_down` | keyboard | `keyboard.play_sequence` ↑ / ↓ | — |
| `keyboard_page_up_down` | keyboard | `keyboard.play_sequence` Page Up / Page Down | — |
| `keyboard_left_right` | keyboard | `keyboard.play_sequence` ← / → | — |

`obs.scene_step` is a new built-in action (`step: -1|1`, optional `wrap: false`) added for the OBS scene duo.

`GET /api/knob_duos?lang=fr` returns `{lang, duos: [...]}`; each duo has `id`, `label`, `category`, `left_label`,
`right_label` (with default params filled in), `params` (`name`, `kind` number|text, `label`, `default`,
`required`, `min`, `max`), the raw `left` / `right` templates (`{"param": "step", "sign": -1}` marks a
placeholder), and the `*_key` of every translated text.

Locale keys: `knob.duo.<id>.label`, `knob.duo.<id>.left|right` (feedback text; every param is a `{placeholder}`,
e.g. `"Volume +{step}"`), `knob.duo.param.<name>.label`, `knob.feedback.needs_setup`, `knob.feedback.failed`,
`error.invalid_knobs`. They live outside the `action.` / `look.` / `category.` families so
`scripts/check_catalog_keys.py` does not report them as stray.

## Runtime

On an encoder event (`rotate` left/right or `push` down) the agent:

1. takes the **current deck page** (`state.page_index`, wrapped like the deck) and its `knobs.<id>`;
2. no entry / no rotate / no press → nothing happens (debug log only);
3. `rotate.duo` → `expand_duo(...)`; `rotate.left|right` / `press` → the actions as written;
4. runs them with `run_actions` (same context as keys: OBS, HA, Spotify, page navigation...);
5. draws the feedback on the neighbouring key: duo → `knob.duo.<id>.left|right`; free action → the catalog name of
   its first action (`action.<type>.label`); if an action failed, `knob.feedback.failed` wraps the text.

Rapid turns redraw the text and only the latest flash restores the key, so it does not flicker while turning.
Simulated events (`POST /api/simulate_press` with `control_id: knobTL` and `direction: left|right`, or no direction
for a push) take the same path.

### Which touch key is "next to" a knob

`knob_pages.feedback_touch_key_for_knob_page_name(knob_id, model)` (wrapped by `knob_roles.feedback_touch_key`).
The model is `device.model`; when it is `auto`, `knob_roles.effective_model` reads it from the opened driver class
(`LoupedeckLiveS` → `live_s`, `LoupedeckLive` → `live`), and an unknown model falls back to the Live S layout.

| Model | Touch grid | Knob → key |
|---|---|---|
| `live_s` (and fallback) | 5×3, `touch_0..14` row by row | `knobTL` → `touch_0` (top-left), `knobCL` → `touch_5` (middle-left); other ids: no feedback |
| `live` | 4×3, `touch_0..11` | left column: `knobTL` → `touch_0`, `knobCL` → `touch_4`, `knobBL` → `touch_8`; right column: `knobTR` → `touch_3`, `knobCR` → `touch_7`, `knobBR` → `touch_11` |

## Migration from `knob_pages`

The legacy model was a top-level `knob_pages: {<knob>: {pages: [{name, rotate_left, rotate_right}, ...]}}`: push
cycled the knob's own pages, rotation ran the current knob page's actions, the page name flashed on the neighbouring
key. `ensure_minimal_structure` (every load, `PUT /api/config`, reset/restore) runs
`knob_roles.migrate_legacy_knob_pages`:

- For each knob with legacy pages, the **first** knob page's rotation becomes that knob's `rotate` role on **every
  deck page that has no role for that knob yet** (existing roles are never overwritten). When the left/right actions
  are exactly a duo's expansion they become `{duo, params}` (e.g. `sound.volume_delta` −2/+2 →
  `{duo: system_volume, params: {step: 2}}`), otherwise a split `{left: [...], right: [...]}` with the actions verbatim.
  No `press` is created (the old push only cycled pages).
- The legacy data is kept verbatim under **`legacy_knob_pages`** (nothing is lost; the other knob pages can be
  re-created by hand from it). A differing entry already stored for the same knob is never overwritten: the new one
  goes to `<knob>_2`, `<knob>_3`... A malformed (non-mapping) `knob_pages` is kept under `legacy_knob_pages._unparsed`.
- `knob_pages` is removed (an empty one is just dropped), so the migration is **idempotent**.
- `knob_page_feedback.duration_sec` stays and is now the global feedback duration.
- **Config without deck pages** (old `bindings`-only setups, model `auto`): nothing to attach roles to, so `knob_pages`
  is left untouched and the legacy runtime (push cycles knob pages, rotation runs their actions) keeps working.

Example (`config.example.yaml` before this change): `knobTL` "Volume" (±2) + "Deck page", `knobCL` "Scroll"
(`command.run` xdotool) become, on every page, `knobTL: {rotate: {duo: system_volume, params: {step: 2}}}` and
`knobCL: {rotate: {left: [command.run click 4], right: [command.run click 5]}}`; the "Deck page" knob page is only in
`legacy_knob_pages`.
