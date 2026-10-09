/*
 * model.js — The config model: device layout detection, page/global button lookup and normalisation
 * (ensure*), entry helpers. Reads and mutates state.cfg; no DOM.
 */

import { BTNS_LIVE_S, KNOBS_LIVE } from "./constants.js";
import { state } from "./state.js";
import { hasTactileGraphic } from "./util.js";

export function layoutMode() {
  const m = (state.cfg.device && state.cfg.device.model) || "auto";
  if (m === "live") return "live";
  if (m === "live_s") return "live_s";
  if (state.agentDeckLayout === "live") return "live";
  if (state.agentDeckLayout === "live_s") return "live_s";
  return "live_s";
}

export function isLiveSModel() {
  return layoutMode() === "live_s";
}

export function isLiveSPageSwitchButton(cid) {
  return isLiveSModel() && typeof cid === "string" && BTNS_LIVE_S.includes(cid);
}

export function liveKnobEncoderIds() {
  return layoutMode() === "live_s" ? ["knobTL", "knobCL"] : [...KNOBS_LIVE];
}

export function isKnobEncoderId(cid) {
  return typeof cid === "string" && liveKnobEncoderIds().includes(cid);
}

function knobKeys(k) {
  return [`${k}_left`, `${k}_right`, k];
}

/** True if the key has a PNG preview (tactile) or a Live S physical LED color. */
export function hasRenderableVisual(e) {
  if (!e) return false;
  if (hasTactileGraphic(e)) return true;
  const bc = e.button_color && String(e.button_color).trim();
  return !!(bc && layoutMode() === "live_s");
}

export function isLiveSPhysicalButton(cid) {
  return layoutMode() === "live_s" && typeof cid === "string" && BTNS_LIVE_S.includes(cid);
}

// Config keys for the gradients/idle/press design fields (see button_render.py's
// render_tactile_key_image docstring for the exact contract each one implements).
const DESIGN_FIELD_KEYS = [
  "text_gradient_from",
  "text_gradient_to",
  "text_gradient_angle",
  "background_gradient_from",
  "background_gradient_to",
  "background_gradient_angle",
  "idle_animation",
  "idle_animation_speed",
  "press_animation",
  "press_animation_direction",
  "press_flash_color",
];

export function visualEntryForPreview(e) {
  if (!e) return {};
  const o = {};
  for (const k of [
    "text",
    "label",
    "image",
    "icon",
    "background",
    "text_color",
    "font_size",
    "font_file",
    "graphic_text_layout",
    ...DESIGN_FIELD_KEYS,
  ]) {
    if (e[k] != null && e[k] !== "") o[k] = e[k];
  }
  return o;
}

export function clampPageIndex(agentIndex) {
  ensurePages();
  const n = state.cfg.pages.length;
  if (n === 0) return 0;
  if (typeof agentIndex !== "number" || !Number.isFinite(agentIndex)) return state.pageIndex;
  return ((Math.floor(agentIndex) % n) + n) % n;
}

/** Loupedeck Live side strips are not represented as discrete keys in the agent (no synthetic message). */
export function controlCanSimulate(cid) {
  if (!cid || typeof cid !== "string") return false;
  if (cid === "strip_left" || cid === "strip_right") return false;
  return true;
}

export function canPasteToControl(cid) {
  if (!cid || typeof cid !== "string") return false;
  if (cid === "strip_left" || cid === "strip_right") return false;
  return true;
}

/** Page N is bound to round button N (page 1 = circle button, 2-4 = the three right-hand buttons). */
export const HARDWARE_PAGE_COUNT = 4;

function defaultPageName(n) {
  return t("pages.default_name", { number: n });
}

export function ensurePages() {
  if (!Array.isArray(state.cfg.pages)) state.cfg.pages = [];
  const pages = state.cfg.pages;
  // The four hardware pages always exist: pad (never alters existing pages).
  while (pages.length < HARDWARE_PAGE_COUNT) {
    pages.push({ name: defaultPageName(pages.length + 1), buttons: {} });
  }
  if (isLiveSModel()) {
    pages.forEach((p, i) => {
      if (!p || typeof p !== "object") {
        pages[i] = { id: i, name: defaultPageName(i + 1), buttons: {} };
        return;
      }
      p.id = i;
      if (!p.name) p.name = defaultPageName(i + 1);
      if (!p.buttons || typeof p.buttons !== "object") p.buttons = {};
    });
  } else {
    pages.forEach((p, i) => {
      if (p && typeof p === "object" && !p.buttons) p.buttons = {};
      else if (!p || typeof p !== "object") pages[i] = { name: defaultPageName(i + 1), buttons: {} };
    });
  }
  if (state.pageIndex >= pages.length) state.pageIndex = Math.max(0, pages.length - 1);
}

export function ensureDevice() {
  if (!state.cfg.device) state.cfg.device = { path: "", baudrate: null, model: "auto" };
  if (state.cfg.device.model == null) state.cfg.device.model = "auto";
}

export function ensureGlobalButtons() {
  if (!state.cfg.global_buttons || typeof state.cfg.global_buttons !== "object") {
    state.cfg.global_buttons = {};
  }
}

/** Center touch keys are per-page; knobs, strips, and physical side buttons use ``global_buttons``. */
function isPageScopedControl(cid) {
  return typeof cid === "string" && cid.startsWith("touch_");
}

function removeControlFromAllPages(cid) {
  ensurePages();
  for (const p of state.cfg.pages) {
    if (p.buttons && Object.prototype.hasOwnProperty.call(p.buttons, cid)) {
      delete p.buttons[cid];
    }
  }
}

export function currentPage() {
  ensurePages();
  return state.cfg.pages[state.pageIndex];
}

export function getButtonEntry(cid) {
  ensurePages();
  ensureGlobalButtons();
  if (isPageScopedControl(cid)) {
    const p = currentPage();
    if (!p.buttons) p.buttons = {};
    return p.buttons[cid] || null;
  }
  if (state.cfg.global_buttons[cid]) {
    return state.cfg.global_buttons[cid];
  }
  const p = currentPage();
  if (!p.buttons) p.buttons = {};
  return p.buttons[cid] || null;
}

export function setButtonEntry(cid, entry) {
  ensurePages();
  ensureGlobalButtons();
  if (isPageScopedControl(cid)) {
    const p = currentPage();
    if (!p.buttons) p.buttons = {};
    if (entry == null) delete p.buttons[cid];
    else p.buttons[cid] = entry;
  } else {
    if (entry == null) {
      delete state.cfg.global_buttons[cid];
      removeControlFromAllPages(cid);
    } else {
      state.cfg.global_buttons[cid] = entry;
      removeControlFromAllPages(cid);
    }
  }
}

export function knobPageLabelFromConfig(page) {
  if (!page || typeof page !== "object") return "";
  return String(page.name || page.page_change_message || page.message || "").trim();
}
