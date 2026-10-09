/*
 * deck.js — The interactive deck (#deckRoot): a faithful Loupedeck Live S / Live picture whose touch keys
 * show their real, server-rendered look (POST /api/preview_key), round LED buttons that switch pages,
 * knobs with a caption, select / swap / duplicate / delete / arrow-key interactions, and the brief
 * knob-feedback overlay on the neighbouring touch key. Styles live in css/deck.css.
 *
 * Bus contract (state.js on/emit):
 *   emits "control:open" (cid)      — a key (or, on Live, a hardware button) was chosen. Knob clicks also
 *                                     emit it for now so the current encoder editor keeps working.
 *   emits "knob:open" ({knobId})    — a knob was clicked (the knob editor package listens to this).
 *   listens "knob:flash" ({knobId, text}) — draw `text` ~1.4 s on the knob's neighbouring touch key.
 *   listens "status:updated" (json) — the 1.5 s /api/status payload (from status.js), used to redraw live
 *                                     keys when OBS / Home Assistant go online or offline.
 * Debug: window.__flashKnob(knobId, text).
 */

import { BTNS_LIVE, BTNS_LIVE_S, KNOBS_LIVE, TOUCH_LIVE, TOUCH_LIVE_S } from "./constants.js";
import {
  currentPage,
  ensureDevice,
  ensurePages,
  getButtonEntry,
  layoutMode,
  setButtonEntry,
} from "./model.js";
import { scheduleAutosave } from "./save.js";
import { emit, on, state } from "./state.js";
import { snapshotBeforeAction } from "./undo.js";
import { $, cssColorForLedPreview, deepCloneJson, escapeAttr, escapeHtml } from "./util.js";

/**
 * Knob -> neighbouring touch key that shows the knob's feedback. Mirrors the backend source of truth,
 * knob_pages.feedback_touch_key_for_knob_page_name(): keep both in sync.
 */
const KNOB_FEEDBACK_TOUCH = {
  live: { knobTL: "touch_0", knobCL: "touch_4", knobBL: "touch_8", knobTR: "touch_3", knobCR: "touch_7", knobBR: "touch_11" },
  live_s: { knobTL: "touch_0", knobCL: "touch_5" },
};
const FLASH_MS = 1400;

/** Round buttons bound to pages 1-4 on Live S, and the LED colour used when the config has none. */
const PAGE_BUTTONS = BTNS_LIVE_S;
const DEFAULT_LEDS = ["#3b6bff", "#ff8a2b", "#e040c8", "#2de0c0"];

/** Live-key action types and the service whose connection decides the online / offline look. */
const LIVE_SERVICE = {
  "display.obs_scene": "obs",
  "display.obs_stream": "obs",
  "display.ha_sensor": "ha",
  "display.ha_weather": "ha",
  "display.clock": null,
  "display.battery": null,
  "display.live_message": null,
  "display.twitch_live": null,
};

/* ---- knob caption hook ---------------------------------------------------------------------- */

function defaultKnobCaption(knobId) {
  return knobId;
}
let knobCaptionProvider = defaultKnobCaption;

/** Caption shown under a knob (its role name). The knob editor package replaces the provider. */
export function getKnobCaption(knobId) {
  try {
    return String(knobCaptionProvider(knobId) || knobId);
  } catch {
    return knobId;
  }
}
export function setKnobCaptionProvider(fn) {
  knobCaptionProvider = typeof fn === "function" ? fn : defaultKnobCaption;
}

/* ---- helpers --------------------------------------------------------------------------------- */

