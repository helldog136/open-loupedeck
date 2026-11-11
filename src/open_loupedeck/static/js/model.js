/*
 * model.js — The edited device model and the config's bindings, without DOM.
 *
 * Device model: GET /api/device_model gives every known model (DeviceModel.to_dict()). The editor lays
 * out the connected device if there is one, else the config's `device.model`, else the Live S
 * (resolveEditorModel). Controls are addressed by their model-independent id (`key_<col>_<row>`,
 * `knob_<n>`, `button_<n>`, `slider_<n>`, `strip_<n>`, `pedal_<n>`).
 *
 * Bindings (config_version 2, docs/devices-features.md): `global` (control id -> binding, every page)
 * and `pages[i].controls` (control id -> binding that overrides the global one on that page). One rule
 * for every control: the page binding if there is one, else the global one (resolvedBinding).
 *
 * The inspector edits one scope per control ("page" or "global"): the user's choice for this session,
 * else defaultScope(). getEntry / setEntry read and write the entry in that scope.
 */

import { state } from "./state.js";
import { keyCoord } from "./device-layout.js";

/** At least this many pages always exist (renamable, not deletable). */
export const MIN_PAGES = 4;
/** Model laid out when nothing else says (the server's default model). */
const FALLBACK_MODEL = "loupedeck_live_s";

/* ---- device model ------------------------------------------------------------------------------ */

/** Every known model, in the server's order. */
export function knownModels() {
  const info = state.deviceInfo;
  if (!info || !info.models) return [];
  const order = Array.isArray(info.known_models) ? info.known_models : Object.keys(info.models);
  return order.map((id) => info.models[id]).filter(Boolean);
}

/** The model a `device.model` value names (its id or one of its config names), else null. */
export function findModel(name) {
  const n = String(name || "").trim().toLowerCase();
  if (!n || n === "auto") return null;
  return knownModels().find((m) => m.id === n || (m.config_names || []).includes(n)) || null;
}

/** The connected device's model, or null. */
export function connectedModel() {
  const info = state.deviceInfo;
  return info && info.source === "device" && info.model ? info.model : null;
}

/** Connected device, else the config's device.model, else the default model. Sets state.model; true if it changed. */
export function resolveEditorModel() {
  const prev = state.model && state.model.id;
  const info = state.deviceInfo || {};
  const configured = state.cfg && state.cfg.device ? state.cfg.device.model : "auto";
  state.model =
    connectedModel() ||
    findModel(configured) ||
    (info.models && (info.models[info.config_model] || info.models[FALLBACK_MODEL])) ||
    knownModels()[0] ||
    null;
  return (state.model && state.model.id) !== prev;
}

/** Fetch GET /api/device_model into state.deviceInfo and re-resolve the edited model (true if it changed). */
export async function loadDeviceModels() {
  try {
    const r = await fetch("/api/device_model");
    if (r.ok) state.deviceInfo = await r.json();
  } catch {
    /* keep what we had */
  }
  return resolveEditorModel();
}

export function modelControls() {
  return (state.model && state.model.controls) || [];
}

export function control(cid) {
  return modelControls().find((c) => c.id === cid) || null;
}

/** Kind of a control id ("key", "knob", "button", "slider", "strip", "pedal"), from the id itself. */
export function kindOf(cid) {
  const s = String(cid || "");
  if (keyCoord(s)) return "key";
  const m = /^(button|knob|slider|strip|pedal)_\d+$/.exec(s);
  return m ? m[1] : null;
}

/** Zero-based number of an indexed id (`knob_2` -> 2). */
export function indexOf(cid) {
  const m = /_(\d+)$/.exec(String(cid || ""));
  return m ? Number(m[1]) : 0;
}

export function hasInput(cid, input) {
  const c = control(cid);
  return !!c && (c.inputs || []).includes(input);
}

export function hasImage(cid) {
  const c = control(cid);
  return !!(c && c.outputs && c.outputs.image);
}

export function hasLed(cid) {
  const c = control(cid);
  return !!(c && c.outputs && c.outputs.led);
}

