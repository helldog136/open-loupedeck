# UI redesign — brief for every work package

`mockup.html` (open it in a browser) is the validated target for the **Buttons** screen. It is French
and static; the real app is bilingual (see *Languages*). The mockup is a reference for layout, flow and
behaviour, not code to copy.

## Principles
1. **The button is the hero.** The deck mirrors the real device, drawn from its model (the connected device,
   else `device.model`, else the Live S: 5x3 touch screen, 2 knobs, 4 round LED buttons) and every key shows
   its real, final look.
2. **Three steps:** pick the key → pick what it does → how it looks. Everything else is under *Advanced*.
3. **Smart defaults.** Choosing an action immediately gives the key a proposed look (icon, colours, label,
   content mode). A field the user touches becomes *modified* (tag + "reset") and stops following the action;
   untouched fields keep following it (including when the action or the language changes).
4. **Apply live, save on every change, with Undo.** No "Apply" button.
5. **Status chips are actionable** (OBS offline → "Connect"), never decorative.
6. **Plain language.** No "strips", "indices", "URI" in the UI.
7. **Dark theme only**, accent amber, font Hanken Grotesk (UI) + JetBrains Mono (small technical labels).

## Model decisions (do not re-litigate)
- Four pages always exist, renamable, not deletable. A page is opened by the button whose global binding is
  "go to page N" (by default the Live S round buttons open pages 1-4); the tab's dot shows that button's LED
  colour. Extra pages are opened with the "go to page" action.
- **One rule for every control** (`docs/devices-features.md`): a binding for every page, overridden by the
  page's own. The inspector's scope bar ("This page / Every page") says which one applies and offers
  "Override on this page", "Edit the one for every page", "Remove this page's own setting".
- Keys have a **content mode**: `text`, `icon` or `both`. Text must be big (aplats of colour, large white text).
- **Live keys** (current OBS scene, clock…) have an *online* and an *offline* look; the offline fallback is
  configurable: dash (default), nothing, last value.
- **Knobs have no screen.** Feedback after a turn is drawn briefly on the neighbouring touch key (already what
  `knob_flash.py` does). A knob has **no pages of its own**: its role depends on the deck page being shown
  (volume on page 1, mic on page 3…), or is the same on every page (its global binding). Left/right rotation are **one linked setting** (a "duo": Volume −/+,
  Music prev/next…); only the push is an independent action. Advanced: "split left and right".
- Text overflow is detected server-side and warned about in the editor.

## Languages
English is the source language, French the first translation. Strings live in
`src/open_loupedeck/locales/<code>.json` (flat keys, e.g. `inspector.step1.title`); adding a language is a
PR that copies `en.json`. **No hard-coded user-visible strings in new code**: use `t("key")` (JS) /
`t("key")` (Python). Default looks store **keys**, not text, so an untouched key changes language with the app;
text typed by the user is never translated.

## Rules for every work package
- Work only on your branch (`dev-<slug>`), in your worktree. Stay inside your declared files; if you must touch
  another area, keep the change minimal and say so in your final report.
- `ruff format`, `ruff check src tests` and `pytest` must pass. Add tests for Python logic.
- Never run against the user's real config (`%APPDATA%\open-loupedeck\config.yaml`). Use
  `python -m open_loupedeck --config <scratch dir>/config.yaml --web 127.0.0.1:<port> --no-device`.
- UI changes: take at least one Playwright screenshot (Chromium is at
  `/opt/pw-browsers/chromium-1243/chrome-linux64/chrome`) and check there are no console errors.
- Commit messages end with the `Co-Authored-By` line given in the session's attribution reminder.
- Do not push, do not open PRs, do not touch `master`. Final report: what changed, files, how verified, open
  issues.

## Front-end layout
The config UI is plain native ES modules under `src/open_loupedeck/static/js/` — no bundler, no npm, no build
step. `index.html` loads the classic `i18n.js` (defines the global `t()` / `i18n`) and then
`<script type="module" src="/assets/ui/js/main.js">`; the browser fetches the rest through `import`s. FastAPI serves
`static/` at `/assets/ui` (with `.js` pinned to `text/javascript`, required for modules) and PyInstaller bundles the
whole `static/` tree, so a new file needs no registration anywhere. Every module starts with a comment saying what
it owns.