function isTouch(cid) {
  return typeof cid === "string" && cid.startsWith("touch_");
}
function touchIds() {
  return layoutMode() === "live" ? TOUCH_LIVE : TOUCH_LIVE_S;
}
function touchCols() {
  return layoutMode() === "live" ? 4 : 5;
}
function entryActions(e) {
  if (!e) return [];
  if (Array.isArray(e.actions) && e.actions.length) return e.actions.filter((a) => a && typeof a === "object");
  return e.action && typeof e.action === "object" ? [e.action] : [];
}
function isFilled(e) {
  if (!e || typeof e !== "object") return false;
  return !!(
    entryActions(e).length ||
    e.image ||
    e.icon ||
    e.text ||
    e.label ||
    e.background ||
    e.background_gradient_from ||
    e.live_message
  );
}
function actionLabel(type) {
  const a = state.actionCatalog.find((x) => x.type === type);
  const label = (a && a.label) || type || "";
  const parts = String(label).split(/\s[—-]\s/);
  return parts.length > 1 ? parts.slice(1).join(" - ") : label;
}
function keyDescription(e) {
  const acts = entryActions(e);
  const what = acts.length ? actionLabel(acts[0].type) : "";
  const text = String((e && (e.label || e.text)) || "").trim();
  return [what, text].filter(Boolean).join(" ") || t("deck.key.empty_add");
}
function ledColor(cid) {
  const e = getButtonEntry(cid);
  const raw = e && e.button_color && String(e.button_color).trim();
  if (raw) return cssColorForLedPreview(raw);
  const i = PAGE_BUTTONS.indexOf(cid);
  return layoutMode() === "live_s" && i >= 0 ? DEFAULT_LEDS[i] : "#5b667c";
}
function pageName(i) {
  const p = state.cfg.pages && state.cfg.pages[i];
  return (p && p.name) || t("pages.default_name", { number: i + 1 });
}

/* ---- server-rendered previews ---------------------------------------------------------------- */

const CACHE_MAX = 400;
/** hash -> { url, overflow } | { none: true }. Blob URLs live as long as the entry is cached. */
const previewCache = new Map();
/** hash -> true while a request is pending (dedupe). */
const inflight = new Set();
/** cid -> last result shown there; avoids flicker while the next look loads. */
const lastShown = new Map();
const MAX_PARALLEL = 4;
const START_DELAY_MS = 70;
let active = 0;
const queue = [];

/** Connection of the services whose keys have an offline look (from the status poll). */
const conn = { obs: true, ha: true };

function liveService(e) {
  for (const a of entryActions(e)) {
    if (a.type in LIVE_SERVICE) return { live: true, service: LIVE_SERVICE[a.type] };
  }
  if (e && e.live_message) return { live: true, service: null };
  return { live: false, service: null };
}
function isOffline(e) {
  const { live, service } = liveService(e);
  return live && service ? conn[service] === false : false;
}

function previewRequest(cid, e) {
  const entry = deepCloneJson(e || {});
  delete entry.button_color;
  const offline = isOffline(e);
  const body = { entry, control_id: cid };
  if (offline) body.offline = true;
  // Proposed labels are translated: ask in the UI language, and keep languages apart in the cache.
  const lang = (window.i18n && window.i18n.lang) || "";
  if (lang) body.lang = lang;
  const sizeClass = cid.startsWith("strip_") ? "strip" : "key";
  return { hash: `${sizeClass}|${offline ? 1 : 0}|${lang}|${JSON.stringify(entry)}`, body };
}

function cacheSet(hash, val) {
  previewCache.set(hash, val);
  while (previewCache.size > CACHE_MAX) {
    const oldest = previewCache.keys().next().value;
    const old = previewCache.get(oldest);
    previewCache.delete(oldest);
    if (old && old.url && !document.querySelector(`img[src="${old.url}"]`)) URL.revokeObjectURL(old.url);
  }
}

function elementsForHash(hash) {
  return Array.from(document.querySelectorAll(".dk-key[data-hash]")).filter((el) => el.dataset.hash === hash);
}

function applyResult(el, res) {
  const img = el.querySelector(".dk-img");
  const warn = el.querySelector(".dk-warn");
  el.classList.remove("is-loading");
  if (res && res.url) {
    img.src = res.url;
    img.hidden = false;
    el.classList.add("has-image");
    el.classList.remove("no-image");
    if (warn) warn.hidden = !res.overflow;
    lastShown.set(el.dataset.cid, res);
  } else {
    img.removeAttribute("src");
    img.hidden = true;
    el.classList.remove("has-image");
    el.classList.add("no-image");
    if (warn) warn.hidden = true;
    lastShown.delete(el.dataset.cid);
  }
}

function pump() {
  while (active < MAX_PARALLEL && queue.length) {
    const job = queue.shift();
    active += 1;
    job().finally(() => {
      active -= 1;
      pump();
    });
  }
}