/** Default LED colour of a control as "#rrggbb" (what the device shows without `button_color`). */
export function defaultLedHex(cid) {
  const c = control(cid);
  const rgb = c && c.outputs && c.outputs.led && c.outputs.led.default;
  if (!Array.isArray(rgb) || rgb.length !== 3) return "#202028";
  return `#${rgb.map((v) => Math.max(0, Math.min(255, Number(v) || 0)).toString(16).padStart(2, "0")).join("")}`;
}

/** Display keys of the edited model, row by row. */
export function keyIds() {
  return modelControls()
    .filter((c) => c.kind === "key")
    .map((c) => c.id)
    .sort((a, b) => {
      const [ca, ra] = keyCoord(a);
      const [cb, rb] = keyCoord(b);
      return ra - rb || ca - cb;
    });
}

/** { cols, rows } of the key grid. */
export function keyGrid() {
  const g = state.model && state.model.grid;
  return { cols: (g && g.cols) || 0, rows: (g && g.rows) || 0 };
}

/** 1-based number of a key, row by row (what the user calls "key 7"). */
export function keyNumber(cid) {
  const at = keyCoord(cid);
  return at ? at[1] * Math.max(1, keyGrid().cols) + at[0] + 1 : 0;
}

/** Plain-language name of a control ("Key 7", "Knob 2", "Left strip"), the inspector's title. */
export function controlLabel(cid) {
  const c = control(cid);
  const kind = c ? c.kind : kindOf(cid);
  if (kind === "key") return t("inspector.name.key", { number: keyNumber(cid) });
  if (kind === "strip") {
    const strips = modelControls().filter((x) => x.kind === "strip");
    if (strips.length === 2) return t(indexOf(cid) === 0 ? "inspector.name.strip_left" : "inspector.name.strip_right");
  }
  const known = ["knob", "button", "slider", "strip", "pedal"];
  return known.includes(kind) ? t(`inspector.name.${kind}`, { number: indexOf(cid) + 1 }) : String(cid || "");
}

/** Display control showing feedback about a knob (or button), or null. */
export function feedbackKeyFor(cid) {
  const fk = state.model && state.model.feedback_keys;
  return (fk && fk[cid]) || null;
}

/* ---- pages ------------------------------------------------------------------------------------- */

function defaultPageName(n) {
  return t("pages.default_name", { number: n });
}

export function ensurePages() {
  if (!Array.isArray(state.cfg.pages)) state.cfg.pages = [];
  const pages = state.cfg.pages;
  while (pages.length < MIN_PAGES) pages.push({ name: defaultPageName(pages.length + 1), controls: {} });
  pages.forEach((p, i) => {
    if (!p || typeof p !== "object" || Array.isArray(p)) pages[i] = { name: defaultPageName(i + 1), controls: {} };
    else {
      if (!p.name) p.name = defaultPageName(i + 1);
      if (!p.controls || typeof p.controls !== "object" || Array.isArray(p.controls)) p.controls = {};
    }
  });
  if (state.pageIndex >= pages.length) state.pageIndex = Math.max(0, pages.length - 1);
}

export function ensureDevice() {
  if (!state.cfg.device || typeof state.cfg.device !== "object") state.cfg.device = { path: "", baudrate: null, model: "auto" };
  if (state.cfg.device.model == null) state.cfg.device.model = "auto";
}

export function ensureGlobal() {
  if (!state.cfg.global || typeof state.cfg.global !== "object" || Array.isArray(state.cfg.global)) state.cfg.global = {};
}

export function currentPage() {
  ensurePages();
  return state.cfg.pages[state.pageIndex];
}

export function pageName(i) {
  const p = state.cfg.pages && state.cfg.pages[i];
  return (p && p.name) || defaultPageName(i + 1);
}

export function clampPageIndex(agentIndex) {
  ensurePages();
  const n = state.cfg.pages.length;
  if (n === 0) return 0;
  if (typeof agentIndex !== "number" || !Number.isFinite(agentIndex)) return state.pageIndex;
  return ((Math.floor(agentIndex) % n) + n) % n;
}

/* ---- bindings ---------------------------------------------------------------------------------- */

const isMap = (v) => !!v && typeof v === "object" && !Array.isArray(v);

