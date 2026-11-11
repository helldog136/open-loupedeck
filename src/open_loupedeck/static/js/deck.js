/*
 * deck.js — The interactive deck (#deckRoot), drawn from the edited device model (state.model): every
 * control placed from its position (device-layout.js, shared with the virtual device). Display keys
 * show their real, server-rendered look (POST /api/preview_key, the model's key size); knobs, buttons,
 * sliders, strips and pedals are drawn with their role as a caption; the selected control is
 * highlighted, and the key showing a selected knob's feedback is outlined. Keys can be dragged onto one
 * another (swap), duplicated (Ctrl+D) and cleared (Delete); audio files dropped on an empty key make
 * sound keys. Styles live in css/deck.css.
 *
 * What a control shows is its resolved binding on the page shown (model.js: page binding, else
 * global); keys that come from the global binding carry a small "every page" badge.
 *
 * Bus contract (state.js on/emit):
 *   emits "control:open" (cid)     — a control was picked (any kind; the inspector routes by capability).
 *   listens "knob:flash" ({knobId, text}) — draw `text` ~1.4 s on the knob's feedback key.
 *   listens "status:updated" (json) — the /api/status payload (status.js): live keys get their online /
 *                                     offline look when OBS / Home Assistant come and go.
 * Debug: window.__flashKnob(knobId, text).
 */

import { actionShortName } from "./catalog.js";
import { PAD, fitUnit, keyBed, keyCoord, placeAt, visualOrder } from "./device-layout.js";
import {
  controlLabel,
  displayEntry,
  ensureDevice,
  ensurePages,
  entryActions,
  feedbackKeyFor,
  gotoPageIndex,
  indexOf,
  keyIds,
  keyNumber,
  pageEntry,
  pageName,
  resolvedBinding,
  setEntry,
} from "./model.js";
import { cleanSoundName, isAudioFile, uploadSoundFile } from "./pickers/sound-picker.js";
import { scheduleAutosave } from "./save.js";
import { goToService } from "./shell.js";
import { emit, on, state } from "./state.js";
import { snapshotBeforeAction } from "./undo.js";
import { $, cssColorForLedPreview, deepCloneJson } from "./util.js";

const FLASH_MS = 1400;
const MAX_UNIT = 118;
/** Smallest unit (px) the deck is drawn at: a key stays a comfortable tap target, a narrower screen pans. */
const MIN_UNIT = 38;

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

const noCaption = () => "";
let knobCaptionProvider = noCaption;

/** Caption shown under a knob (its role name on the page shown). The knob view provides it. */
export function getKnobCaption(knobId) {
  try {
    return String(knobCaptionProvider(knobId) || "");
  } catch {
    return "";
  }
}
export function setKnobCaptionProvider(fn) {
  knobCaptionProvider = typeof fn === "function" ? fn : noCaption;
}

/* ---- helpers --------------------------------------------------------------------------------- */