async function fetchPreview(hash, body) {
  // Wait briefly so a burst of edits only renders the latest look, then skip what is no longer shown.
  await new Promise((r) => setTimeout(r, START_DELAY_MS));
  if (!elementsForHash(hash).length) return;
  try {
    const r = await fetch("/api/preview_key", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (r.status === 404 || r.status === 400) {
      cacheSet(hash, { none: true });
    } else if (r.ok) {
      const overflow = r.headers.get("X-Key-Overflow") === "1";
      const url = URL.createObjectURL(await r.blob());
      cacheSet(hash, { url, overflow });
    } else {
      return;
    }
  } catch {
    return;
  }
  const res = previewCache.get(hash);
  for (const el of elementsForHash(hash)) applyResult(el, res);
}

/** Make `el` (a key) show the right look for its current entry: cache hit, or skeleton + request. */
function loadKey(el) {
  const cid = el.dataset.cid;
  const e = getButtonEntry(cid);
  if (!isFilled(e)) {
    el.dataset.hash = "";
    applyResult(el, null);
    el.classList.remove("no-image");
    return;
  }
  const { hash, body } = previewRequest(cid, e);
  el.dataset.hash = hash;
  el.dataset.live = liveService(e).live ? "1" : "";
  const hit = previewCache.get(hash);
  if (hit) {
    applyResult(el, hit);
    return;
  }
  const stale = lastShown.get(cid);
  if (stale && !el.classList.contains("has-image")) applyResult(el, stale);
  el.classList.add("is-loading");
  if (!inflight.has(hash)) {
    inflight.add(hash);
    queue.push(() => fetchPreview(hash, body).finally(() => inflight.delete(hash)));
    pump();
  }
}

/* ---- markup ---------------------------------------------------------------------------------- */

function keyHtml(cid, index) {
  const e = getButtonEntry(cid);
  const filled = isFilled(e);
  const err = state.touchErrors && state.touchErrors[cid];
  const aria = filled
    ? t("deck.key.aria", { number: index + 1, what: keyDescription(e) })
    : t("deck.key.aria_empty", { number: index + 1 });
  const strip = cid.startsWith("strip_");
  const name = strip ? t(cid === "strip_left" ? "deck.strip.left" : "deck.strip.right") : "";
  const label = strip ? `${name}${filled ? `, ${keyDescription(e)}` : ""}` : aria;
  const fallback = filled ? escapeHtml(keyDescription(e)) : "";
  return `<div class="dk-key${filled ? " is-filled" : " is-empty"}${strip ? " dk-strip" : ""}${
    err ? " error-outline" : ""
  }" role="button" tabindex="-1" data-cid="${escapeAttr(cid)}" ${
    isTouch(cid) && filled ? 'draggable="true"' : ""
  } aria-label="${escapeAttr(label)}" title="${escapeAttr(err ? `${cid} — ${err}` : strip ? name : aria)}">
    <img class="dk-img" alt="" hidden draggable="false" />
    <span class="dk-skel" aria-hidden="true"></span>
    <span class="dk-fallback" aria-hidden="true">${fallback}</span>
    <span class="dk-plus" aria-hidden="true">+</span>
    <span class="dk-warn" hidden title="${escapeAttr(t("deck.overflow"))}" aria-label="${escapeAttr(
      t("deck.overflow")
    )}">&#9888;</span>
    <button type="button" class="dk-dup" tabindex="-1" title="${escapeAttr(t("deck.duplicate.title"))}">${escapeHtml(
      t("deck.duplicate")
    )}</button>
  </div>`;
}

function roundHtml(cid, number) {
  const live = layoutMode() === "live_s";
  const i = PAGE_BUTTONS.indexOf(cid);
  const led = ledColor(cid);
  const aria = live && i >= 0 ? t("deck.round.aria_page", { number, page: pageName(i) }) : t("deck.round.aria_plain", { number });
  const title = live && i >= 0 ? t("deck.round.title_page", { page: pageName(i) }) : cid;
  return `<button type="button" class="dk-round${cid === "btn_circle" ? " is-circle" : ""}" data-cid="${escapeAttr(
    cid
  )}" data-page="${live ? i : ""}" style="--led:${escapeAttr(led)}" aria-label="${escapeAttr(aria)}" title="${escapeAttr(
    title
  )}"${live && i >= 0 ? ` aria-pressed="${state.pageIndex === i}"` : ""}></button>`;
}

function knobHtml(knobId) {
  const cap = getKnobCaption(knobId);
  return `<div class="dk-knobwrap">
    <button type="button" class="dk-knob" data-knob="${escapeAttr(knobId)}" aria-pressed="false" aria-label="${escapeAttr(
      t("deck.knob.aria", { name: knobId, role: cap })
    )}" title="${escapeAttr(knobId)}"><span class="dk-notch" aria-hidden="true"></span></button>
    <span class="dk-kcap">${escapeHtml(cap)}</span>
  </div>`;
}

function touchScreenHtml(cols) {
  const ids = touchIds();
  return `<div class="dk-screen dk-cols-${cols}">${ids.map((c, i) => keyHtml(c, i)).join("")}</div>`;
}

function liveSHtml() {
  return `<div class="dk-device dk-live-s">
    <div class="dk-col dk-left">
      <div class="dk-knobs">${["knobTL", "knobCL"].map(knobHtml).join("")}</div>
      ${roundHtml("btn_circle", 1)}
    </div>
    ${touchScreenHtml(5)}
    <div class="dk-col dk-right">${["btn_1", "btn_2", "btn_3"].map((c, i) => roundHtml(c, i + 2)).join("")}</div>
  </div>`;
}

function liveHtml() {
  const side = (strip, knobs) => `<div class="dk-side">
      <div class="dk-knobs">${knobs.map(knobHtml).join("")}</div>
      ${keyHtml(strip, strip === "strip_left" ? 0 : 1)}
    </div>`;
  return `<div class="dk-device dk-live">
    ${side("strip_left", KNOBS_LIVE.slice(0, 3))}
    <div class="dk-live-center">
      ${touchScreenHtml(4)}
      <div class="dk-row-btns">${BTNS_LIVE.map((c, i) => roundHtml(c, i + 1)).join("")}</div>
    </div>
    ${side("strip_right", KNOBS_LIVE.slice(3))}
  </div>`;
}

/* ---- selection painting ---------------------------------------------------------------------- */

/** Knob picked on the deck (the knob view mirrors it in state.selectedKnobEncoder). */
let ownKnob = null;
let lastSelectedControl = null;

function selectedKnob() {
  return state.selectedKnobEncoder || ownKnob;
}

function feedbackKeyForKnob(knobId) {
  const table = KNOB_FEEDBACK_TOUCH[layoutMode()] || {};
  return table[knobId] || null;
}

function paintSelection() {
  if (state.selectedControl !== lastSelectedControl) {
    lastSelectedControl = state.selectedControl;
    if (state.selectedControl) ownKnob = null;
  }
  const knob = selectedKnob();
  const sel = knob ? null : state.selectedControl;
  const link = knob ? feedbackKeyForKnob(knob) : null;
  const root = $("#deckRoot");
  if (!root) return;
  let tabStop = null;
  root.querySelectorAll(".dk-key").forEach((el) => {
    const cid = el.dataset.cid;
    el.classList.toggle("is-selected", cid === sel);
    el.classList.toggle("is-knob-link", cid === link);
    if (cid === sel) tabStop = el;
  });
  const keys = Array.from(root.querySelectorAll(".dk-key"));
  if (!tabStop || !root.contains(tabStop)) tabStop = keys.find((k) => k === document.activeElement) || keys[0];
  keys.forEach((k) => k.setAttribute("tabindex", k === tabStop ? "0" : "-1"));
  root.querySelectorAll(".dk-knob").forEach((el) => el.setAttribute("aria-pressed", String(el.dataset.knob === knob)));
  root.querySelectorAll(".dk-round[data-page]").forEach((el) => {
    const p = el.dataset.page;
    if (p !== "") el.setAttribute("aria-pressed", String(Number(p) === state.pageIndex));
    else el.setAttribute("aria-pressed", String(el.dataset.cid === sel));
  });
}

/* ---- actions --------------------------------------------------------------------------------- */

let noteTimer = null;
function note(msg) {
  const el = $("#deckNote");
  if (!el) return;
  el.textContent = msg;
  clearTimeout(noteTimer);
  noteTimer = setTimeout(() => {
    el.textContent = "";
  }, 2500);
}

function focusKey(cid) {
  const el = document.querySelector(`#deckRoot .dk-key[data-cid="${CSS.escape(cid)}"]`);
  if (el) el.focus();
}

function selectKey(cid) {
  ownKnob = null;
  emit("control:open", cid);
  paintSelection();
}

function swapButtonEntries(cidA, cidB) {
  if (!cidA || !cidB || cidA === cidB) return;
  snapshotBeforeAction();
  const entryA = getButtonEntry(cidA);
  const entryB = getButtonEntry(cidB);
  setButtonEntry(cidA, entryB);
  setButtonEntry(cidB, entryA);
  renderDeck();
  scheduleAutosave();
  if (state.selectedControl === cidA || state.selectedControl === cidB) {
    emit("control:open", state.selectedControl);
  }
}

function duplicateKey(cid) {
  const e = getButtonEntry(cid);
  if (!isTouch(cid) || !isFilled(e)) return;
  const ids = touchIds();
  const start = ids.indexOf(cid);
  let target = null;
  for (let step = 1; step < ids.length; step += 1) {
    const c = ids[(start + step) % ids.length];
    if (!isFilled(getButtonEntry(c))) {
      target = c;
      break;
    }
  }
  if (!target) {
    note(t("deck.no_free_key"));
    return;
  }
  snapshotBeforeAction();
  setButtonEntry(target, deepCloneJson(e));
  renderDeck();
  scheduleAutosave();
  selectKey(target);
  focusKey(target);
  note(t("deck.duplicated", { number: ids.indexOf(target) + 1 }));
}

function clearKey(cid) {
  if (!isTouch(cid) || !isFilled(getButtonEntry(cid))) return;
  snapshotBeforeAction();
  setButtonEntry(cid, null);
  renderDeck();
  scheduleAutosave();
  selectKey(cid);
  focusKey(cid);
}

function moveSelection(cid, key) {
  const ids = touchIds();
  const i = ids.indexOf(cid);
  if (i < 0) return;
  const cols = touchCols();
  const rows = ids.length / cols;
  let r = Math.floor(i / cols);
  let c = i % cols;
  if (key === "ArrowLeft") c = Math.max(0, c - 1);
  else if (key === "ArrowRight") c = Math.min(cols - 1, c + 1);
  else if (key === "ArrowUp") r = Math.max(0, r - 1);
  else r = Math.min(rows - 1, r + 1);
  const next = ids[r * cols + c];
  if (next === cid) return;
  selectKey(next);
  focusKey(next);
}

function switchToPage(i) {
  const sel = $("#pageSelect");
  if (!sel || i === state.pageIndex) return;
  sel.value = String(i);
  sel.dispatchEvent(new Event("change", { bubbles: true }));
}

/** cid currently being dragged, or null when no drag is in progress. */
let draggingCid = null;

function bindKey(el) {
  const cid = el.dataset.cid;
  el.addEventListener("click", (ev) => {
    if (draggingCid) return;
    if (ev.target.closest(".dk-dup")) return;
    selectKey(cid);
  });
  el.addEventListener("keydown", (ev) => {
    if (ev.target !== el) return;
    if (ev.key === "Enter" || ev.key === " ") {
      ev.preventDefault();
      selectKey(cid);
    } else if (ev.key.startsWith("Arrow") && isTouch(cid)) {
      ev.preventDefault();
      moveSelection(cid, ev.key);
    } else if (ev.key === "Delete" || ev.key === "Backspace") {
      ev.preventDefault();
      clearKey(cid);
    } else if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "d") {
      ev.preventDefault();
      duplicateKey(cid);
    }
  });
  const dup = el.querySelector(".dk-dup");
  if (dup) {
    dup.addEventListener("click", (ev) => {
      ev.stopPropagation();
      duplicateKey(cid);
    });
  }
  if (!isTouch(cid)) return;
  el.addEventListener("dragstart", (ev) => {
    draggingCid = cid;
    ev.dataTransfer.effectAllowed = "move";
    ev.dataTransfer.setData("text/plain", cid);
    el.classList.add("dragging");
  });
  el.addEventListener("dragend", () => {
    draggingCid = null;
    el.classList.remove("dragging");
    document.querySelectorAll(".dk-key.drag-over").forEach((c) => c.classList.remove("drag-over"));
  });
  el.addEventListener("dragover", (ev) => {
    if (!draggingCid || cid === draggingCid) return;
    ev.preventDefault();
    ev.dataTransfer.dropEffect = "move";
    el.classList.add("drag-over");
  });
  el.addEventListener("dragleave", () => el.classList.remove("drag-over"));
  el.addEventListener("drop", (ev) => {
    el.classList.remove("drag-over");
    if (!draggingCid || cid === draggingCid) return;
    ev.preventDefault();
    const source = draggingCid;
    draggingCid = null;
    swapButtonEntries(source, cid);
  });
}