/** The page's own binding of `cid` (null when it has none). */
export function pageEntry(cid, pageIndex = state.pageIndex) {
  const p = state.cfg.pages && state.cfg.pages[pageIndex];
  const e = p && isMap(p.controls) ? p.controls[cid] : null;
  return isMap(e) ? e : null;
}

/** The global binding of `cid` (null when it has none). */
export function globalEntry(cid) {
  const e = isMap(state.cfg.global) ? state.cfg.global[cid] : null;
  return isMap(e) ? e : null;
}

/** The one rule: { entry, scope } of the page binding, else of the global one; null when unbound. */
export function resolvedBinding(cid, pageIndex = state.pageIndex) {
  const p = pageEntry(cid, pageIndex);
  if (p) return { entry: p, scope: "page" };
  const g = globalEntry(cid);
  return g ? { entry: g, scope: "global" } : null;
}

/** What the device shows / does for `cid` on the page shown (resolved entry), or null. */
export function displayEntry(cid, pageIndex = state.pageIndex) {
  const b = resolvedBinding(cid, pageIndex);
  return b ? b.entry : null;
}

/**
 * Scope the inspector edits when the user has not chosen: keys are page-bound; other controls edit
 * where their binding resolves today (a page override, else the global one); unbound knobs default to
 * the page (their role follows the page), other unbound controls to every page.
 */
export function defaultScope(cid) {
  const kind = kindOf(cid);
  if (kind === "key") return "page";
  const b = resolvedBinding(cid);
  if (b) return b.scope;
  return kind === "knob" ? "page" : "global";
}

export function editScope(cid) {
  return state.editScopes.get(cid) || defaultScope(cid);
}

export function setEditScope(cid, scope) {
  if (scope === "page" || scope === "global") state.editScopes.set(cid, scope);
}

/** Entry of `cid` in `scope` (default: the edited scope), or null. */
export function getEntry(cid, scope = editScope(cid)) {
  return scope === "global" ? globalEntry(cid) : pageEntry(cid);
}

/** Store (or remove, with null) the entry of `cid` in `scope` (default: the edited scope). */
export function setEntry(cid, entry, scope = editScope(cid)) {
  if (scope === "global") {
    ensureGlobal();
    if (entry == null) delete state.cfg.global[cid];
    else state.cfg.global[cid] = entry;
    return;
  }
  const p = currentPage();
  if (entry == null) delete p.controls[cid];
  else p.controls[cid] = entry;
}

/** Pages (indexes) whose own binding overrides the global one of `cid`. */
export function overridingPages(cid) {
  return (state.cfg.pages || []).map((_, i) => i).filter((i) => pageEntry(cid, i));
}

/** The actions of a key / button binding (a non-empty `actions` list, else `action`). */
export function entryActions(e) {
  if (!isMap(e)) return [];
  if (Array.isArray(e.actions) && e.actions.length) return e.actions.filter(isMap);
  return isMap(e.action) ? [e.action] : [];
}

/** Page index a binding opens (`agent.goto_page` with an `index`), else null. */
export function gotoPageIndex(e) {
  const acts = entryActions(e);
  if (acts.length !== 1 || acts[0].type !== "agent.goto_page") return null;
  const n = Number(acts[0].index);
  return Number.isInteger(n) && n >= 0 ? n : null;
}

/** The button (of the edited model) whose global binding opens page `i`: { cid, color } or null. */
export function pageButton(i) {
  for (const c of modelControls()) {
    if (c.kind !== "button") continue;
    const g = globalEntry(c.id);
    if (g && gotoPageIndex(g) === i) {
      const raw = g.button_color && String(g.button_color).trim();
      return { cid: c.id, color: raw || null };
    }
  }
  return null;
}

/* ---- capabilities used by the inspector -------------------------------------------------------- */

/** The test-press button can fire this control (it has a press or a rotation). */
export function controlCanSimulate(cid) {
  return hasInput(cid, "press") || hasInput(cid, "rotate");
}

/** Shape of a binding: "knob" (rotate + press role) or "action" (keys, buttons, pedals, strips). */
export function bindingShape(cid) {
  return hasInput(cid, "rotate") || kindOf(cid) === "knob" ? "knob" : "action";
}