function mk(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
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

function keyDescription(e) {
  const acts = entryActions(e);
  const what = acts.length ? actionShortName(acts[0].type) : "";
  const text = String((e && (e.label || e.text)) || "").trim();
  return [what, text].filter(Boolean).join(" · ") || t("deck.key.empty_add");
}

/** Short role of a button / pedal for its caption: the page it opens, else its action, else "". */
function actionCaption(e) {
  const page = gotoPageIndex(e);
  if (page != null) return pageName(page);
  const acts = entryActions(e);
  return acts.length ? actionShortName(acts[0].type) : "";
}

function ledColor(cid) {
  const e = displayEntry(cid);
  const raw = e && e.button_color && String(e.button_color).trim();
  return raw ? cssColorForLedPreview(raw) : "";
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
  const model = state.model ? state.model.id : "";
  const body = { entry, control_id: cid, model };
  if (offline) body.offline = true;
  // Proposed labels are translated: ask in the UI language, and keep languages apart in the cache.
  const lang = (window.i18n && window.i18n.lang) || "";
  if (lang) body.lang = lang;
  const c = state.model && state.model.controls.find((x) => x.id === cid);
  const img = c && c.outputs && c.outputs.image;
  const size = img ? `${img.width}x${img.height}` : "key";
  return { hash: `${size}|${offline ? 1 : 0}|${lang}|${JSON.stringify(entry)}`, body };
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
  return Array.from(document.querySelectorAll("#deckRoot .dk-key[data-hash]")).filter((n) => n.dataset.hash === hash);
}

function applyResult(node, res) {
  const img = node.querySelector(".dk-img");
  const warn = node.querySelector(".dk-warn");
  node.classList.remove("is-loading");
  if (res && res.url) {
    img.src = res.url;
    img.hidden = false;
    node.classList.add("has-image");
    node.classList.remove("no-image");
    if (warn) warn.hidden = !res.overflow;
    lastShown.set(node.dataset.cid, res);
  } else {
    img.removeAttribute("src");
    img.hidden = true;
    node.classList.remove("has-image");
    node.classList.add("no-image");
    if (warn) warn.hidden = true;
    lastShown.delete(node.dataset.cid);
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
  for (const n of elementsForHash(hash)) applyResult(n, res);
}

/** Make `node` (a key) show the right look for its current entry: cache hit, or skeleton + request. */
function loadKey(node) {
  const cid = node.dataset.cid;
  const e = displayEntry(cid);
  if (!isFilled(e)) {
    node.dataset.hash = "";
    applyResult(node, null);
    node.classList.remove("no-image");
    return;
  }
  const { hash, body } = previewRequest(cid, e);
  node.dataset.hash = hash;
  const hit = previewCache.get(hash);
  if (hit) {
    applyResult(node, hit);
    return;
  }
  const stale = lastShown.get(cid);
  if (stale && !node.classList.contains("has-image")) applyResult(node, stale);
  node.classList.add("is-loading");
  if (!inflight.has(hash)) {
    inflight.add(hash);
    queue.push(() => fetchPreview(hash, body).finally(() => inflight.delete(hash)));
    pump();
  }
}

/* ---- control elements ------------------------------------------------------------------------ */

function caption(text, empty = false) {
  const cap = mk("span", `dk-cap${empty ? " is-empty" : ""}`, text);
  cap.setAttribute("aria-hidden", "true");
  return cap;
}

function keyNode(ctl) {
  const cid = ctl.id;
  const b = resolvedBinding(cid);
  const e = b ? b.entry : null;
  const filled = isFilled(e);
  const strip = ctl.kind === "strip";
  const node = mk("div", `dk-ctl dk-key${strip ? " dk-strip" : ""}${filled ? " is-filled" : " is-empty"}`);
  node.dataset.cid = cid;
  node.setAttribute("role", "button");
  node.tabIndex = -1;
  const name = controlLabel(cid);
  node.setAttribute("aria-label", filled ? `${name}, ${keyDescription(e)}` : t("deck.key.aria_empty_named", { name }));
  if (b && b.scope === "global") node.classList.add("is-global");
  // A touch strip cannot be bound yet: no "+" inviting the user to add something.
  if (!(ctl.inputs || []).includes("press")) node.classList.add("is-passive");
  // Only the page's own binding moves with a drag (a key showing the global binding has none).
  if (!strip && pageEntry(cid)) node.draggable = true;
  const face = mk("span", "dk-face");
  const img = mk("img", "dk-img");
  img.alt = "";
  img.hidden = true;
  img.draggable = false;
  face.append(img, mk("span", "dk-skel"), mk("span", "dk-fallback", filled ? keyDescription(e) : ""), mk("span", "dk-plus", "+"));
  const warn = mk("span", "dk-warn", "⚠");
  warn.hidden = true;
  warn.title = t("deck.overflow");
  warn.setAttribute("aria-label", t("deck.overflow"));
  const badge = mk("span", "dk-badge");
  badge.title = t("deck.key.global");
  badge.setAttribute("aria-hidden", "true");
  face.append(warn, badge);
  for (const c of face.children) if (c !== warn) c.setAttribute("aria-hidden", "true");
  node.append(face);
  if (!strip) {
    // A round corner tool outside the face: it never covers the key's text.
    const dup = mk("button", "dk-dup", "⧉");
    dup.type = "button";
    dup.tabIndex = -1;
    dup.title = t("deck.duplicate.title");
    dup.setAttribute("aria-label", t("deck.duplicate"));
    node.append(dup);
  }
  return node;
}

function knobNode(ctl) {
  const role = getKnobCaption(ctl.id);
  const node = mk("button", "dk-ctl dk-knob");
  node.type = "button";
  node.dataset.cid = ctl.id;
  node.setAttribute("aria-label", t("deck.knob.aria", { name: controlLabel(ctl.id), role: role || t("inspector.knob.role.none") }));
  const face = mk("span", "dk-face");
  const dial = mk("span", "dk-dial");
  dial.append(mk("span", "dk-notch"));
  face.append(dial);
  node.title = `${controlLabel(ctl.id)}: ${role || t("inspector.knob.role.none")}`;
  node.append(face, caption(role || t("inspector.knob.role.none"), !role));
  return node;
}

function buttonNode(ctl) {
  const e = displayEntry(ctl.id);
  const cap = actionCaption(e);
  const node = mk("button", `dk-ctl dk-btn${ctl.kind === "pedal" ? " dk-pedal" : ""}`);
  node.type = "button";
  node.dataset.cid = ctl.id;
  const led = ctl.outputs && ctl.outputs.led ? ledColor(ctl.id) : "";
  if (led) {
    node.style.setProperty("--led", led);
    node.classList.add("is-lit");
  }
  const page = gotoPageIndex(e);
  if (page != null) {
    node.dataset.page = String(page);
    if (page === state.pageIndex) node.setAttribute("aria-current", "page");
  }
  const name = controlLabel(ctl.id);
  node.setAttribute(
    "aria-label",
    page != null ? t("deck.button.aria_page", { name, page: pageName(page) }) : cap ? `${name}, ${cap}` : t("deck.key.aria_empty_named", { name }),
  );
  node.title = page != null ? t("deck.button.title_page", { page: pageName(page) }) : cap ? `${name}: ${cap}` : name;
  const face = mk("span", "dk-face");
  face.append(mk("span", "dk-btn-num", String(indexOf(ctl.id) + 1)));
  node.append(face, caption(cap));
  return node;
}

function sliderNode(ctl) {
  const node = mk("button", `dk-ctl dk-slider ${ctl.position.h >= ctl.position.w ? "is-vertical" : "is-horizontal"}`);
  node.type = "button";
  node.dataset.cid = ctl.id;
  const name = controlLabel(ctl.id);
  node.setAttribute("aria-label", t("deck.slider.aria", { name }));
  node.title = name;
  node.append(mk("span", "dk-track"), mk("span", "dk-thumb"), caption(name, true));
  return node;
}

function controlNode(ctl) {
  switch (ctl.kind) {
    case "key":
      return keyNode(ctl);
    case "strip":
      return ctl.outputs && ctl.outputs.image ? keyNode(ctl) : sliderNode(ctl);
    case "knob":
      return knobNode(ctl);
    case "slider":
      return sliderNode(ctl);
    case "button":
    case "pedal":
      return buttonNode(ctl);
    default:
      return null;
  }
}

/* ---- selection painting ---------------------------------------------------------------------- */

function paintSelection() {
  const root = $("#deckRoot");
  if (!root) return;
  const sel = state.selectedControl;
  const selCtl = sel && state.model ? state.model.controls.find((c) => c.id === sel) : null;
  const link = selCtl && selCtl.kind === "knob" ? feedbackKeyFor(sel) : null;
  let tabStop = null;
  const keys = [];
  root.querySelectorAll(".dk-ctl").forEach((n) => {
    const cid = n.dataset.cid;
    n.classList.toggle("is-selected", cid === sel);
    n.classList.toggle("is-knob-link", cid === link);
    n.classList.toggle("has-error", !!(state.controlErrors && state.controlErrors[cid]));
    if (n.matches(".dk-key:not(.dk-strip)")) {
      keys.push(n);
      if (cid === sel) tabStop = n;
    }
    if (n.matches("button")) n.setAttribute("aria-pressed", String(cid === sel));
  });
  scrollSelectionIntoView(root.querySelector(".dk-stage-wrap"));
  if (!tabStop) tabStop = keys.find((k) => k === document.activeElement) || keys[0];
  keys.forEach((k) => (k.tabIndex = k === tabStop ? 0 : -1));
  root.querySelectorAll(".dk-strip").forEach((s) => (s.tabIndex = 0));
}

/* ---- actions --------------------------------------------------------------------------------- */

let noteTimer = null;
function note(msg) {
  const n = $("#deckNote");
  if (!n) return;
  n.textContent = msg;
  clearTimeout(noteTimer);
  noteTimer = setTimeout(() => {
    n.textContent = "";
  }, 2500);
}

function focusControl(cid) {
  const n = document.querySelector(`#deckRoot .dk-ctl[data-cid="${CSS.escape(cid)}"]`);
  if (n) n.focus();
}

function selectControl(cid) {
  emit("control:open", cid);
  paintSelection();
}

/** Swap the page bindings of two keys (what the page shows; global bindings stay where they are). */
function swapKeys(a, b) {
  if (!a || !b || a === b) return;
  snapshotBeforeAction();
  const ea = pageEntry(a);
  const eb = pageEntry(b);
  setEntry(a, eb, "page");
  setEntry(b, ea, "page");
  renderDeck();
  scheduleAutosave();
  if (state.selectedControl === a || state.selectedControl === b) emit("control:open", state.selectedControl);
}

/** Keys after `cid` (wrapping), row by row. */
function keysFrom(cid) {
  const ids = keyIds();
  const i = Math.max(0, ids.indexOf(cid));
  return [...ids.slice(i), ...ids.slice(0, i)];
}

function duplicateKey(cid) {
  const e = displayEntry(cid);
  if (!keyCoord(cid) || !isFilled(e)) return;
  const target = keysFrom(cid)
    .slice(1)
    .find((c) => !isFilled(displayEntry(c)));
  if (!target) {
    note(t("deck.no_free_key"));
    return;
  }
  snapshotBeforeAction();
  setEntry(target, deepCloneJson(e), "page");
  renderDeck();
  scheduleAutosave();
  selectControl(target);
  focusControl(target);
  note(t("deck.duplicated", { number: keyNumber(target) }));
}

function isFileDrag(ev) {
  return !!ev.dataTransfer && Array.from(ev.dataTransfer.types || []).includes("Files");
}

/** Audio files dropped on an empty key: upload to the sound library, one `sound.play` key per file
 * (the first on the drop target, the next ones on the following empty keys), labelled with the clean name. */
async function dropSoundFiles(cid, files) {
  const audio = files.filter(isAudioFile);
  if (!audio.length) {
    note(t("sound.picker.not_audio"));
    return;
  }
  const free = keysFrom(cid).filter((c, i) => i === 0 || !isFilled(displayEntry(c)));
  try {
    let made = 0;
    for (const file of audio.slice(0, free.length)) {
      const rel = await uploadSoundFile(file);
      const target = free[made];
      if (isFilled(displayEntry(target))) continue;
      snapshotBeforeAction();
      setEntry(target, { action: { type: "sound.play", file: rel }, text: cleanSoundName(file.name) }, "page");
      made += 1;
      renderDeck();
      scheduleAutosave();
    }
    if (made) {
      selectControl(free[0]);
      note(t("sound.deck.created", { count: made }));
    }
  } catch (e) {
    note(String((e && e.message) || e));
  }
}

function clearKey(cid) {
  if (!keyCoord(cid) || !pageEntry(cid)) return;
  snapshotBeforeAction();
  setEntry(cid, null, "page");
  renderDeck();
  scheduleAutosave();
  selectControl(cid);
  focusControl(cid);
}

function moveSelection(cid, key) {
  const at = keyCoord(cid);
  if (!at) return;
  const d = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[key];
  const next = `key_${at[0] + d[0]}_${at[1] + d[1]}`;
  if (!document.querySelector(`#deckRoot .dk-key[data-cid="${next}"]`)) return;
  selectControl(next);
  focusControl(next);
}

function switchToPage(i) {
  const sel = $("#pageSelect");
  if (!sel || i === state.pageIndex || i >= (state.cfg.pages || []).length) return;
  sel.value = String(i);
  sel.dispatchEvent(new Event("change", { bubbles: true }));
}

/** cid currently being dragged, or null when no drag is in progress. */
let draggingCid = null;

function bindKey(node) {
  const cid = node.dataset.cid;
  node.addEventListener("click", (ev) => {
    if (draggingCid) return;
    if (ev.target.closest(".dk-dup")) return;
    selectControl(cid);
  });
  node.addEventListener("keydown", (ev) => {
    if (ev.target !== node) return;
    if (ev.key === "Enter" || ev.key === " ") {
      ev.preventDefault();
      selectControl(cid);
    } else if (ev.key.startsWith("Arrow") && keyCoord(cid)) {
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
  const dup = node.querySelector(".dk-dup");
  if (dup) {
    dup.addEventListener("click", (ev) => {
      ev.stopPropagation();
      duplicateKey(cid);
    });
  }
  if (!keyCoord(cid)) return;
  node.addEventListener("dragstart", (ev) => {
    draggingCid = cid;
    ev.dataTransfer.effectAllowed = "move";
    ev.dataTransfer.setData("text/plain", cid);
    node.classList.add("dragging");
  });
  node.addEventListener("dragend", () => {
    draggingCid = null;
    node.classList.remove("dragging");
    document.querySelectorAll("#deckRoot .drag-over").forEach((c) => c.classList.remove("drag-over"));
  });
  node.addEventListener("dragover", (ev) => {
    if (draggingCid) {
      if (cid === draggingCid) return;
      ev.preventDefault();
      ev.dataTransfer.dropEffect = "move";
      node.classList.add("drag-over");
    } else if (isFileDrag(ev) && !isFilled(displayEntry(cid))) {
      // Audio files dropped from the desktop onto an empty key create sound keys (see dropSoundFiles).
      ev.preventDefault();
      ev.dataTransfer.dropEffect = "copy";
      node.classList.add("drag-over");
    }
  });
  node.addEventListener("dragleave", () => node.classList.remove("drag-over"));
  node.addEventListener("drop", (ev) => {
    node.classList.remove("drag-over");
    if (draggingCid) {
      if (cid === draggingCid) return;
      ev.preventDefault();
      const source = draggingCid;
      draggingCid = null;
      swapKeys(source, cid);
    } else if (isFileDrag(ev)) {
      ev.preventDefault();
      if (!isFilled(displayEntry(cid))) void dropSoundFiles(cid, Array.from(ev.dataTransfer.files));
    }
  });
}

function bindStage(stage) {
  stage.querySelectorAll(".dk-key").forEach(bindKey);
  stage.querySelectorAll("button.dk-ctl").forEach((n) => {
    n.addEventListener("click", () => {
      const cid = n.dataset.cid;
      // A button that opens a page shows that page (as on the device) and opens its settings.
      if (n.dataset.page) switchToPage(Number(n.dataset.page));
      selectControl(cid);
    });
  });
}

/* ---- knob feedback overlay ------------------------------------------------------------------- */

const flashes = new Map();

function drawFlash(cid) {
  const face = document.querySelector(`#deckRoot .dk-key[data-cid="${CSS.escape(cid)}"] .dk-face`);
  const f = flashes.get(cid);
  if (!face) return;
  let ov = face.querySelector(".dk-flash");
  if (!f) {
    if (ov) ov.remove();
    return;
  }
  if (!ov) {
    ov = mk("div", "dk-flash");
    ov.setAttribute("aria-hidden", "true");
    face.appendChild(ov);
  }
  ov.textContent = f.text;
}

export function flashKnob(knobId, text) {
  const cid = feedbackKeyFor(knobId);
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

let stageModel = null;

/** Size the stage to the deck's width (and keep captions only where they are readable). */
function fitStage() {
  const root = $("#deckRoot");
  const stage = root && root.querySelector(".dk-stage");
  if (!stage || !stageModel) return;
  const avail = root.clientWidth || 600;
  const u = fitUnit(stageModel, avail, Infinity, { min: MIN_UNIT, max: MAX_UNIT });
  stage.style.setProperty("--u", `${u.toFixed(2)}px`);
  const wrap = stage.parentElement;
  wrap.classList.toggle("is-pannable", stage.offsetWidth > root.clientWidth + 1);
  scrollSelectionIntoView(wrap);
}

/** On a panning deck, keep the selected control in view. */
function scrollSelectionIntoView(wrap) {
  if (!wrap || !wrap.classList.contains("is-pannable") || !state.selectedControl) return;
  const n = wrap.querySelector(`.dk-ctl[data-cid="${CSS.escape(state.selectedControl)}"]`);
  if (!n) return;
  const left = n.offsetLeft;
  const right = left + n.offsetWidth;
  if (left < wrap.scrollLeft) wrap.scrollLeft = Math.max(0, left - 12);
  else if (right > wrap.scrollLeft + wrap.clientWidth) wrap.scrollLeft = right - wrap.clientWidth + 12;
}

function footer() {
  const foot = mk("div", "dk-foot");
  const hint = mk("p", "dk-hint", t("deck.hint"));
  const chip = mk("button", "dk-model");
  chip.type = "button";
  const connected = state.deviceInfo && state.deviceInfo.source === "device";
  chip.append(mk("i", connected ? "is-on" : ""), mk("span", "", state.model.name));
  chip.title = connected ? t("deck.model.connected") : t("deck.model.change");
  chip.addEventListener("click", () => goToService("device"));
  foot.append(hint, chip);
  return foot;
}

export function renderDeck() {
  ensurePages();
  ensureDevice();
  const root = $("#deckRoot");
  if (!root) return;
  const model = state.model;
  if (!model) {
    root.replaceChildren(mk("p", "dk-hint", t("deck.loading")));
    return;
  }
  stageModel = model;
  const stage = mk("div", "dk-stage");
  stage.setAttribute("role", "group");
  stage.setAttribute("aria-label", t("deck.aria", { model: model.name, page: pageName(state.pageIndex) }));
  stage.style.setProperty("--lw", model.layout.width);
  stage.style.setProperty("--lh", model.layout.height);
  stage.style.setProperty("--pad", PAD);
  const bedRect = keyBed(model);
  if (bedRect) {
    const bed = mk("div", "dk-bed");
    placeAt(bed, bedRect);
    stage.append(bed);
  }
  for (const ctl of visualOrder(model.controls)) {
    const node = controlNode(ctl);
    if (!node) continue;
    placeAt(node, ctl.position);
    node.dataset.kind = ctl.kind;
    stage.append(node);
  }
  const note = mk("p", "dk-note");
  note.id = "deckNote";
  note.setAttribute("role", "status");
  note.setAttribute("aria-live", "polite");
  const wrap = mk("div", "dk-stage-wrap");
  wrap.append(stage);
  root.replaceChildren(wrap, mk("p", "dk-pan-hint", t("deck.pan_hint")), footer(), note);
  fitStage();
  bindStage(stage);
  stage.querySelectorAll(".dk-key").forEach(loadKey);
  for (const cid of flashes.keys()) drawFlash(cid);
  paintSelection();
}

/** Redraw only the keys whose look depends on a service connection (status poll: no flicker). */
function refreshLiveKeys() {
  document.querySelectorAll("#deckRoot .dk-key").forEach((n) => {
    const e = displayEntry(n.dataset.cid);
    if (!isFilled(e)) return;
    const { hash } = previewRequest(n.dataset.cid, e);
    if (hash !== n.dataset.hash) loadKey(n);
  });
}

on("status:updated", (st) => {
  const obs = !(st && st.obs && st.obs.configured && !st.obs.connected);
  const ha = !(st && st.ha && st.ha.configured && !st.ha.connected);
  const changed = obs !== conn.obs || ha !== conn.ha;
  conn.obs = obs;
  conn.ha = ha;
  if (changed) refreshLiveKeys();
  paintSelection();
});
on("knob:flash", (p) => {
  if (p && p.knobId) flashKnob(p.knobId, p.text);
});
document.addEventListener("i18n:change", () => {
  if (state.cfg && state.cfg.pages) renderDeck();
});
window.__flashKnob = flashKnob;

const ro = typeof ResizeObserver === "function" ? new ResizeObserver(() => fitStage()) : null;
document.addEventListener("DOMContentLoaded", () => {
  const root = $("#deckRoot");
  if (root && ro) ro.observe(root);
});
window.addEventListener("resize", fitStage);

// Selection is owned by the inspector (it may reset it after a render), so the deck follows state
// with a cheap diff instead of trusting call order.
let paintedSelection;
setInterval(() => {
  if (document.hidden || paintedSelection === state.selectedControl) return;
  paintedSelection = state.selectedControl;
  paintSelection();
}, 150);