function bindRoot(root) {
  root.querySelectorAll(".dk-key").forEach(bindKey);
  root.querySelectorAll(".dk-round").forEach((el) => {
    const cid = el.dataset.cid;
    el.addEventListener("click", () => {
      const p = el.dataset.page;
      if (p !== "" && p != null) {
        switchToPage(Number(p));
        paintSelection();
      } else {
        selectKey(cid);
      }
    });
    // On Live S a click changes page; double-click reaches the button's own settings (LED colour).
    el.addEventListener("dblclick", () => {
      if (el.dataset.page !== "") selectKey(cid);
    });
  });
  root.querySelectorAll(".dk-knob").forEach((el) => {
    el.addEventListener("click", () => {
      const knobId = el.dataset.knob;
      ownKnob = knobId;
      emit("knob:open", { knobId });
      paintSelection();
    });
  });
}

/* ---- knob feedback overlay ------------------------------------------------------------------- */

const flashes = new Map();

function drawFlash(cid) {
  const el = document.querySelector(`#deckRoot .dk-key[data-cid="${CSS.escape(cid)}"]`);
  const f = flashes.get(cid);
  if (!el) return;
  let ov = el.querySelector(".dk-flash");
  if (!f) {
    if (ov) ov.remove();
    return;
  }
  if (!ov) {
    ov = document.createElement("div");
    ov.className = "dk-flash";
    ov.setAttribute("aria-hidden", "true");
    el.appendChild(ov);
  }
  ov.textContent = f.text;
}