| File | Owns |
| --- | --- |
| `main.js` | Entry point: boot sequence (order matters), reactions to `config:replaced` and `model:changed` |
| `state.js` | The shared `state` object (`state.cfg`, `state.model`, `state.pageIndex`, `state.selectedControl`, …) and `on`/`emit` |
| `constants.js`, `util.js` | File-extension sets; stateless helpers (`$`, escaping, colours, media paths) |
| `api.js` | Shared fetch wrappers (config GET/PUT in the stored v2 shape, page index, simulate press, upload, skin refresh) |
| `model.js` | Without DOM: the edited device model (`/api/device_model`), control capabilities and names, pages, the bindings (`global` + `pages[].controls`, page binding else global) and the scope edited per control |
| `device-layout.js` | Geometry shared with the virtual device: bezel, key bed, visual order, unit fitting |
| `save.js`, `undo.js`, `forms.js` | Debounced autosave + save status; undo/redo snapshots; validated "smart" fields |
| `shell.js`, `status.js` | Tab bar; status pills and the 1.5 s `/api/status` poll (device changes reload the model) |
| `pages.js`, `page-field.js` | Page tabs (dot = the button opening the page), page ↔ agent `page_index` sync; the "Go to page" page list |
| `deck.js` | Deck picture (`#deckRoot`) from the model's positions: key previews, captions, selection, knob feedback outline, drag-swap / duplicate / delete; a click emits `control:open` |
| `inspector/index.js` | Inspector panel: empty state, routing by capability (`controls.js`), `registerInspectorView(name, {render, destroy, refresh?})` |
| `inspector/key-view.js` | A control with a press: header (copy / paste / clear), scope bar, action step, Appearance (image output), Light (LED output), Advanced |
| `inspector/scope.js`, `inspector/light.js` | "This page / Every page" with the inheritance state; the LED colour step |
| `inspector/appearance.js`, `inspector/advanced.js` | Appearance (live preview, proposed / modified fields, live pair, overflow); Advanced (animations, gradients, font, layout, JSON, test press) |
| `inspector/entry.js`, `inspector/edit.js` | Stored-config contract (which keys make a field "modified"); the single edit path (scope, Undo snapshot, save, device refresh) |
| `inspector/preview.js`, `inspector/controls.js`, `inspector/dom.js` | `/api/preview_key` + `/api/resolve_look` clients, animations; view per capability and names; small DOM helpers |
| `inspector/clipboard.js` | Copy / paste (same binding shape only) / clear |
| `catalog.js`, `action-fields.js`, `key-sequence.js` | Catalog lookups and short action names; catalog-driven parameter forms; key recorder |
| `inspector/knob-view.js` | Knob inspector: role per deck page (duo list, press action, display time, test buttons, split / JSON), knob captions for the deck |
| `services/*.js` | One per Services section: `backups`, `device` (hardware model), `spotify`, `twitch`, `obs`, `ha`, `logging`, `system` |

Rules: imports only point "down" (no import cycles); when a lower module needs something a higher one owns it
calls `emit("…")` and `main.js` subscribes with `on("…")` (synchronous). A variable that more than one module
reassigns goes on `state`; anything else stays module-local. `tests/test_web_static.py` checks every module is
served as JavaScript and every relative import resolves.

Smoke tests (start a scratch instance first; they edit and undo, `ui_models_check.py` also changes
`device.model` and puts it back):

```
python scripts/ui_smoke.py http://127.0.0.1:8775            # [--chromium PATH] [--ignore-external] [--headed]
python scripts/ui_models_check.py http://127.0.0.1:8775     # [--chromium PATH] [--headed]
```

It loads the page, fails on any console error, uncaught page error or failed request (the browser's automatic
`/favicon.ico` request excepted; `--ignore-external` also tolerates other origins such as web fonts when offline),
clicks both tabs, selects `key_0_0`, picks an action in the inspector's action picker, presses Ctrl+Z, checks the saved config is
unchanged and prints `OK` (exit code 0) or `FAILED` with the reasons (exit code 1).

`ui_models_check.py` does, for `virtual_mini`, `virtual_15` and `virtual_mega` (picked in Services > General):
every control of the model is drawn; a key gets an action on the page, a knob a role, a button an action on
every page (checked in the stored config); page switch; Undo restores the config; no console error.
