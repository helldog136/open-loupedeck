/*
 * state.js — The one shared mutable state object (config being edited, selection, autosave timer…)
 * and a tiny synchronous event bus (on/emit) so lower-level modules never import higher ones.
 *
 * ES module bindings are read-only for importers, so anything more than one module reassigns lives
 * here as a property of `state` (read and write `state.cfg`, `state.pageIndex`, …). State used by a
 * single module stays a module-local `let` in that module.
 *
 * Events in use (emit is synchronous: listeners run before emit() returns):
 *   "control:open" (cid)            — a deck cell was clicked / swapped; main.js opens the editor.
 *   "config:replaced" (prevPageIdx) — cfg/pageIndex were replaced wholesale (undo/redo, restore);
 *                                     main.js re-syncs every view.
 */

export const state = {
  /** The config being edited (GET /api/config), saved back by save.js. */
  cfg: {},
  /** Resolved from GET /api/status when device.model is "auto" ("live" | "live_s" | null). */
  agentDeckLayout: null,
  /** GET /api/action_catalog → actions[]. */
  actionCatalog: [],
  /** Index into cfg.pages of the page shown in the editor. */
  pageIndex: 0,
  /** Control id open in the key editor (never a knob id), or null. */
  selectedControl: null,
  /** @type {string | null} Knob id open in the encoder editor, or null. */
  selectedKnobEncoder: null,
  /** touch_{n} -> error string for current page (from /api/status). */
  touchErrors: {},
  /** Clipboard for copy/paste between controls (entry JSON). */
  copiedControlEntry: null,
  copiedControlMeta: null,
  /** When advanced JSON matches this (after trim), Apply uses the form instead of the textarea. */
  lastSyncedAdv: "",
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