export function flashKnob(knobId, text) {
  const cid = feedbackKeyForKnob(knobId);
  if (!cid) return;
  const prev = flashes.get(cid);
  if (prev) clearTimeout(prev.timer);
  const timer = setTimeout(() => {
    flashes.delete(cid);
    drawFlash(cid);
  }, FLASH_MS);
  flashes.set(cid, { text: String(text ?? ""), timer });
  drawFlash(cid);
}

/* ---- render ---------------------------------------------------------------------------------- */

export function renderDeck() {
  ensurePages();
  ensureDevice();
  $("#pageName").textContent = currentPage().name || t("pages.default_name", { number: state.pageIndex + 1 });
  const pn = $("#pageNameInput");
  if (pn) pn.value = currentPage().name || "";

  const root = $("#deckRoot");
  if (!root) return;
  root.innerHTML = `${layoutMode() === "live" ? liveHtml() : liveSHtml()}
    <p class="dk-hint">${escapeHtml(t("deck.hint"))}</p>
    <p class="dk-note" id="deckNote" role="status" aria-live="polite"></p>`;
  bindRoot(root);
  root.querySelectorAll(".dk-key").forEach(loadKey);
  for (const cid of flashes.keys()) drawFlash(cid);
  paintSelection();
}

/** Redraw only the keys whose look depends on a service connection (status poll: no flicker). */
function refreshLiveKeys() {
  document.querySelectorAll("#deckRoot .dk-key").forEach((el) => {
    const e = getButtonEntry(el.dataset.cid);
    if (!isFilled(e)) return;
    const { hash } = previewRequest(el.dataset.cid, e);
    if (hash !== el.dataset.hash) loadKey(el);
  });
}

on("status:updated", (st) => {
  const obs = !(st && st.obs && st.obs.configured && !st.obs.connected);
  const ha = !(st && st.ha && st.ha.configured && !st.ha.connected);
  const changed = obs !== conn.obs || ha !== conn.ha;
  conn.obs = obs;
  conn.ha = ha;
  if (changed) refreshLiveKeys();
});
on("knob:flash", (p) => {
  if (p && p.knobId) flashKnob(p.knobId, p.text);
});
document.addEventListener("i18n:change", () => {
  if (state.cfg && state.cfg.pages) renderDeck();
});
window.__flashKnob = flashKnob;

// Selection is owned by the editors (they run after "control:open" and sometimes reset it after a
// render), so the deck follows state with a cheap diff instead of trusting call order.
setInterval(() => {
  if (!document.hidden) paintSelection();
}, 150);
