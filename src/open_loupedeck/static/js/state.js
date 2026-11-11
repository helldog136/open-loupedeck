/*
 * state.js — The one shared mutable state object (config being edited, edited device model, selection,
 * autosave timer…) and a tiny synchronous event bus (on/emit) so lower-level modules never import
 * higher ones.
 *
 * ES module bindings are read-only for importers, so anything more than one module reassigns lives
 * here as a property of `state` (read and write `state.cfg`, `state.pageIndex`, …). State used by a
 * single module stays a module-local `let` in that module.
 *
 * Events in use (emit is synchronous: listeners run before emit() returns):
 *   "control:open" (cid)            — a control was picked on the deck; the inspector opens it.
 *   "config:replaced" (prevPageIdx) — cfg/pageIndex were replaced wholesale (undo/redo, restore);
 *                                     main.js re-syncs every view.
 *   "model:changed"                 — the edited device model changed (device plugged, model select).
 *   "inspector:sync"                — selection or page changed elsewhere; the inspector follows.
 *   "inspector:reopen"              — rebuild the open control (its edit scope changed).
 *   "status:updated" (json)         — the /api/status poll result.
 */

export const state = {
  /** The config being edited, `config_version: 2` (GET/PUT /api/config?format=v2). */
  cfg: {},
  /** GET /api/device_model payload: { source, connected, models: {id: model}, model, config_model }. */
  deviceInfo: null,
  /** The device model the editor lays out (DeviceModel.to_dict()); see model.js resolveEditorModel(). */
  model: null,
  /** GET /api/action_catalog → actions[]. */
  actionCatalog: [],
  /** Index into cfg.pages of the page shown in the editor. */
  pageIndex: 0,
  /** Control id open in the inspector (any kind), or null. */
  selectedControl: null,
  /** Control id -> "page" | "global": the scope the inspector edits, chosen by the user (session only). */
  editScopes: new Map(),
  /** Control id -> render error of its binding on the page shown (from /api/status control_errors). */
  controlErrors: {},
  /** Clipboard for copy/paste between controls (entry JSON). */
  copiedControlEntry: null,
  copiedControlMeta: null,
  /** False until initial load finishes, so we do not PUT empty/partial state. */
  suppressAutosave: true,
  autosaveTimer: null,
};

/** Tiny synchronous event bus: lets a lower-level module ask for work owned by a higher one. */
const eventListeners = new Map();

export function on(name, fn) {
  if (!eventListeners.has(name)) eventListeners.set(name, []);
  eventListeners.get(name).push(fn);
}

export function emit(name, ...args) {
  for (const fn of eventListeners.get(name) || []) fn(...args);
}
