/* Loupedeck page editor — Loupedeck Live vs Live S layouts */

const TOUCH_LIVE = Array.from({ length: 12 }, (_, i) => `touch_${i}`);
const TOUCH_LIVE_S = Array.from({ length: 15 }, (_, i) => `touch_${i}`);
const BTNS_LIVE = [...Array.from({ length: 7 }, (_, i) => `btn_${i + 1}`), "btn_circle"];
const BTNS_LIVE_S = ["btn_circle", "btn_1", "btn_2", "btn_3"];
/** Loupedeck Live S: any number of touch pages; btn_circle + btn_1–btn_3 switch indices 0–3 on device (LED color only in UI). */
const KNOBS_LIVE = ["knobTL", "knobCL", "knobBL", "knobTR", "knobCR", "knobBR"];
const VIDEO_EXT = new Set([".mp4", ".webm", ".mov", ".m4v", ".ogv", ".avi", ".mkv"]);
const SOUND_UPLOAD_EXT = new Set([".wav", ".mp3", ".ogg", ".flac", ".m4a", ".opus", ".aac"]);
const FONT_UPLOAD_EXT = new Set([".ttf", ".otf", ".ttc"]);
/** GIF, static images, and video — key graphic or deck background */
const DECK_MEDIA_EXT = new Set([
  ".gif",
  ".png",
  ".jpg",
  ".jpeg",
  ".webp",
  ...VIDEO_EXT,
]);

/** Target ``library`` for POST /api/upload from a chosen File (extension-based). */
function uploadLibraryParamForFile(file) {
  if (!file || !file.name) return "images";
  const low = file.name.toLowerCase();
  const dot = low.lastIndexOf(".");
  const ext = dot >= 0 ? low.slice(dot) : "";
  if (VIDEO_EXT.has(ext)) return "videos";
  if (SOUND_UPLOAD_EXT.has(ext)) return "sounds";
  if (FONT_UPLOAD_EXT.has(ext)) return "fonts";
  return "images";
}

// --- Undo/redo: client-side, session-only (cleared on page reload). ------------------------

const UNDO_STACK_MAX = 50;
const undoStack = [];
const redoStack = [];
/** True while a keystroke-driven edit session is "open" (since the field was focused) — batches
 * an entire typing burst into a single undo step instead of one per keystroke. Reset on focusout. */
let undoSnapshotPendingForFocus = false;
/** True while applying an undo/redo snapshot, so that doing so does not itself get pushed. */
let applyingUndoRedo = false;

function pushUndoSnapshot() {
  if (applyingUndoRedo) return;
  try {
    undoStack.push(JSON.stringify({ cfg, pageIndex }));
  } catch {
    return;
  }
  if (undoStack.length > UNDO_STACK_MAX) undoStack.shift();
  redoStack.length = 0;
}

/** Use for discrete one-shot actions (click a button, drop a drag) — always pushes. */
function snapshotBeforeAction() {
  pushUndoSnapshot();
  undoSnapshotPendingForFocus = false;
}

/** Use inside keystroke-driven "input"/"change" handlers — pushes once per focus session. */
function snapshotBeforeEditOnce() {
  if (undoSnapshotPendingForFocus) return;
  pushUndoSnapshot();
  undoSnapshotPendingForFocus = true;
}

function applyCfgSnapshot(json) {
  const prevPageIndex = pageIndex;
  applyingUndoRedo = true;
  try {
    const parsed = JSON.parse(json);
    cfg = parsed.cfg;
    pageIndex = parsed.pageIndex;
  } finally {
    applyingUndoRedo = false;
  }
  ensurePages();
  ensureDevice();
  ensureLogging();
  ensureHa();
  ensureObs();
  ensureTwitch();
  ensureGlobalButtons();
  if (pageIndex >= cfg.pages.length) pageIndex = Math.max(0, cfg.pages.length - 1);
  syncSpotifyFromCfg();
  syncLoggingFromCfg();
  syncHaFromCfg();
  syncObsFromCfg();
  renderTwitchAccounts();
  syncPageSelect();
  renderDeck();
  if (selectedControl) openEditor(selectedControl);
  scheduleAutosave();
  if (pageIndex !== prevPageIndex) syncAgentPageIndex();
}

function currentUndoSnapshot() {
  return JSON.stringify({ cfg, pageIndex });
}

function undo() {
  if (undoStack.length === 0) return;
  const current = currentUndoSnapshot();
  const snapshot = undoStack.pop();
  redoStack.push(current);
  applyCfgSnapshot(snapshot);
}

function redo() {
  if (redoStack.length === 0) return;
  const current = currentUndoSnapshot();
  const snapshot = redoStack.pop();
  undoStack.push(current);
  applyCfgSnapshot(snapshot);
}

function wireUndoRedoKeyboard() {
  document.addEventListener("keydown", (e) => {
    if (!(e.ctrlKey || e.metaKey) || e.key.toLowerCase() !== "z") return;
    e.preventDefault();
    if (e.shiftKey) redo();
    else undo();
  });
  // Any field losing focus ends the current keystroke-batching session.
  document.addEventListener(
    "focusout",
    () => {
      undoSnapshotPendingForFocus = false;
    },
    true,
  );
}

function switchTab(name) {
  stopKeySequenceRecording();
  const panels = { buttons: $("#tabPanelButtons"), services: $("#tabPanelServices") };
  const buttons = { buttons: $("#tabBtnButtons"), services: $("#tabBtnServices") };
  for (const key of Object.keys(panels)) {
    if (panels[key]) panels[key].hidden = key !== name;
    if (buttons[key]) buttons[key].setAttribute("aria-selected", key === name ? "true" : "false");
  }
}

function wireTabBar() {
  const btnButtons = $("#tabBtnButtons");
  const btnServices = $("#tabBtnServices");
  if (btnButtons) btnButtons.addEventListener("click", () => switchTab("buttons"));
  if (btnServices) btnServices.addEventListener("click", () => switchTab("services"));
}

function layoutMode() {
  const m = (cfg.device && cfg.device.model) || "auto";
  if (m === "live") return "live";
  if (m === "live_s") return "live_s";
  if (agentDeckLayout === "live") return "live";
  if (agentDeckLayout === "live_s") return "live_s";
  return "live_s";
}

function isLiveSModel() {
  return layoutMode() === "live_s";
}

function isLiveSPageSwitchButton(cid) {
  return isLiveSModel() && typeof cid === "string" && BTNS_LIVE_S.includes(cid);
}

function liveKnobEncoderIds() {
  return layoutMode() === "live_s" ? ["knobTL", "knobCL"] : [...KNOBS_LIVE];
}

function isKnobEncoderId(cid) {
  return typeof cid === "string" && liveKnobEncoderIds().includes(cid);
}

/** @type {string | null} */
let selectedKnobEncoder = null;
/** Unique id prefix for knob rotate action field rows (asset browse, etc.). */
let knobRotateFieldSeq = 0;

function knobKeys(k) {
  return [`${k}_left`, `${k}_right`, k];
}

let cfg = {};
/** Resolved from GET /api/status when device.model is "auto" ("live" | "live_s" | null). */
let agentDeckLayout = null;
let actionCatalog = [];
let pageIndex = 0;
let selectedControl = null;
/** touch_{n} -> error string for current page (from /api/status). */
let touchErrors = {};
/** Clipboard for copy/paste between controls (entry JSON). */
let copiedControlEntry = null;
let copiedControlMeta = null;
/** When advanced JSON matches this (after trim), Apply uses the form instead of the textarea. */
let lastSyncedAdv = "";
/** Blob URLs for deck key previews (revoked on each re-render). */
const deckPreviewUrls = [];
/** Incremented each renderDeck; stale hydrateKeyPreviews completions are ignored. */
let deckPreviewGeneration = 0;
let sidebarPreviewUrl = null;
/** Media background controllers to stop on rerender. */
const deckMediaBgStops = [];

/** False until initial load finishes, so we do not PUT empty/partial state. */
let suppressAutosave = true;
let autosaveTimer = null;

const $ = (s) => document.querySelector(s);

function setSaveStatus(text, isError = false) {
  const el = $("#saveStatus");
  if (!el) return;
  el.textContent = text || "";
  el.classList.toggle("save-status-error", !!isError);
}

function scheduleAutosave() {
  if (suppressAutosave) return;
  clearTimeout(autosaveTimer);
  setSaveStatus("Pending…");
  autosaveTimer = setTimeout(() => {
    void runAutosave();
  }, 500);
}

async function runAutosave() {
  $("#saveError").textContent = "";
  setSaveStatus("Saving…");
  try {
    await apiPut(cfg);
    setSaveStatus("Saved");
    return true;
  } catch (e) {
    const msg = String(e);
    $("#saveError").textContent = msg;
    setSaveStatus("Save failed", true);
    return false;
  }
}

async function backupConfig() {
  $("#saveError").textContent = "";
  clearTimeout(autosaveTimer);
  autosaveTimer = null;
  const saved = await runAutosave();
  if (!saved) return;
  try {
    const r = await fetch("/api/config/backup", { method: "POST" });
    if (!r.ok) throw new Error(await r.text());
    const j = await r.json();
    const files = j.files || [];
    const names = files.map((f) => f.name).join(", ");
    setSaveStatus(names ? `Backup: ${names}` : "Backup created");
    void refreshBackupsList();
  } catch (e) {
    $("#saveError").textContent = String(e);
    setSaveStatus("Backup failed", true);
  }
}

async function refreshBackupsList() {
  const mount = $("#backupsListMount");
  if (!mount) return;
  try {
    const r = await fetch("/api/config/backups");
    if (!r.ok) return;
    const j = await r.json();
    const rows = j.backups || [];
    if (!rows.length) {
      mount.innerHTML = '<p class="hint small">No backups yet — one is taken automatically on each launch.</p>';
      return;
    }
    mount.innerHTML = "";
    for (const b of rows) {
      const when = new Date(b.mtime * 1000).toLocaleString();
      const kb = Math.round(b.bytes / 102.4) / 10;
      const row = document.createElement("div");
      row.className = "backup-row";
      const nameEl = document.createElement("span");
      nameEl.className = "backup-name";
      nameEl.textContent = b.name;
      const metaEl = document.createElement("span");
      metaEl.className = "backup-meta";
      metaEl.textContent = `${when} · ${kb} KB`;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = "Restore";
      btn.addEventListener("click", () => void restoreBackupByName(b.name));
      row.appendChild(nameEl);
      row.appendChild(metaEl);
      row.appendChild(btn);
      mount.appendChild(row);
    }
  } catch {
    /* best-effort */
  }
}

async function restoreBackupByName(name) {
  if (!confirm(`Restore config from "${name}"? This overwrites the current configuration (Ctrl+Z can undo it).`)) {
    return;
  }
  $("#saveError").textContent = "";
  try {
    const r = await fetch("/api/config/backups/restore", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    if (!r.ok) throw new Error(await r.text());
    const j = await r.json();
    snapshotBeforeAction();
    const restoredPageCount = (j.config.pages || []).length;
    applyCfgSnapshot(
      JSON.stringify({ cfg: j.config, pageIndex: Math.max(0, Math.min(pageIndex, restoredPageCount - 1)) }),
    );
    selectedControl = null;
    closeKnobEncoderEditor();
    setSaveStatus(`Restored from ${name}`);
    void refreshBackupsList();
  } catch (e) {
    $("#saveError").textContent = String(e);
    setSaveStatus("Restore failed", true);
  }
}

async function wipeBackupsConfig() {
  $("#saveError").textContent = "";
  if (
    !confirm(
      "Remove all rotating config backups on disk? The current editor config will be saved first; only the main YAML file will remain."
    )
  ) {
    return;
  }
  clearTimeout(autosaveTimer);
  autosaveTimer = null;
  const saved = await runAutosave();
  if (!saved) return;
  try {
    const r = await fetch("/api/config/backups/wipe", { method: "POST" });
    if (!r.ok) throw new Error(await r.text());
    const j = await r.json();
    const n = j.count ?? 0;
    setSaveStatus(n ? `Removed ${n} backup file(s)` : "No backup files to remove");
    void refreshBackupsList();
  } catch (e) {
    $("#saveError").textContent = String(e);
    setSaveStatus("Remove backups failed", true);
  }
}

async function resetConfigToDefaults() {
  $("#saveError").textContent = "";
  if (
    !confirm(
      "Reset touch-page layout to defaults?\n\nThis will reset the deck pages/buttons layout and delete config backups. Other settings (e.g. Spotify) will be preserved."
    )
  ) {
    return;
  }
  clearTimeout(autosaveTimer);
  autosaveTimer = null;
  setSaveStatus("Resetting…");
  try {
    const r = await fetch("/api/config/reset", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirm: true }),
    });
    if (!r.ok) throw new Error(await r.text());
    const j = await r.json();
    cfg = await apiGet();
    suppressAutosave = true;
    ensureDevice();
    try {
      const sr = await fetch("/api/status");
      if (sr.ok) {
        const sj = await sr.json();
        if (sj.deck_layout === "live" || sj.deck_layout === "live_s") {
          agentDeckLayout = sj.deck_layout;
        } else {
          agentDeckLayout = null;
        }
        ensurePages();
        if (typeof sj.page_index === "number") {
          syncUiToAgentPage(sj.page_index);
        }
      } else {
        ensurePages();
      }
    } catch {
      ensurePages();
    }
    updateLiveSPageChrome();
    syncSpotifyFromCfg();
    ensureLogging();
    syncLoggingFromCfg();
    $("#pageName").textContent = currentPage().name || `Page ${pageIndex + 1}`;
    const pnR = $("#pageNameInput");
    if (pnR) pnR.value = currentPage().name || "";
    syncPageSelect();
    renderDeck();
    syncKnobPagesEditor();
    suppressAutosave = false;
    setSaveStatus("Reset ok");
    await refreshSkin();
  } catch (e) {
    $("#saveError").textContent = String(e);
    setSaveStatus("Reset failed", true);
  }
}

function hasTactileGraphic(e) {
  if (!e) return false;
  const t = (e.text && String(e.text).trim()) || (e.label && String(e.label).trim());
  return !!(e.image || e.icon || t || e.background || e.background_gradient_from || mediaPathForEntry(e));
}

/** True if the key has a PNG preview (tactile) or a Live S physical LED color. */
function hasRenderableVisual(e) {
  if (!e) return false;
  if (hasTactileGraphic(e)) return true;
  const bc = e.button_color && String(e.button_color).trim();
  return !!(bc && layoutMode() === "live_s");
}

function isLiveSPhysicalButton(cid) {
  return layoutMode() === "live_s" && typeof cid === "string" && BTNS_LIVE_S.includes(cid);
}

/** Normalize to #rrggbb or return "". */
function sanitizeButtonColorHex(s) {
  const t = String(s || "").trim();
  if (/^#[0-9A-Fa-f]{6}$/i.test(t)) return `#${t.slice(1).toLowerCase()}`;
  if (/^#[0-9A-Fa-f]{3}$/i.test(t)) {
    const r = t[1],
      g = t[2],
      b = t[3];
    return `#${r}${r}${g}${g}${b}${b}`.toLowerCase();
  }
  return "";
}

function normalizeHex6ForPicker(s) {
  const x = sanitizeButtonColorHex(s);
  return x || "#202028";
}

/** Safe CSS color for LED preview (hex or simple named color). */
function cssColorForLedPreview(raw) {
  const s = String(raw || "").trim();
  if (!s) return "#555555";
  const h = sanitizeButtonColorHex(s);
  if (h) return h;
  if (/^[a-zA-Z][a-zA-Z0-9]*$/.test(s)) return s;
  return "#555555";
}

function syncLiveSButtonColorBlock(cid, e) {
  const block = $("#liveSButtonColorBlock");
  const picker = $("#buttonColorPicker");
  const hex = $("#buttonColorHex");
  const lab = $("#liveSButtonColorLabel");
  if (!block || !picker || !hex) return;
  if (!isLiveSPhysicalButton(cid)) {
    block.hidden = true;
    return;
  }
  block.hidden = false;
  if (lab && isLiveSPageSwitchButton(cid)) {
    const n = BTNS_LIVE_S.indexOf(cid) + 1;
    lab.textContent = `Page ${n} button — LED color`;
  } else if (lab) {
    lab.textContent = "Physical button LED (Live S)";
  }
  const raw = (e && e.button_color && String(e.button_color).trim()) || "";
  if (!raw) {
    picker.value = "#202028";
    hex.value = "#202028";
    return;
  }
  const hexOk = sanitizeButtonColorHex(raw);
  if (hexOk) {
    picker.value = hexOk;
    hex.value = hexOk;
  } else {
    hex.value = raw;
    picker.value = "#808080";
  }
}

function wireButtonColorInputs() {
  const picker = $("#buttonColorPicker");
  const hex = $("#buttonColorHex");
  if (!picker || !hex) return;
  picker.addEventListener("input", () => {
    hex.value = picker.value;
    scheduleSidebarPreviewRefresh();
  });
  hex.addEventListener("input", () => {
    const s = sanitizeButtonColorHex(hex.value);
    if (s) picker.value = s;
    scheduleSidebarPreviewRefresh();
  });
}

// Pairs a native <input type="color"> swatch with a free-text hex field: either one can drive
// the other, and both changes refresh the live sidebar preview (design section: text/background
// solid colors and gradient endpoints).
function wireColorPairInputs(pickerId, hexId) {
  const picker = $(pickerId);
  const hex = $(hexId);
  if (!picker || !hex) return;
  picker.addEventListener("input", () => {
    hex.value = picker.value;
    scheduleSidebarPreviewRefresh();
  });
  hex.addEventListener("input", () => {
    const s = sanitizeButtonColorHex(hex.value);
    if (s) picker.value = s;
    scheduleSidebarPreviewRefresh();
  });
}

const DESIGN_COLOR_PAIRS = [
  ["#textColorPicker", "#textColor"],
  ["#backgroundColorPicker", "#backgroundColor"],
  ["#textGradientFromPicker", "#textGradientFrom"],
  ["#textGradientToPicker", "#textGradientTo"],
  ["#backgroundGradientFromPicker", "#backgroundGradientFrom"],
  ["#backgroundGradientToPicker", "#backgroundGradientTo"],
  ["#pressFlashColorPicker", "#pressFlashColor"],
];

function syncDesignAnimationFieldVisibility() {
  const idleType = ($("#idleAnimation") && $("#idleAnimation").value) || "none";
  const speedRow = $("#idleAnimationSpeedRow");
  if (speedRow) speedRow.hidden = idleType === "none";

  const pressType = ($("#pressAnimation") && $("#pressAnimation").value) || "none";
  const dirRow = $("#pressAnimationDirectionRow");
  if (dirRow) dirRow.hidden = pressType !== "slide_reappear";
  const flashRow = $("#pressFlashColorRow");
  if (flashRow) flashRow.hidden = pressType !== "flash";
}

function wireDesignFieldInputs() {
  for (const [pickerId, hexId] of DESIGN_COLOR_PAIRS) wireColorPairInputs(pickerId, hexId);

  const plainInputIds = ["#textGradientAngle", "#backgroundGradientAngle", "#idleAnimationSpeed"];
  for (const id of plainInputIds) {
    const el = $(id);
    if (el) el.addEventListener("input", () => scheduleSidebarPreviewRefresh());
  }

  const idleSel = $("#idleAnimation");
  if (idleSel) {
    idleSel.addEventListener("change", () => {
      syncDesignAnimationFieldVisibility();
      scheduleSidebarPreviewRefresh();
    });
  }
  const pressSel = $("#pressAnimation");
  if (pressSel) {
    pressSel.addEventListener("change", () => {
      syncDesignAnimationFieldVisibility();
      scheduleSidebarPreviewRefresh();
    });
  }
  const pressDirSel = $("#pressAnimationDirection");
  if (pressDirSel) pressDirSel.addEventListener("change", () => scheduleSidebarPreviewRefresh());

  const btnPreviewPress = $("#btnPreviewPress");
  if (btnPreviewPress) btnPreviewPress.addEventListener("click", () => void previewPressAnimation());
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

function visualEntryForPreview(e) {
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

// Reads the gradient/idle/press fields from the form into `target` (mutated and returned).
// Shared by draftVisualEntryFromForm() (live preview) and saveAction() (persisted config).
function readDesignFieldsFromForm(target) {
  const tgFrom = ($("#textGradientFrom") && $("#textGradientFrom").value.trim()) || "";
  const tgTo = ($("#textGradientTo") && $("#textGradientTo").value.trim()) || "";
  if (tgFrom && tgTo) {
    target.text_gradient_from = tgFrom;
    target.text_gradient_to = tgTo;
    const angle = ($("#textGradientAngle") && $("#textGradientAngle").value.trim()) || "";
    if (angle) target.text_gradient_angle = Number(angle);
  }

  const bgFrom = ($("#backgroundGradientFrom") && $("#backgroundGradientFrom").value.trim()) || "";
  const bgTo = ($("#backgroundGradientTo") && $("#backgroundGradientTo").value.trim()) || "";
  if (bgFrom && bgTo) {
    target.background_gradient_from = bgFrom;
    target.background_gradient_to = bgTo;
    const angle = ($("#backgroundGradientAngle") && $("#backgroundGradientAngle").value.trim()) || "";
    if (angle) target.background_gradient_angle = Number(angle);
  }

  const idleType = ($("#idleAnimation") && $("#idleAnimation").value) || "none";
  if (idleType !== "none") {
    target.idle_animation = idleType;
    const speed = ($("#idleAnimationSpeed") && $("#idleAnimationSpeed").value.trim()) || "";
    if (speed) target.idle_animation_speed = Number(speed);
  }

  const pressType = ($("#pressAnimation") && $("#pressAnimation").value) || "none";
  if (pressType !== "none") {
    target.press_animation = pressType;
    if (pressType === "slide_reappear") {
      const dir = ($("#pressAnimationDirection") && $("#pressAnimationDirection").value) || "left";
      if (dir !== "left") target.press_animation_direction = dir;
    }
    if (pressType === "flash") {
      const col = ($("#pressFlashColor") && $("#pressFlashColor").value.trim()) || "";
      if (col) target.press_flash_color = col;
    }
  }
  return target;
}

// Populates the design-section form fields from a stored/loaded button entry (mirror of
// readDesignFieldsFromForm). Pass {} to reset to defaults (e.g. Live S page-switch buttons).
function populateDesignFieldsFromEntry(e) {
  const ent = e || {};
  const setVal = (id, v) => {
    const el = $(id);
    if (el) el.value = v;
  };
  setVal("#textGradientFrom", ent.text_gradient_from || "");
  setVal("#textGradientTo", ent.text_gradient_to || "");
  setVal("#textGradientAngle", ent.text_gradient_angle != null ? String(ent.text_gradient_angle) : "");
  setVal("#backgroundGradientFrom", ent.background_gradient_from || "");
  setVal("#backgroundGradientTo", ent.background_gradient_to || "");
  setVal(
    "#backgroundGradientAngle",
    ent.background_gradient_angle != null ? String(ent.background_gradient_angle) : "",
  );
  setVal("#idleAnimation", ent.idle_animation || "none");
  setVal("#idleAnimationSpeed", ent.idle_animation_speed != null ? String(ent.idle_animation_speed) : "");
  setVal("#pressAnimation", ent.press_animation || "none");
  setVal("#pressAnimationDirection", ent.press_animation_direction || "left");
  setVal("#pressFlashColor", ent.press_flash_color || "");
  for (const [pickerId, hexId] of DESIGN_COLOR_PAIRS) {
    const hex = $(hexId);
    const picker = $(pickerId);
    if (!hex || !picker) continue;
    const s = sanitizeButtonColorHex(hex.value);
    picker.value = s || "#808080";
  }
  syncDesignAnimationFieldVisibility();
}

let sidebarPreviewDebounce = null;

function draftVisualEntryFromForm() {
  if (selectedControl && isLiveSPageSwitchButton(selectedControl)) {
    const e = {};
    const raw = ($("#buttonColorHex") && $("#buttonColorHex").value.trim()) || "";
    if (raw) {
      const bc = sanitizeButtonColorHex(raw);
      e.button_color = bc || raw;
    }
    return e;
  }
  const e = {};
  const txt = ($("#buttonText") && $("#buttonText").value.trim()) || "";
  if (txt) e.text = txt;
  const icon = ($("#iconUri") && $("#iconUri").value.trim()) || "";
  const img = ($("#imagePath") && $("#imagePath").value.trim()) || "";
  if (icon) e.icon = icon;
  if (img) e.image = img;
  const tc = $("#textColor") && $("#textColor").value.trim();
  if (tc) e.text_color = tc;
  const bg = $("#backgroundColor") && $("#backgroundColor").value.trim();
  if (bg) e.background = bg;
  const fs = $("#fontSize") && $("#fontSize").value.trim();
  if (fs) e.font_size = Number(fs);
  const ff = ($("#fontFilePath") && $("#fontFilePath").value.trim()) || "";
  if (ff) e.font_file = ff;
  const hasG = !!(icon || img);
  const hasT = !!txt;
  if (hasG && hasT) {
    const lo = $("#graphicTextLayout");
    e.graphic_text_layout = (lo && lo.value) || "split";
  }
  if (selectedControl && isLiveSPhysicalButton(selectedControl) && !isLiveSPageSwitchButton(selectedControl)) {
    const hx = $("#buttonColorHex");
    const raw = hx && hx.value.trim();
    if (raw) {
      const bc = sanitizeButtonColorHex(raw);
      e.button_color = bc || raw;
    }
  }
  readDesignFieldsFromForm(e);
  return e;
}

function syncGraphicLayoutVisibility() {
  const block = $("#graphicLayoutBlock");
  if (!block) return;
  const icon = ($("#iconUri") && $("#iconUri").value.trim()) || "";
  const img = ($("#imagePath") && $("#imagePath").value.trim()) || "";
  const txt = ($("#buttonText") && $("#buttonText").value.trim()) || "";
  block.hidden = !(txt && (icon || img));
}

function scheduleSidebarPreviewRefresh() {
  if (!selectedControl) return;
  clearTimeout(sidebarPreviewDebounce);
  sidebarPreviewDebounce = setTimeout(() => {
    syncGraphicLayoutVisibility();
    const draft = draftVisualEntryFromForm();
    void updatePreviewFromEntry(draft, selectedControl);
    maybeStartSidebarAnimPreview(draft, selectedControl);
  }, 320);
}

function revokeDeckPreviewUrls() {
  for (const u of deckPreviewUrls) URL.revokeObjectURL(u);
  deckPreviewUrls.length = 0;
}

function stopDeckMediaBackgrounds() {
  for (const stop of deckMediaBgStops.splice(0)) {
    try {
      stop();
    } catch {
      /* ignore */
    }
  }
}

function extOfPath(p) {
  const s = String(p || "").trim().toLowerCase();
  const base = s.split("?")[0].split("#")[0];
  const i = base.lastIndexOf(".");
  if (i < 0) return "";
  return base.slice(i);
}

function mediaPathForEntry(entry) {
  if (!entry || typeof entry !== "object") return null;
  const pick = (raw) => {
    const s = raw && String(raw).trim();
    if (!s) return null;
    const ex = extOfPath(s);
    if (DECK_MEDIA_EXT.has(ex)) return s;
    return null;
  };
  const fromImg = pick(entry.image);
  if (fromImg) return fromImg;
  const ic = entry.icon && String(entry.icon).trim();
  if (ic && !isIconUri(ic)) {
    const fromIcon = pick(ic);
    if (fromIcon) return fromIcon;
  }
  const act0 =
    Array.isArray(entry.actions) &&
    entry.actions.length > 0 &&
    entry.actions[0] &&
    typeof entry.actions[0] === "object"
      ? entry.actions[0]
      : null;
  const act = entry.action && typeof entry.action === "object" ? entry.action : null;
  const overlay =
    act0 && act0.type === "overlay.show_media"
      ? act0
      : act && act.type === "overlay.show_media"
        ? act
        : null;
  if (overlay) {
    const p = (overlay.file || overlay.path) && String(overlay.file || overlay.path).trim();
    return pick(p);
  }
  return null;
}

function localFileUrl(relPath) {
  return `/api/local-file?path=${encodeURIComponent(String(relPath || ""))}`;
}

function revokeSidebarPreview() {
  if (sidebarPreviewUrl) {
    URL.revokeObjectURL(sidebarPreviewUrl);
    sidebarPreviewUrl = null;
  }
}

function isIconUri(s) {
  const t = String(s || "").trim();
  return /^(si:|simpleicons:|heroicons:|lucide:|mdi:|https?:\/\/)/i.test(t);
}

function splitIconAndImage(e) {
  let icon = (e && e.icon) || "";
  let image = (e && e.image) || "";
  if (!icon && image && isIconUri(image)) {
    icon = image;
    image = "";
  }
  return { icon, image };
}

async function apiGet() {
  const r = await fetch("/api/config");
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

async function apiPut(body) {
  const r = await fetch("/api/config", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

function syncSpotifyFromCfg() {
  const sp = (cfg && cfg.spotify) || {};
  const cid = $("#spotifyClientId");
  const redir = $("#spotifyRedirectUri");
  if (cid) cid.value = sp.client_id || "";
  if (redir) {
    redir.value = sp.redirect_uri || `${window.location.origin}/api/spotify/callback`;
  }
}

function ensureTwitch() {
  const t = cfg && cfg.twitch;
  if (Array.isArray(t)) {
    cfg.twitch = t.filter((x) => x && typeof x === "object");
    return;
  }
  if (t && typeof t === "object") {
    cfg.twitch = [t];
    return;
  }
  cfg.twitch = [];
}

function escapeAttr(s) {
  return escapeHtml(String(s || "")).replace(/\"/g, "&quot;");
}

function renderTwitchAccounts() {
  ensureTwitch();
  const mount = $("#twitchAccountsMount");
  if (!mount) return;
  const rows = cfg.twitch || [];
  if (!rows.length) {
    mount.innerHTML = `<p class="hint small">No Twitch accounts configured.</p>`;
    return;
  }
  mount.innerHTML = rows
    .map((acct, i) => {
      const a = acct && typeof acct === "object" ? acct : {};
      const cid = a.client_id || "";
      const cs = a.client_secret || "";
      const tok = a.access_token || "";
      return `
        <fieldset class="twitch-acct" data-ix="${i}">
          <legend>Account ${i + 1}${cid ? ` — ${escapeHtml(String(cid).slice(0, 10))}…` : ""}</legend>
          <label class="row">Client ID</label>
          <input class="full-width mono" data-tw="client_id" value="${escapeAttr(cid)}" spellcheck="false" />
          <label class="row">Client secret</label>
          <input type="password" class="full-width mono" data-tw="client_secret" value="${escapeAttr(cs)}" />
          <label class="row">Access token (optional)</label>
          <input type="password" class="full-width mono" data-tw="access_token" value="${escapeAttr(tok)}" />
          <div class="row-actions">
            <button type="button" class="btnRemoveTwitchAccount">Remove</button>
          </div>
        </fieldset>`;
    })
    .join("");

  mount.querySelectorAll("input[data-tw]").forEach((el) => {
    el.addEventListener("input", () => {
      const fs = el.closest(".twitch-acct");
      if (!fs) return;
      const ix = Number(fs.dataset.ix);
      const key = el.dataset.tw;
      if (!Number.isFinite(ix) || !cfg.twitch[ix]) return;
      cfg.twitch[ix][key] = el.value;
      scheduleAutosave();
    });
  });
  mount.querySelectorAll(".btnRemoveTwitchAccount").forEach((btn) => {
    btn.addEventListener("click", () => {
      const fs = btn.closest(".twitch-acct");
      if (!fs) return;
      const ix = Number(fs.dataset.ix);
      if (!Number.isFinite(ix)) return;
      cfg.twitch.splice(ix, 1);
      renderTwitchAccounts();
      scheduleAutosave();
    });
  });
}

async function refreshSpotifyStatus() {
  const line = $("#spotifyStatusLine");
  try {
    const r = await fetch("/api/spotify/status");
    if (!r.ok) {
      if (line) line.textContent = "";
      return;
    }
    const j = await r.json();
    if (!line) return;
    if (!j.configured) {
      line.textContent =
        "Not configured: enter Client ID and Redirect URI, then Save Spotify settings.";
    } else if (!j.connected) {
      line.textContent = "Configured — not connected. Click Connect with Spotify.";
    } else {
      line.textContent = j.user ? `Connected as ${j.user}.` : "Connected.";
    }
  } catch {
    if (line) line.textContent = "";
  }
}

async function saveSpotifySettings() {
  const errEl = $("#spotifyErrorLine");
  if (errEl) {
    errEl.hidden = true;
    errEl.textContent = "";
  }
  try {
    const r = await fetch("/api/spotify/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        client_id: ($("#spotifyClientId") && $("#spotifyClientId").value.trim()) || "",
        redirect_uri: ($("#spotifyRedirectUri") && $("#spotifyRedirectUri").value.trim()) || "",
      }),
    });
    if (!r.ok) throw new Error(await r.text());
    const j = await r.json();
    if (!cfg.spotify) cfg.spotify = {};
    Object.assign(cfg.spotify, j.spotify || {});
    await refreshSpotifyStatus();
  } catch (e) {
    if (errEl) {
      errEl.hidden = false;
      errEl.textContent = String(e);
    }
  }
}

function handleSpotifyReturnQuery() {
  const params = new URLSearchParams(window.location.search);
  const errEl = $("#spotifyErrorLine");
  if (params.get("spotify") === "connected") {
    const next = window.location.pathname + (window.location.hash || "");
    history.replaceState({}, "", next);
    void refreshSpotifyStatus();
  }
  const err = params.get("spotify_error");
  if (err) {
    const next = window.location.pathname + (window.location.hash || "");
    history.replaceState({}, "", next);
    if (errEl) {
      errEl.hidden = false;
      errEl.textContent = err;
    }
  }
}

async function refreshSkin() {
  await fetch("/api/refresh_skin", { method: "POST" });
}

function clampPageIndex(agentIndex) {
  ensurePages();
  const n = cfg.pages.length;
  if (n === 0) return 0;
  if (typeof agentIndex !== "number" || !Number.isFinite(agentIndex)) return pageIndex;
  return ((Math.floor(agentIndex) % n) + n) % n;
}

/**
 * After we change the page ourselves (click a rail item, add/remove/reorder a page), ignore the
 * status poll's reported page_index for this long (ms). The poll can race a local change from
 * either direction — a response already in flight when we click, computed against the pre-click
 * server state, or (with a real device) a POST that takes a while to return because the agent
 * waits for the physical redraw — and blindly trusting it snaps the UI back to the old page for a
 * moment before a later poll corrects it forward again (a visible flicker). A flat cooldown is
 * simpler and more robust than trying to track exactly which in-flight request a given poll
 * result predates. Once it elapses, a poll reporting a different page again (e.g. a genuine
 * physical button press) is applied normally.
 */
const PAGE_INDEX_POLL_COOLDOWN_MS = 2000;
let pageIndexPollMutedUntil = 0;

function muteAgentPagePollBriefly() {
  pageIndexPollMutedUntil = Date.now() + PAGE_INDEX_POLL_COOLDOWN_MS;
}

function syncUiToAgentPage(agentIndex) {
  if (Date.now() < pageIndexPollMutedUntil) return;
  const target = clampPageIndex(agentIndex);
  const changed = target !== pageIndex;
  pageIndex = target;
  const sel = $("#pageSelect");
  if (sel) sel.value = String(pageIndex);
  $("#pageName").textContent = currentPage().name || `Page ${pageIndex + 1}`;
  const pn = $("#pageNameInput");
  if (pn) pn.value = currentPage().name || "";
  if (changed) {
    renderDeck();
    renderPageRail();
    selectedControl = null;
    const sl = $("#selLabel");
    if (sl) sl.textContent = "Select a control";
    syncTestPressButton();
    syncCopyPasteButtons();
  }
}

async function postAgentPageIndex(ix) {
  const r = await fetch("/api/page_index", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ index: ix }),
  });
  if (!r.ok) throw new Error(await r.text());
}

/** Loupedeck Live side strips are not represented as discrete keys in the agent (no synthetic message). */
function controlCanSimulate(cid) {
  if (!cid || typeof cid !== "string") return false;
  if (cid === "strip_left" || cid === "strip_right") return false;
  return true;
}

function syncTestPressButton() {
  const btn = $("#btnTestPress");
  if (!btn) return;
  const ok = controlCanSimulate(selectedControl);
  btn.disabled = !selectedControl || !ok;
  btn.title = ok
    ? "Run the same action as a physical press on this control (no USB)"
    : "Side strips are not simulated (hardware uses touch coordinates)";
}

function deepCloneJson(v) {
  return v == null ? null : JSON.parse(JSON.stringify(v));
}

function loadCopiedControlFromStorage() {
  try {
    const raw = localStorage.getItem("ld_clipboard_control_v1");
    if (!raw) return;
    const j = JSON.parse(raw);
    if (!j || typeof j !== "object") return;
    if (j.entry && typeof j.entry === "object") copiedControlEntry = j.entry;
    if (j.meta && typeof j.meta === "object") copiedControlMeta = j.meta;
  } catch {
    /* ignore */
  }
}

function saveCopiedControlToStorage() {
  try {
    localStorage.setItem(
      "ld_clipboard_control_v1",
      JSON.stringify({ entry: copiedControlEntry, meta: copiedControlMeta })
    );
  } catch {
    /* ignore */
  }
}

function canPasteToControl(cid) {
  if (!cid || typeof cid !== "string") return false;
  if (cid === "strip_left" || cid === "strip_right") return false;
  return true;
}

function syncCopyPasteButtons() {
  const bCopy = $("#btnCopyControl");
  const bPaste = $("#btnPasteControl");
  if (bCopy) bCopy.disabled = !selectedControl || !getButtonEntry(selectedControl);
  if (bPaste) {
    const ok = !!selectedControl && !!copiedControlEntry && canPasteToControl(selectedControl);
    bPaste.disabled = !ok;
  }
}

async function postSimulatePress(controlId, direction) {
  const body = { control_id: controlId };
  if (direction === "left" || direction === "right") body.direction = direction;
  const r = await fetch("/api/simulate_press", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    let detail = r.statusText;
    try {
      const j = await r.json();
      if (j.detail !== undefined) {
        detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
      }
    } catch {
      try {
        detail = await r.text();
      } catch {
        /* ignore */
      }
    }
    throw new Error(detail || `HTTP ${r.status}`);
  }
  return r.json();
}

let statusPollTimer = null;

function setConnBadge(el, mode, text) {
  if (!el) return;
  el.textContent = text;
  el.classList.remove("ok", "offline", "muted");
  el.classList.add(mode);
}

async function refreshConnectionStatus() {
  const usbBadge = document.getElementById("stUsbBadge");
  const usbPath = document.getElementById("stUsbPath");
  const obsBadge = document.getElementById("stObsBadge");
  const obsMeta = document.getElementById("stObsMeta");
  const haBadge = document.getElementById("stHaBadge");
  const haMeta = document.getElementById("stHaMeta");
  if (!usbBadge || !obsBadge) return;
  try {
    const r = await fetch("/api/status");
    if (!r.ok) return;
    const j = await r.json();
    const usb = j.usb || {};
    if (usb.disabled) {
      setConnBadge(usbBadge, "muted", "Disabled");
      if (usbPath) usbPath.textContent = "";
    } else if (usb.connected) {
      setConnBadge(usbBadge, "ok", "Connected");
      if (usbPath) usbPath.textContent = usb.path || usb.detail || "";
    } else {
      setConnBadge(usbBadge, "offline", "Offline");
      if (usbPath) usbPath.textContent = usb.path || usb.detail || "";
    }

    const obs = j.obs || {};
    if (!obs.configured) {
      setConnBadge(obsBadge, "muted", "Not configured");
      if (obsMeta) obsMeta.textContent = "";
    } else if (obs.connected) {
      setConnBadge(obsBadge, "ok", "Connected");
      if (obsMeta) obsMeta.textContent = obs.url || "";
    } else {
      setConnBadge(obsBadge, "offline", "Offline");
      if (obsMeta) obsMeta.textContent = obs.url || obs.detail || "";
    }

    if (haBadge) {
      const ha = j.ha || {};
      if (!ha.configured) {
        setConnBadge(haBadge, "muted", "Not configured");
        if (haMeta) haMeta.textContent = "";
      } else if (ha.connected) {
        setConnBadge(haBadge, "ok", "Connected");
        if (haMeta) haMeta.textContent = ha.url || "";
      } else {
        setConnBadge(haBadge, "offline", "Offline");
        if (haMeta) haMeta.textContent = ha.url || ha.detail || "";
      }
    }

    const prevLayout = agentDeckLayout;
    if (j.deck_layout === "live" || j.deck_layout === "live_s") {
      agentDeckLayout = j.deck_layout;
    } else {
      agentDeckLayout = null;
    }
    if (prevLayout !== agentDeckLayout) {
      ensurePages();
      updateLiveSPageChrome();
      syncPageSelect();
    }

    if (typeof j.page_index === "number") {
      syncUiToAgentPage(j.page_index);
    }
    touchErrors = j.touch_errors && typeof j.touch_errors === "object" ? j.touch_errors : {};
    // Update outlines without waiting for a full re-render.
    document.querySelectorAll(".cell").forEach((el) => {
      const cid = el && el.dataset && el.dataset.cid;
      if (cid && typeof cid === "string" && cid.startsWith("touch_") && touchErrors[cid]) {
        el.classList.add("error-outline");
        el.title = `${cid} — ${touchErrors[cid]}`;
      } else if (el) {
        el.classList.remove("error-outline");
      }
    });
  } catch {
    setConnBadge(usbBadge, "muted", "…");
    setConnBadge(obsBadge, "muted", "…");
    if (haBadge) setConnBadge(haBadge, "muted", "…");
  }
}

function startConnectionStatusPolling() {
  if (!document.getElementById("connBar")) return;
  void refreshConnectionStatus();
  if (statusPollTimer) clearInterval(statusPollTimer);
  statusPollTimer = setInterval(refreshConnectionStatus, 1500);
}

function ensurePages() {
  if (!Array.isArray(cfg.pages)) cfg.pages = [];
  if (isLiveSModel()) {
    if (cfg.pages.length === 0) {
      cfg.pages.push({ id: 0, name: "Page 1", buttons: {} });
    }
    cfg.pages.forEach((p, i) => {
      if (!p || typeof p !== "object") {
        cfg.pages[i] = { id: i, name: `Page ${i + 1}`, buttons: {} };
        return;
      }
      p.id = i;
      if (!p.name) p.name = `Page ${i + 1}`;
      if (!p.buttons || typeof p.buttons !== "object") p.buttons = {};
    });
    if (pageIndex >= cfg.pages.length) pageIndex = Math.max(0, cfg.pages.length - 1);
  } else if (cfg.pages.length === 0) {
    cfg.pages = [{ name: "Page 1", buttons: {} }];
  }
}

function updateLiveSPageChrome() {
  const hint = $(".page-rail-hint");
  if (hint) {
    hint.title = isLiveSModel()
      ? "On the device, circle + btn 1–3 only switch among page indices 0–3 (first four pages)."
      : "";
  }
  const nameIn = $("#pageNameInput");
  if (nameIn) nameIn.hidden = false;
}

function syncKeyEditorPageSwitchMode(cid) {
  const pageSwitch = !!cid && isLiveSPageSwitchButton(cid);
  const def = $("#keyEditorDefaultHint");
  const psh = $("#keyEditorPageSwitchHint");
  const act = $("#keyEditorActionAndAdv");
  const tg = $("#keyEditorTouchGraphicFields");
  const prev = $("#keyEditorPreviewHint");
  if (def) def.hidden = pageSwitch;
  if (psh) psh.hidden = !pageSwitch;
  if (act) act.hidden = pageSwitch;
  if (tg) tg.hidden = pageSwitch;
  if (prev) prev.hidden = pageSwitch;
}

function ensureDevice() {
  if (!cfg.device) cfg.device = { path: "", baudrate: null, model: "auto" };
  if (cfg.device.model == null) cfg.device.model = "auto";
}

function ensureLogging() {
  if (!cfg.logging || typeof cfg.logging !== "object") {
    cfg.logging = { dir: "", level: "INFO", file: true, console: true };
  }
  if (cfg.logging.level == null || String(cfg.logging.level).trim() === "") {
    cfg.logging.level = "INFO";
  }
}

function syncLoggingFromCfg() {
  const sel = $("#logLevel");
  if (!sel) return;
  let lv = String(cfg.logging && cfg.logging.level ? cfg.logging.level : "INFO").trim().toUpperCase();
  const allowed = new Set(["DEBUG", "INFO", "WARNING", "WARN", "ERROR", "CRITICAL"]);
  if (!allowed.has(lv)) lv = "INFO";
  sel.value = lv;
}

/** Generic field validators, shared by Services fields and (later) the button editor. */
const FIELD_VALIDATORS = {
  hexColor: (v) => /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.test(v.trim()),
  port: (v) => {
    const n = Number(v.trim());
    return Number.isInteger(n) && n >= 1 && n <= 65535;
  },
  nonEmpty: (v) => v.trim().length > 0,
};

/**
 * Wire an input/select/textarea for "smart" autosave: validate on every keystroke, never persist
 * an invalid value (red outline instead), commit on blur immediately, commit on valid input after
 * the normal debounce. `validate` returns true/false or an error string; `onCommit(value)` applies
 * the value to `cfg` (the caller still triggers scheduleAutosave()/runAutosave()).
 */
function wireSmartField(el, { validate, onCommit, optional = true }) {
  if (!el) return;
  const check = (raw) => {
    if (optional && raw.trim() === "") return true;
    const res = validate(raw);
    return res === undefined ? true : res;
  };
  const applyValidity = (raw) => {
    const res = check(raw);
    const ok = res === true;
    el.classList.toggle("field-invalid", !ok);
    el.title = ok ? "" : typeof res === "string" ? res : "Invalid value";
    return ok;
  };
  el.addEventListener("input", () => {
    const raw = el.value;
    if (applyValidity(raw)) {
      snapshotBeforeEditOnce();
      onCommit(raw);
      scheduleAutosave();
    } else {
      clearTimeout(autosaveTimer);
      autosaveTimer = null;
    }
  });
  el.addEventListener("blur", () => {
    const raw = el.value;
    if (applyValidity(raw)) {
      onCommit(raw);
      clearTimeout(autosaveTimer);
      autosaveTimer = null;
      void runAutosave();
    }
  });
}

function ensureHa() {
  if (!cfg.ha || typeof cfg.ha !== "object") {
    cfg.ha = { base_url: "", token: "" };
  }
}

function syncHaFromCfg() {
  ensureHa();
  const urlEl = $("#haBaseUrl");
  const tokEl = $("#haToken");
  if (urlEl) urlEl.value = cfg.ha.base_url || "";
  if (tokEl) tokEl.value = cfg.ha.token || "";
}

function ensureObs() {
  if (!cfg.obs || typeof cfg.obs !== "object") {
    cfg.obs = { host: "127.0.0.1", port: 4455, password: "" };
  }
}

function syncObsFromCfg() {
  ensureObs();
  const hostEl = $("#obsHost");
  const portEl = $("#obsPort");
  const pwEl = $("#obsPassword");
  if (hostEl) hostEl.value = cfg.obs.host || "";
  if (portEl) portEl.value = cfg.obs.port != null ? String(cfg.obs.port) : "";
  if (pwEl) pwEl.value = cfg.obs.password || "";
}

function ensureGlobalButtons() {
  if (!cfg.global_buttons || typeof cfg.global_buttons !== "object") {
    cfg.global_buttons = {};
  }
}

/** Center touch keys are per-page; knobs, strips, and physical side buttons use ``global_buttons``. */
function isPageScopedControl(cid) {
  return typeof cid === "string" && cid.startsWith("touch_");
}

function removeControlFromAllPages(cid) {
  ensurePages();
  for (const p of cfg.pages) {
    if (p.buttons && Object.prototype.hasOwnProperty.call(p.buttons, cid)) {
      delete p.buttons[cid];
    }
  }
}

function currentPage() {
  ensurePages();
  return cfg.pages[pageIndex];
}

function getButtonEntry(cid) {
  ensurePages();
  ensureGlobalButtons();
  if (isPageScopedControl(cid)) {
    const p = currentPage();
    if (!p.buttons) p.buttons = {};
    return p.buttons[cid] || null;
  }
  if (cfg.global_buttons[cid]) {
    return cfg.global_buttons[cid];
  }
  const p = currentPage();
  if (!p.buttons) p.buttons = {};
  return p.buttons[cid] || null;
}

function setButtonEntry(cid, entry) {
  ensurePages();
  ensureGlobalButtons();
  if (isPageScopedControl(cid)) {
    const p = currentPage();
    if (!p.buttons) p.buttons = {};
    if (entry == null) delete p.buttons[cid];
    else p.buttons[cid] = entry;
  } else {
    if (entry == null) {
      delete cfg.global_buttons[cid];
      removeControlFromAllPages(cid);
    } else {
      cfg.global_buttons[cid] = entry;
      removeControlFromAllPages(cid);
    }
  }
}

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

function knobPageLabelFromConfig(page) {
  if (!page || typeof page !== "object") return "";
  return String(page.name || page.page_change_message || page.message || "").trim();
}

function parseRotateValueForUi(val) {
  if (val == null || val === "") return { mode: "empty" };
  if (Array.isArray(val)) {
    if (val.length === 0) return { mode: "empty" };
    if (
      val.length === 1 &&
      val[0] &&
      typeof val[0] === "object" &&
      !Array.isArray(val[0]) &&
      val[0].type
    ) {
      return { mode: "form", action: val[0] };
    }
    try {
      return { mode: "json", text: JSON.stringify(val, null, 2) };
    } catch {
      return { mode: "empty" };
    }
  }
  if (typeof val === "object" && val !== null && val.type) {
    return { mode: "form", action: val };
  }
  try {
    return { mode: "json", text: JSON.stringify(val, null, 2) };
  } catch {
    return { mode: "empty" };
  }
}

function appendKnobRotateUI(fs, side, rotateVal) {
  const parsed = parseRotateValueForUi(rotateVal);
  const wrap = document.createElement("div");
  wrap.className = `knob-rot-side knob-rot-${side}`;

  const lab = document.createElement("label");
  lab.className = "row";
  lab.textContent = side === "left" ? "Rotate left" : "Rotate right";
  wrap.appendChild(lab);

  const sel = document.createElement("select");
  sel.className = `full-width knob-rot-type-${side}`;
  const curType =
    parsed.mode === "form" && parsed.action && parsed.action.type ? String(parsed.action.type) : "";
  populateKnobActionSelect(sel, curType);
  enhanceActionTypeSelect(sel, knobCompatibleActionList());

  const fields = document.createElement("div");
  fields.className = `knob-rot-fields-${side} knob-rot-fields`;

  const adv = document.createElement("details");
  adv.className = "knob-rot-json-details";
  const sum = document.createElement("summary");
  sum.textContent = "Advanced: JSON (arrays or multiple actions)";
  const taAdv = document.createElement("textarea");
  taAdv.className = `mono full-width knob-rot-json-${side}`;
  taAdv.rows = 4;
  taAdv.spellcheck = false;
  adv.appendChild(sum);
  adv.appendChild(taAdv);

  if (parsed.mode === "json") {
    taAdv.value = parsed.text;
    adv.open = true;
  } else if (parsed.mode === "form" && parsed.action) {
    const act = parsed.action;
    sel.value = act.type || "";
    if (sel._refreshActionSelectTrigger) sel._refreshActionSelectTrigger();
    const prefix = `kr${++knobRotateFieldSeq}`;
    renderActionFieldsInto(fields, sel.value, prefix);
    fillActionFieldsInContainer(fields, act, sel.value);
  }

  sel.addEventListener("change", () => {
    const prefix = `kr${++knobRotateFieldSeq}`;
    renderActionFieldsInto(fields, sel.value, prefix);
    taAdv.value = "";
    adv.open = false;
  });

  wrap.appendChild(sel);
  wrap.appendChild(fields);
  wrap.appendChild(adv);
  fs.appendChild(wrap);
}

function collectRotateSide(fs, side) {
  const label = side === "left" ? "Rotate left" : "Rotate right";
  const ta = fs.querySelector(`.knob-rot-json-${side}`);
  if (ta && ta.value.trim()) {
    try {
      return JSON.parse(ta.value.trim());
    } catch (e) {
      throw new Error(`${label} (JSON): ${e.message || e}`);
    }
  }
  const sel = fs.querySelector(`.knob-rot-type-${side}`);
  const fields = fs.querySelector(`.knob-rot-fields-${side}`);
  const type = sel && sel.value;
  if (!type) return undefined;
  try {
    return buildActionFromFormIn(fields, type);
  } catch (e) {
    throw new Error(`${label}: ${e.message || e}`);
  }
}

function showKeyEditorPanel() {
  const k = $("#keyEditorBlock");
  const kn = $("#knobEncoderEditorBlock");
  if (k) k.hidden = false;
  if (kn) kn.hidden = true;
}

function renumberKnobPageLegends() {
  const mount = $("#knobEncoderPagesMount");
  if (!mount) return;
  mount.querySelectorAll(".knob-page-fieldset").forEach((fs, i) => {
    const n = fs.querySelector(".knob-page-num");
    if (n) n.textContent = String(i + 1);
  });
}

function addKnobEncoderPageRow(page) {
  const mount = $("#knobEncoderPagesMount");
  if (!mount) return;
  const p = page && typeof page === "object" ? page : {};
  const leftVal = p.rotate_left ?? p.left;
  const rightVal = p.rotate_right ?? p.right;

  const fs = document.createElement("fieldset");
  fs.className = "knob-page-fieldset";
  const leg = document.createElement("legend");
  leg.append("Page ");
  const numSpan = document.createElement("span");
  numSpan.className = "knob-page-num";
  leg.appendChild(numSpan);
  fs.appendChild(leg);

  const labN = document.createElement("label");
  labN.className = "row";
  labN.textContent = "Page name (shown on touch when you push to select this page)";
  fs.appendChild(labN);
  const nameIn = document.createElement("input");
  nameIn.type = "text";
  nameIn.className = "full-width knob-page-name";
  nameIn.value = knobPageLabelFromConfig(p);
  fs.appendChild(nameIn);

  appendKnobRotateUI(fs, "left", leftVal);
  appendKnobRotateUI(fs, "right", rightVal);

  const rm = document.createElement("button");
  rm.type = "button";
  rm.className = "btn-remove-knob-page";
  rm.textContent = "Remove this page";
  fs.appendChild(rm);

  mount.appendChild(fs);
  renumberKnobPageLegends();
}

function renderKnobEncoderForm(knobId) {
  const mount = $("#knobEncoderPagesMount");
  if (!mount) return;
  mount.innerHTML = "";
  const spec = cfg.knob_pages && cfg.knob_pages[knobId];
  const pages = spec && Array.isArray(spec.pages) ? spec.pages.filter((x) => x && typeof x === "object") : [];
  if (pages.length === 0) {
    addKnobEncoderPageRow({});
  } else {
    for (const pg of pages) {
      addKnobEncoderPageRow(pg);
    }
  }
}

function collectKnobEncoderPagesFromDom() {
  const mount = $("#knobEncoderPagesMount");
  if (!mount) return [];
  const out = [];
  for (const fs of mount.querySelectorAll(".knob-page-fieldset")) {
    const name = (fs.querySelector(".knob-page-name") && fs.querySelector(".knob-page-name").value.trim()) || "";
    const rotate_left = collectRotateSide(fs, "left");
    const rotate_right = collectRotateSide(fs, "right");
    if (!name && rotate_left === undefined && rotate_right === undefined) continue;
    const o = {};
    if (name) o.name = name;
    if (rotate_left !== undefined) o.rotate_left = rotate_left;
    if (rotate_right !== undefined) o.rotate_right = rotate_right;
    out.push(o);
  }
  return out;
}

function openKnobEncoderEditor(kid) {
  stopSidebarAnimPreview();
  selectedKnobEncoder = kid;
  selectedControl = null;
  const k = $("#keyEditorBlock");
  const kn = $("#knobEncoderEditorBlock");
  if (k) k.hidden = true;
  if (kn) kn.hidden = false;
  const title = $("#knobEncoderTitle");
  if (title) title.textContent = `Encoder: ${kid}`;
  const err = $("#knobEncoderError");
  if (err) err.textContent = "";
  const dur = $("#knobFeedbackDurationSec");
  if (dur) {
    const d = cfg.knob_page_feedback && cfg.knob_page_feedback.duration_sec;
    dur.value =
      d != null && !Number.isNaN(Number(d))
        ? String(Math.max(0.3, Math.min(2, Number(d))))
        : "2";
  }
  renderKnobEncoderForm(kid);
  syncKnobPagesEditor();
  syncTestPressButton();
}

function closeKnobEncoderEditor() {
  selectedKnobEncoder = null;
  showKeyEditorPanel();
  const sl = $("#selLabel");
  if (sl) sl.textContent = "Select a control";
  syncTestPressButton();
  syncCopyPasteButtons();
}

function knobEncoderSummaryHtml(knobId) {
  const spec = cfg.knob_pages && cfg.knob_pages[knobId];
  const pages = spec && Array.isArray(spec.pages) ? spec.pages.filter((x) => x && typeof x === "object") : [];
  if (pages.length === 0) {
    return `<span class="knob-encoder-summary muted">No pages — click to configure</span>`;
  }
  const first = knobPageLabelFromConfig(pages[0]) || "(unnamed)";
  const extra = pages.length > 1 ? ` +${pages.length - 1} more` : "";
  return `<span class="knob-encoder-summary">${escapeHtml(first.slice(0, 28))}${escapeHtml(extra)}</span>`;
}

function knobEncoderCellHtml(knobId) {
  return `
    <div class="cell knob-encoder-cell knob-dial has-action" data-cid="${escapeHtml(knobId)}" title="${escapeHtml(
      knobId
    )} — dial pages">
      <div class="knob-dial-ring" aria-hidden="true"></div>
      <div class="knob-encoder-body">
        <span class="knob-encoder-id">${escapeHtml(knobId)}</span>
        ${knobEncoderSummaryHtml(knobId)}
      </div>
      <div class="cell-footer">
        <span class="cid">${escapeHtml(knobId)}</span>
        <span class="cell-act">dial pages</span>
      </div>
    </div>`;
}

function getSpec(type) {
  return actionCatalog.find((a) => a.type === type) || null;
}

/** Resolve a catalog field control inside an action-fields container (data-param + id suffix fallback). */
function actionFieldEl(container, field) {
  if (!container || !field || field.name == null) return null;
  const name = String(field.name);
  const esc =
    typeof CSS !== "undefined" && typeof CSS.escape === "function"
      ? CSS.escape(name)
      : name.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
  let el = container.querySelector(`[data-param="${esc}"]`);
  if (el) return el;
  const suf = name.replace(/[^a-zA-Z0-9_]/g, "_");
  return container.querySelector(`input[id$="_${suf}"],select[id$="_${suf}"],textarea[id$="_${suf}"]`);
}

function populateActionTypeSelect() {
  const sel = $("#actionType");
  if (!sel) return;
  sel.innerHTML = "";
  const o0 = document.createElement("option");
  o0.value = "";
  o0.textContent = "— No action —";
  sel.appendChild(o0);
  for (const a of actionCatalog) {
    const o = document.createElement("option");
    o.value = a.type;
    o.textContent = a.label || a.type;
    sel.appendChild(o);
  }
  enhanceActionTypeSelect(sel, actionCatalog);
}

/* ---------------------------------------------------------------------------------------------
 * Categorized action-type picker: click the trigger for a list of categories (OBS, Spotify, ...);
 * hovering (or clicking, for touch) a category flies out a submenu of that category's actions.
 * The underlying <select> stays the single source of truth — picking an item just sets its value
 * and dispatches "change", so every existing consumer (form rendering, autosave, knob rotate
 * wiring, ...) keeps working unchanged. Reused for both the main action-type select and each
 * knob's rotate-left/rotate-right selects.
 * ------------------------------------------------------------------------------------------- */

let openActionSelectPanel = null; // { wrap, panel, trigger }
let actionSelectGlobalListenersInstalled = false;

function closeOpenActionSelectPanel() {
  if (!openActionSelectPanel) return;
  const cur = openActionSelectPanel;
  openActionSelectPanel = null;
  cur.panel.remove(); // body-appended (see openPanel) — must detach, not just hide
  cur.trigger.setAttribute("aria-expanded", "false");
}

function ensureActionSelectGlobalListeners() {
  if (actionSelectGlobalListenersInstalled) return;
  actionSelectGlobalListenersInstalled = true;
  document.addEventListener("click", (e) => {
    if (
      openActionSelectPanel &&
      !openActionSelectPanel.wrap.contains(e.target) &&
      !openActionSelectPanel.panel.contains(e.target)
    ) {
      closeOpenActionSelectPanel();
    }
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && openActionSelectPanel) closeOpenActionSelectPanel();
  });
  // The editor panel this lives in scrolls internally (overflow: auto); "scroll" does not bubble,
  // so this must be capture-phase on window to see it and keep the (fixed-positioned) dropdown
  // from visually drifting away from its trigger. Scrolling *inside* the dropdown's own panel
  // (long category lists) must not close it -- only scrolling some other ancestor should.
  window.addEventListener(
    "scroll",
    (e) => {
      if (openActionSelectPanel && !openActionSelectPanel.panel.contains(e.target)) {
        closeOpenActionSelectPanel();
      }
    },
    true,
  );
  window.addEventListener("resize", () => closeOpenActionSelectPanel());
}

/** Split a catalog label like "OBS — set program scene" into ["OBS", "set program scene"]. */
function splitCategoryFromLabel(label) {
  const s = String(label || "");
  const i = s.indexOf(" — ");
  return i === -1 ? null : [s.slice(0, i), s.slice(i + 3)];
}

/**
 * Attach the categorized dropdown UI to an already-populated <select> (main action-type select or
 * a per-knob rotate select). Safe to call more than once on the same element — later calls just
 * refresh the trigger label and item list rather than re-wrapping it.
 * @param {HTMLSelectElement} selectEl
 * @param {{type: string, label: string, category?: string}[]} items
 */
function enhanceActionTypeSelect(selectEl, items) {
  if (!selectEl) return;
  selectEl._actionSelectItems = items;
  if (selectEl._refreshActionSelectTrigger) {
    selectEl._refreshActionSelectTrigger();
    return;
  }

  const wrap = document.createElement("div");
  wrap.className = "action-select";
  selectEl.parentNode.insertBefore(wrap, selectEl);
  wrap.appendChild(selectEl);
  selectEl.classList.add("action-select-native");
  selectEl.tabIndex = -1;

  const trigger = document.createElement("button");
  trigger.type = "button";
  trigger.className = "action-select-trigger";
  trigger.setAttribute("aria-haspopup", "true");
  trigger.setAttribute("aria-expanded", "false");
  wrap.appendChild(trigger);

  function currentLabel() {
    const t = selectEl.value;
    if (!t) return "— No action —";
    const found = (selectEl._actionSelectItems || []).find((i) => i.type === t);
    return (found && found.label) || t;
  }

  function refreshTrigger() {
    trigger.textContent = currentLabel();
  }
  selectEl._refreshActionSelectTrigger = refreshTrigger;
  refreshTrigger();

  function pick(type) {
    selectEl.value = type;
    refreshTrigger();
    closeOpenActionSelectPanel();
    selectEl.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function groupByCategory() {
    const groups = new Map();
    for (const it of selectEl._actionSelectItems || []) {
      const cat = it.category || splitCategoryFromLabel(it.label)?.[0] || "Other";
      if (!groups.has(cat)) groups.set(cat, []);
      groups.get(cat).push(it);
    }
    return groups;
  }

  function itemLabel(it) {
    const split = splitCategoryFromLabel(it.label);
    return (split && split[1]) || it.label || it.type;
  }

  // Appended to <body> (not `wrap`) and position: fixed, so it visually escapes the editor
  // panel's `overflow: auto` instead of being clipped at that panel's edge. Categories expand
  // inline (accordion-style) rather than flying out sideways: a sideways flyout needs the
  // submenu positioned relative to the viewport's right edge, which turned out unreliable in the
  // packaged app's webview (reported: the submenu rendered off-screen, needing horizontal
  // scrolling to reach) -- an inline list only ever needs vertical space, which the panel already
  // scrolls for.
  function openPanel() {
    closeOpenActionSelectPanel();
    ensureActionSelectGlobalListeners();

    const panel = document.createElement("div");
    panel.className = "action-select-panel";

    const noneRow = document.createElement("div");
    noneRow.className = "action-select-item";
    noneRow.textContent = "— No action —";
    if (!selectEl.value) noneRow.classList.add("selected");
    noneRow.addEventListener("click", () => pick(""));
    panel.appendChild(noneRow);

    for (const [cat, groupItems] of groupByCategory()) {
      const isOpenCategory = groupItems.some((it) => it.type === selectEl.value);

      const row = document.createElement("div");
      row.className = "action-select-category";
      if (isOpenCategory) row.classList.add("open");
      const caret = document.createElement("span");
      caret.className = "action-select-caret";
      caret.textContent = isOpenCategory ? "▾" : "▸";
      row.appendChild(caret);
      const catLabel = document.createElement("span");
      catLabel.textContent = cat;
      row.appendChild(catLabel);

      const sublist = document.createElement("div");
      sublist.className = "action-select-sublist";
      sublist.hidden = !isOpenCategory;
      for (const it of groupItems) {
        const subRow = document.createElement("div");
        subRow.className = "action-select-item action-select-subitem";
        subRow.textContent = itemLabel(it);
        if (it.type === selectEl.value) subRow.classList.add("selected");
        subRow.addEventListener("click", (e) => {
          e.stopPropagation();
          pick(it.type);
        });
        sublist.appendChild(subRow);
      }

      row.addEventListener("click", () => {
        const willOpen = sublist.hidden;
        sublist.hidden = !willOpen;
        row.classList.toggle("open", willOpen);
        caret.textContent = willOpen ? "▾" : "▸";
      });

      panel.appendChild(row);
      panel.appendChild(sublist);
    }

    document.body.appendChild(panel);
    const triggerRect = trigger.getBoundingClientRect();
    panel.style.left = `${Math.round(triggerRect.left)}px`;
    panel.style.top = `${Math.round(triggerRect.bottom + 4)}px`;
    panel.style.minWidth = `${Math.round(triggerRect.width)}px`;
    panel.style.maxHeight = `${Math.max(160, window.innerHeight - triggerRect.bottom - 16)}px`;

    trigger.setAttribute("aria-expanded", "true");
    openActionSelectPanel = { wrap, panel, trigger };

    const selectedEl = panel.querySelector(".action-select-item.selected");
    if (selectedEl) selectedEl.scrollIntoView({ block: "nearest" });
  }

  trigger.addEventListener("click", (e) => {
    e.stopPropagation();
    if (openActionSelectPanel && openActionSelectPanel.wrap === wrap) closeOpenActionSelectPanel();
    else openPanel();
  });
}

/** Action types that do not apply to encoder rotation (e.g. display-only overlays). */
function knobCompatibleActionList() {
  return actionCatalog.filter(
    (a) => a && a.type && !String(a.type).startsWith("display.")
  );
}

/**
 * Fill a &lt;select&gt; with action types suitable for knob rotate (excludes display.*).
 * @param {string} [currentType] if set and incompatible, append one option so the value stays visible.
 */
function populateKnobActionSelect(sel, currentType) {
  if (!sel) return;
  sel.innerHTML = "";
  const o0 = document.createElement("option");
  o0.value = "";
  o0.textContent = "— No action —";
  sel.appendChild(o0);
  const list = knobCompatibleActionList();
  for (const a of list) {
    const o = document.createElement("option");
    o.value = a.type;
    o.textContent = a.label || a.type;
    sel.appendChild(o);
  }
  const ct = currentType != null && String(currentType).trim() !== "" ? String(currentType).trim() : "";
  if (ct && !list.some((a) => a.type === ct)) {
    const spec = getSpec(ct);
    if (spec) {
      const ox = document.createElement("option");
      ox.value = ct;
      ox.textContent = `${spec.label || ct} (not for knobs — choose another)`;
      sel.appendChild(ox);
    }
  }
}

/* ---------------------------------------------------------------------------------------------
 * keyboard.play_sequence: "record" widget (keys/key_sequence field).
 *
 * Recording is done entirely in the browser — a document-level keydown listener, installed once,
 * captures real keystrokes while at most one widget instance is "active". Replay (actually
 * sending the keys to the OS) is the agent's job (keyboard_replay.py); this only builds the
 * ordered `steps` list that gets saved as the action's params.
 * ------------------------------------------------------------------------------------------- */

let activeKeySequenceRecorder = null; // { wrapEl, hiddenEl, chipsEl, recordBtn, timeoutId }
let keySequenceGlobalListenerInstalled = false;

function keySequenceStepsFromHidden(hiddenEl) {
  try {
    const v = JSON.parse((hiddenEl && hiddenEl.value) || "[]");
    return Array.isArray(v) ? v : [];
  } catch {
    return [];
  }
}

const KEY_DISPLAY_NAMES = {
  ctrl: "Ctrl",
  alt: "Alt",
  shift: "Shift",
  meta: "Win/⌘",
  tab: "Tab",
  enter: "Enter",
  escape: "Esc",
  esc: "Esc",
  " ": "Space",
  space: "Space",
  arrowup: "↑",
  arrowdown: "↓",
  arrowleft: "←",
  arrowright: "→",
  backspace: "⌫",
  delete: "Del",
};

function keyDisplayName(k) {
  const s = String(k);
  const lower = s.toLowerCase();
  if (KEY_DISPLAY_NAMES[lower]) return KEY_DISPLAY_NAMES[lower];
  return s.length === 1 ? s.toUpperCase() : s;
}

function renderKeySequenceChips(chipsEl, hiddenEl) {
  if (!chipsEl) return;
  const steps = keySequenceStepsFromHidden(hiddenEl);
  chipsEl.innerHTML = "";
  if (steps.length === 0) {
    const empty = document.createElement("span");
    empty.className = "key-sequence-empty";
    empty.textContent = "No keys recorded yet";
    chipsEl.appendChild(empty);
    return;
  }
  steps.forEach((step, i) => {
    const chip = document.createElement("span");
    chip.className = "key-chip";
    const keys = (step && step.keys) || [];
    chip.appendChild(document.createTextNode(keys.map(keyDisplayName).join("+") || "?"));
    const rm = document.createElement("button");
    rm.type = "button";
    rm.className = "key-chip-remove";
    rm.textContent = "×";
    rm.title = "Remove this key";
    rm.addEventListener("click", () => {
      const cur = keySequenceStepsFromHidden(hiddenEl);
      cur.splice(i, 1);
      hiddenEl.value = JSON.stringify(cur);
      renderKeySequenceChips(chipsEl, hiddenEl);
      hiddenEl.dispatchEvent(new Event("input", { bubbles: true }));
    });
    chip.appendChild(rm);
    chipsEl.appendChild(chip);
  });
}

function stopKeySequenceRecording() {
  const rec = activeKeySequenceRecorder;
  if (!rec) return;
  activeKeySequenceRecorder = null;
  if (rec.timeoutId) clearTimeout(rec.timeoutId);
  if (rec.wrapEl) rec.wrapEl.classList.remove("recording");
  if (rec.recordBtn) rec.recordBtn.textContent = "● Record";
}

// Safety net: recording left on by accident (e.g. the user wandered off without clicking Stop)
// must not keep intercepting every keystroke on the page forever.
const KEY_SEQUENCE_RECORD_TIMEOUT_MS = 60000;
const KEY_SEQUENCE_MAX_STEPS = 40;

function startKeySequenceRecording(wrapEl, hiddenEl, chipsEl, recordBtn) {
  stopKeySequenceRecording(); // only one recorder active at a time
  ensureKeySequenceGlobalListener();
  wrapEl.classList.add("recording");
  recordBtn.textContent = "■ Stop";
  activeKeySequenceRecorder = {
    wrapEl,
    hiddenEl,
    chipsEl,
    recordBtn,
    timeoutId: setTimeout(stopKeySequenceRecording, KEY_SEQUENCE_RECORD_TIMEOUT_MS),
  };
}

function ensureKeySequenceGlobalListener() {
  if (keySequenceGlobalListenerInstalled) return;
  keySequenceGlobalListenerInstalled = true;
  // Capture phase: must win the race against other document-level keydown handlers (e.g. the
  // Ctrl+Z undo/redo listener) so recording "Ctrl+Z" as a macro step doesn't also trigger undo.
  document.addEventListener(
    "keydown",
    (ev) => {
      const rec = activeKeySequenceRecorder;
      if (!rec) return;
      ev.preventDefault();
      ev.stopPropagation();
      if (ev.repeat) return; // holding a key down must not spam duplicate steps
      if (["Control", "Alt", "Shift", "Meta"].includes(ev.key)) return; // wait for the real key
      const mods = [];
      if (ev.ctrlKey) mods.push("ctrl");
      if (ev.altKey) mods.push("alt");
      if (ev.metaKey) mods.push("meta");
      // A single printable character already encodes shift in its value (e.g. Shift+a -> "A");
      // only named keys (Tab, arrows, F-keys, ...) need shift tracked as a separate modifier.
      if (ev.shiftKey && String(ev.key).length > 1) mods.push("shift");
      const cur = keySequenceStepsFromHidden(rec.hiddenEl);
      cur.push({ keys: [...mods, ev.key] });
      rec.hiddenEl.value = JSON.stringify(cur);
      renderKeySequenceChips(rec.chipsEl, rec.hiddenEl);
      rec.hiddenEl.dispatchEvent(new Event("input", { bubbles: true }));
      if (cur.length >= KEY_SEQUENCE_MAX_STEPS) stopKeySequenceRecording();
    },
    true,
  );
}

function renderKeySequenceField(wrap, f, idPrefix) {
  const fieldWrap = document.createElement("div");
  fieldWrap.className = "key-sequence-field";

  const hidden = document.createElement("input");
  hidden.type = "hidden";
  hidden.dataset.param = f.name;
  hidden.setAttribute("data-param", String(f.name));
  hidden.id = `${idPrefix}_${String(f.name).replace(/[^a-zA-Z0-9_]/g, "_")}`;
  hidden.value = "[]";

  const chips = document.createElement("div");
  chips.className = "key-sequence-chips";

  const controls = document.createElement("div");
  controls.className = "key-sequence-controls";
  const recordBtn = document.createElement("button");
  recordBtn.type = "button";
  recordBtn.className = "btn-record";
  recordBtn.textContent = "● Record";
  const clearBtn = document.createElement("button");
  clearBtn.type = "button";
  clearBtn.className = "btn-clear-seq";
  clearBtn.textContent = "Clear";

  recordBtn.addEventListener("click", () => {
    if (activeKeySequenceRecorder && activeKeySequenceRecorder.hiddenEl === hidden) {
      stopKeySequenceRecording();
    } else {
      startKeySequenceRecording(fieldWrap, hidden, chips, recordBtn);
    }
  });
  clearBtn.addEventListener("click", () => {
    if (activeKeySequenceRecorder && activeKeySequenceRecorder.hiddenEl === hidden) stopKeySequenceRecording();
    hidden.value = "[]";
    renderKeySequenceChips(chips, hidden);
    hidden.dispatchEvent(new Event("input", { bubbles: true }));
  });
  controls.appendChild(recordBtn);
  controls.appendChild(clearBtn);

  const hint = document.createElement("p");
  hint.className = "hint key-sequence-hint";
  hint.textContent = "Click Record, then press the keys in this window, in order. Click Stop when done.";

  fieldWrap.appendChild(hidden);
  fieldWrap.appendChild(chips);
  fieldWrap.appendChild(controls);
  fieldWrap.appendChild(hint);
  wrap.appendChild(fieldWrap);
  renderKeySequenceChips(chips, hidden);
}

/**
 * Render action parameter fields into a container (main key editor or knob rotate block).
 * @param {HTMLElement} container
 * @param {string} type action type
 * @param {string} idPrefix unique prefix for input ids (e.g. "ap" for main form)
 */
function renderActionFieldsInto(container, type, idPrefix) {
  stopKeySequenceRecording(); // any full rebuild invalidates whatever was recording
  if (!container) return;
  container.innerHTML = "";
  if (!type) return;
  const spec = getSpec(type);
  if (!spec) return;

  if (spec.fields && spec.fields.length > 0) {
    for (const f of spec.fields) {
      const wrap = document.createElement("div");
      wrap.className = "field-row";

      if (f.input === "key_sequence") {
        const lab = document.createElement("label");
        lab.className = "field-label";
        lab.textContent = f.label || f.name;
        wrap.appendChild(lab);
        renderKeySequenceField(wrap, f, idPrefix);
        container.appendChild(wrap);
        continue;
      }

      if (f.input === "asset") {
        const lab = document.createElement("label");
        lab.className = "field-label";
        lab.textContent = f.label || f.name;
        if (f.optional) lab.textContent += " (optional)";
        const fid = `${idPrefix}_${String(f.name).replace(/[^a-zA-Z0-9_]/g, "_")}`;
        const row = document.createElement("div");
        row.className = "path-with-browse";
        const input = document.createElement("input");
        input.type = "text";
        input.dataset.param = f.name;
        input.setAttribute("data-param", String(f.name));
        input.className = "mono path-input";
        input.id = fid;
        lab.htmlFor = fid;
        if (f.placeholder) input.placeholder = f.placeholder;
        const browse = document.createElement("button");
        browse.type = "button";
        browse.className = "btn-browse";
        browse.textContent = "Browse…";
        const fileIn = document.createElement("input");
        fileIn.type = "file";
        fileIn.hidden = true;
        fileIn.accept =
          f.accept != null && String(f.accept).trim() !== "" ? String(f.accept) : "*/*";
        browse.addEventListener("click", () => fileIn.click());
        fileIn.addEventListener("change", async (ev) => {
          const file = ev.target.files && ev.target.files[0];
          ev.target.value = "";
          if (!file) return;
          const errEl = $("#editError");
          try {
            const lib = uploadLibraryParamForFile(file);
            const rel = await uploadFileToAssets(file, lib);
            // After `await`, the form may have been re-rendered; the closure `input` can be detached.
            const live =
              document.getElementById(fid) ||
              (container && container.isConnected && container.querySelector(`#${fid}`)) ||
              input;
            if (live) {
              live.value = rel;
              live.dispatchEvent(new Event("input", { bubbles: true }));
            }
            if (errEl) errEl.textContent = "";
            const saveErr = $("#saveError");
            if (saveErr) saveErr.textContent = "";
            if (idPrefix === "ap") {
              syncMainActionAdvWithFormAfterAssetChange();
              setSaveStatus("Media uploaded — click Apply to key to save");
            }
          } catch (e) {
            const msg = String(e.message || e);
            if (errEl) errEl.textContent = msg;
            const saveErr = $("#saveError");
            if (saveErr) saveErr.textContent = msg;
          }
        });
        row.appendChild(input);
        row.appendChild(browse);
        row.appendChild(fileIn);
        wrap.appendChild(lab);
        wrap.appendChild(row);
        container.appendChild(wrap);
        continue;
      }

      const lab = document.createElement("label");
      lab.className = "field-label";
      lab.textContent = f.label || f.name;
      if (f.optional) lab.textContent += " (optional)";

      let input;
      if (f.input === "select") {
        input = document.createElement("select");
        input.dataset.param = f.name;
        input.setAttribute("data-param", String(f.name));
        for (const opt of f.options || []) {
          const op = document.createElement("option");
          op.value = opt;
          op.textContent = opt;
          input.appendChild(op);
        }
        if (f.default != null) input.value = String(f.default);
      } else if (f.input === "json") {
        input = document.createElement("textarea");
        input.dataset.param = f.name;
        input.setAttribute("data-param", String(f.name));
        input.rows = 3;
        input.spellcheck = false;
        if (f.placeholder) input.placeholder = f.placeholder;
      } else if (f.input === "number") {
        input = document.createElement("input");
        input.type = "number";
        input.dataset.param = f.name;
        input.setAttribute("data-param", String(f.name));
        if (f.placeholder) input.placeholder = f.placeholder;
      } else {
        input = document.createElement("input");
        input.type = "text";
        input.dataset.param = f.name;
        input.setAttribute("data-param", String(f.name));
        if (f.placeholder) input.placeholder = f.placeholder;
      }
      lab.appendChild(input);
      wrap.appendChild(lab);
      container.appendChild(wrap);
    }
    return;
  }

  if (spec.params_json) {
    const hint = document.createElement("p");
    hint.className = "hint";
    hint.textContent =
      "Parameters as a JSON object (do not repeat \"type\"). Example: {\"scene\": \"Main\"}";
    container.appendChild(hint);
    const ta = document.createElement("textarea");
    ta.className = "action-params-json";
    if (idPrefix === "ap") {
      ta.id = "actionParamsJson";
    }
    ta.rows = 8;
    ta.spellcheck = false;
    container.appendChild(ta);
  }
}

function renderActionFields(type) {
  const container = $("#actionFields");
  if (!container) return;
  renderActionFieldsInto(container, type, "ap");
}

function fillActionFieldsInContainer(container, action, type) {
  if (!container || !action || !type) return;
  const spec = getSpec(type);
  if (!spec) return;
  const rest = { ...action };
  delete rest.type;

  if (spec.fields && spec.fields.length > 0) {
    for (const f of spec.fields) {
      const el = actionFieldEl(container, f);
      if (!el) continue;
      if (f.input === "key_sequence") {
        const arr = Array.isArray(action[f.name]) ? action[f.name] : [];
        el.value = JSON.stringify(arr);
        const chipsEl = el.closest(".key-sequence-field")?.querySelector(".key-sequence-chips");
        renderKeySequenceChips(chipsEl, el);
        continue;
      }
      const v = action[f.name];
      if (v === undefined || v === null) {
        if (f.default != null) el.value = String(f.default);
        else el.value = "";
        continue;
      }
      if (f.input === "json") {
        el.value = typeof v === "string" ? v : JSON.stringify(v, null, 2);
      } else {
        el.value = String(v);
      }
    }
  } else if (spec.params_json) {
    const ta = container.querySelector(".action-params-json");
    if (ta) ta.value = Object.keys(rest).length ? JSON.stringify(rest, null, 2) : "";
  }
}

function fillFieldsFromAction(action) {
  const type = action && action.type;
  const sel = $("#actionType");
  if (sel) {
    sel.value = type || "";
    if (sel._refreshActionSelectTrigger) sel._refreshActionSelectTrigger();
  }
  renderActionFields(type || "");
  if (!type) return;
  fillActionFieldsInContainer($("#actionFields"), action, type);

  const adv = $("#actionJsonAdv");
  if (adv) {
    adv.value = JSON.stringify(action, null, 2);
    lastSyncedAdv = adv.value.trim();
  }
}

function useAdvancedJson() {
  const det = $("#advJsonDetails");
  const adv = $("#actionJsonAdv");
  if (!det || !det.open || !adv) return false;
  const cur = adv.value.trim();
  if (!cur) return false;
  return cur !== lastSyncedAdv;
}

/** When Advanced JSON overrides the form, still copy non-empty asset path fields from the form (Browse… only updates inputs). */
function mergeAssetFieldValuesFromForm(container, type, action) {
  if (!action || typeof action !== "object" || Array.isArray(action)) return action;
  const spec = getSpec(type);
  if (!spec || !spec.fields || !container) return action;
  for (const f of spec.fields) {
    if (f.input !== "asset") continue;
    const el = actionFieldEl(container, f);
    if (!el) continue;
    const raw = String(el.value).trim();
    if (!raw) continue;
    action[f.name] = raw;
  }
  return action;
}

/** Keep Advanced JSON in sync after an asset upload so Apply does not drop the new path. */
function syncMainActionAdvWithFormAfterAssetChange() {
  const adv = $("#actionJsonAdv");
  const type = $("#actionType").value;
  const fields = $("#actionFields");
  if (!adv || !type || !fields) return;
  let base = { type };
  const cur = adv.value.trim();
  if (cur) {
    try {
      const p = JSON.parse(cur);
      if (p && typeof p === "object" && !Array.isArray(p)) base = p;
    } catch {
      return;
    }
  }
  mergeAssetFieldValuesFromForm(fields, type, base);
  adv.value = JSON.stringify(base, null, 2);
  lastSyncedAdv = adv.value.trim();
}

function buildActionFromFormIn(container, type) {
  if (!type) return null;
  const spec = getSpec(type);
  const out = { type };
  if (!spec) return out;

  if (spec.fields && spec.fields.length > 0) {
    for (const f of spec.fields) {
      const el = actionFieldEl(container, f);
      if (!el) continue;
      if (f.input === "key_sequence") {
        const steps = keySequenceStepsFromHidden(el);
        if (steps.length > 0) out[f.name] = steps;
        continue;
      }
      const raw = String(el.value).trim();
      if (!raw) {
        continue;
      }
      if (f.input === "json") {
        try {
          out[f.name] = JSON.parse(raw);
        } catch {
          throw new Error(`${f.label || f.name}: invalid JSON`);
        }
      } else if (f.input === "number") {
        out[f.name] = Number(raw);
      } else {
        out[f.name] = raw;
      }
    }
    return out;
  }

  if (spec.params_json) {
    const ta = container.querySelector(".action-params-json");
    const raw = ta && ta.value.trim();
    if (raw) {
      let extra;
      try {
        extra = JSON.parse(raw);
      } catch {
        throw new Error("Parameters: invalid JSON");
      }
      if (typeof extra !== "object" || extra === null || Array.isArray(extra)) {
        throw new Error("Parameters must be a JSON object");
      }
      Object.assign(out, extra);
    }
    return out;
  }

  return out;
}

function buildActionFromForm() {
  if (useAdvancedJson()) {
    const raw = $("#actionJsonAdv").value.trim();
    const action = JSON.parse(raw);
    if (!action || typeof action !== "object" || Array.isArray(action)) {
      throw new Error("Advanced JSON must be an object");
    }
    if (!action.type) throw new Error('Advanced JSON must include "type"');
    const t = String(action.type);
    mergeAssetFieldValuesFromForm($("#actionFields"), t, action);
    return action;
  }

  const type = $("#actionType").value;
  if (!type) return null;
  return buildActionFromFormIn($("#actionFields"), type);
}

function cellHtml(cid) {
  const e = getButtonEntry(cid);
  const err = typeof cid === "string" && cid.startsWith("touch_") && touchErrors && touchErrors[cid];
  const ledOnly =
    layoutMode() === "live_s" &&
    BTNS_LIVE_S.includes(cid) &&
    e &&
    e.button_color &&
    String(e.button_color).trim() &&
    !hasTactileGraphic(e);
  const has =
    e &&
    (e.action ||
      e.actions ||
      e.image ||
      e.icon ||
      e.text ||
      e.label ||
      e.background ||
      ledOnly);
  const label =
    (e &&
      Array.isArray(e.actions) &&
      e.actions.length > 0 &&
      e.actions[0] &&
      e.actions[0].type) ||
    (e && e.action && e.action.type) ||
    "";
  const pageTag =
    isLiveSModel() && BTNS_LIVE_S.includes(cid)
      ? `<span class="page-btn-tag" title="Switches touch page ${BTNS_LIVE_S.indexOf(cid) + 1}">P${
          BTNS_LIVE_S.indexOf(cid) + 1
        }</span>`
      : "";
  const showRaster = hasTactileGraphic(e) && !mediaPathForEntry(e);
  const swatch =
    layoutMode() === "live_s" && BTNS_LIVE_S.includes(cid) && e && e.button_color && String(e.button_color).trim()
      ? `<span class="btn-led-swatch" style="background-color:${escapeHtml(
          cssColorForLedPreview(e.button_color)
        )}" title="LED"></span>`
      : "";
  const swappable = typeof cid === "string" && cid.startsWith("touch_");
  return `
    <div class="cell ${has ? "has-action" : ""} ${err ? "error-outline" : ""}" data-cid="${cid}" ${
    swappable ? 'draggable="true"' : ""
  } title="${escapeHtml(err ? `${cid} — ${err}` : cid)}">
      ${
        showRaster
          ? `<img class="key-preview" data-cid="${escapeHtml(cid)}" alt="" hidden />`
          : ""
      }
      <div class="cell-footer">
        <span class="cid">${swatch}${escapeHtml(cid)}${pageTag}</span>
        ${label ? `<span class="cell-act">${escapeHtml(label)}</span>` : ""}
      </div>
    </div>`;
}

/** cid currently being dragged, or null when no drag is in progress. */
let draggingCid = null;

function swapButtonEntries(cidA, cidB) {
  if (!cidA || !cidB || cidA === cidB) return;
  snapshotBeforeAction();
  const entryA = getButtonEntry(cidA);
  const entryB = getButtonEntry(cidB);
  setButtonEntry(cidA, entryB);
  setButtonEntry(cidB, entryA);
  renderDeck();
  scheduleAutosave();
  if (selectedControl === cidA || selectedControl === cidB) {
    openEditor(selectedControl);
  }
}

function bindCells() {
  document.querySelectorAll(".cell").forEach((el) => {
    el.addEventListener("click", () => {
      if (draggingCid) return; // a drop already fired the swap; ignore the trailing click
      openEditor(el.dataset.cid);
    });

    el.addEventListener("dragstart", (e) => {
      const cid = el.dataset.cid;
      if (!cid || !cid.startsWith("touch_")) {
        e.preventDefault();
        return;
      }
      draggingCid = cid;
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", cid);
      el.classList.add("dragging");
    });

    el.addEventListener("dragend", () => {
      draggingCid = null;
      el.classList.remove("dragging");
      document.querySelectorAll(".cell.drag-over").forEach((c) => c.classList.remove("drag-over"));
    });

    el.addEventListener("dragover", (e) => {
      const cid = el.dataset.cid;
      if (!draggingCid || !cid || !cid.startsWith("touch_") || cid === draggingCid) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      el.classList.add("drag-over");
    });

    el.addEventListener("dragleave", () => {
      el.classList.remove("drag-over");
    });

    el.addEventListener("drop", (e) => {
      const cid = el.dataset.cid;
      el.classList.remove("drag-over");
      if (!draggingCid || !cid || !cid.startsWith("touch_") || cid === draggingCid) return;
      e.preventDefault();
      const source = draggingCid;
      draggingCid = null;
      swapButtonEntries(source, cid);
    });
  });
}

async function hydrateKeyPreviews(expectedGen) {
  const imgs = document.querySelectorAll("img.key-preview");
  await Promise.all(
    Array.from(imgs).map(async (img) => {
      if (expectedGen !== deckPreviewGeneration) return;
      const cid = img.dataset.cid;
      const e = getButtonEntry(cid);
      if (!hasTactileGraphic(e)) {
        img.removeAttribute("src");
        img.hidden = true;
        return;
      }
      try {
        const r = await fetch("/api/preview_key", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            entry: visualEntryForPreview(e),
            control_id: cid,
          }),
        });
        if (expectedGen !== deckPreviewGeneration) return;
        if (!r.ok) {
          img.hidden = true;
          return;
        }
        const blob = await r.blob();
        if (expectedGen !== deckPreviewGeneration) return;
        const url = URL.createObjectURL(blob);
        deckPreviewUrls.push(url);
        img.src = url;
        img.hidden = false;
      } catch {
        if (expectedGen === deckPreviewGeneration) img.hidden = true;
      }
    })
  );
}

function hydrateMediaBackgrounds(expectedGen) {
  stopDeckMediaBackgrounds();
  const cells = document.querySelectorAll(".cell");
  for (const cell of Array.from(cells)) {
    if (expectedGen !== deckPreviewGeneration) return;
    const cid = cell.dataset && cell.dataset.cid;
    if (!cid || typeof cid !== "string") continue;
    const mediaBgCell =
      cid.startsWith("touch_") ||
      cid === "strip_left" ||
      cid === "strip_right" ||
      cid.startsWith("btn_");
    if (!mediaBgCell) continue;
    const e = getButtonEntry(cid);
    const rel = mediaPathForEntry(e);
    if (!rel) continue;
    const url = localFileUrl(rel);
    const ex = extOfPath(rel);
    if (VIDEO_EXT.has(ex)) {
      const v = document.createElement("video");
      v.className = "media-bg";
      v.muted = true;
      v.loop = true;
      v.autoplay = true;
      v.playsInline = true;
      v.preload = "auto";
      v.src = url;
      v.playbackRate = 2.0;
      cell.prepend(v);
      const stop = () => {
        try {
          v.pause();
        } catch {
          /* ignore */
        }
        try {
          v.removeAttribute("src");
          v.load();
        } catch {
          /* ignore */
        }
        try {
          v.remove();
        } catch {
          /* ignore */
        }
      };
      deckMediaBgStops.push(stop);
      continue;
    }
    if (DECK_MEDIA_EXT.has(ex)) {
      const im = document.createElement("img");
      im.className = "media-bg";
      im.src = url;
      im.alt = "";
      im.draggable = false;
      cell.prepend(im);
      deckMediaBgStops.push(() => {
        try {
          im.remove();
        } catch {
          /* ignore */
        }
      });
    }
  }
}

function renderDeck() {
  deckPreviewGeneration += 1;
  const previewGen = deckPreviewGeneration;
  ensurePages();
  ensureDevice();
  $("#pageName").textContent = currentPage().name || `Page ${pageIndex + 1}`;
  const pn = $("#pageNameInput");
  if (pn) pn.value = currentPage().name || "";

  const mode = layoutMode();
  const root = $("#deckRoot");
  if (!root) return;

  if (mode === "live_s") {
    const np = cfg.pages && cfg.pages.length ? cfg.pages.length : 1;
    root.innerHTML = `
      <div class="deck-chassis deck-chassis--live-s">
        <p class="deck-subtitle">Live S · ${np} touch page${np === 1 ? "" : "s"} · <span class="deck-subtitle-hint">Circle + btn 1–3 → indices 0–3 only</span></p>
        <div class="live-s-wrap">
          <div class="live-s-left deck-side-rail">
            <span class="deck-region-label">Encoders</span>
            ${["knobTL", "knobCL"]
              .map(
                (k) =>
                  `<div class="knob-block"><span class="knob-block-label">${escapeHtml(k)}</span>${knobEncoderCellHtml(k)}</div>`
              )
              .join("")}
            <div class="knob-block knob-block--btn">
              <span class="knob-block-label">Page</span>
              ${cellHtml("btn_circle")}
            </div>
          </div>
          <div class="live-s-center">
            <span class="deck-region-label">Touch screen</span>
            <div class="touch-screen">
              <div class="touch-grid touch-grid-5">${TOUCH_LIVE_S.map((c) => cellHtml(c)).join("")}</div>
            </div>
          </div>
          <div class="live-s-right deck-side-rail deck-side-rail--btns">
            <span class="deck-region-label">Keys</span>
            ${["btn_1", "btn_2", "btn_3"].map((c) => cellHtml(c)).join("")}
          </div>
        </div>
      </div>`;
  } else {
    root.innerHTML = `
      <div class="deck-chassis deck-chassis--live">
        <p class="deck-subtitle">Loupedeck Live · strips · 4×3 touch · row + circle</p>
        <div class="deck-grid">
          <div class="strip strip--side">
            <span class="deck-region-label">Left</span>
            <div id="stripLeft" class="strip-touch">${cellHtml("strip_left")}</div>
            <div class="knob-col">${KNOBS_LIVE.slice(0, 3).map((k) => `<div class="knob-slot"><span class="knob-block-label">${k}</span>${knobEncoderCellHtml(k)}</div>`).join("")}</div>
          </div>
          <div class="center-block">
            <span class="deck-region-label">Touch screen</span>
            <div class="touch-screen touch-screen--live">
              <div class="touch-grid touch-grid-4">${TOUCH_LIVE.map((c) => cellHtml(c)).join("")}</div>
            </div>
            <span class="deck-region-label deck-region-label--row">Hardware buttons</span>
            <div class="row-btns">${BTNS_LIVE.map((c) => cellHtml(c)).join("")}</div>
          </div>
          <div class="strip strip--side">
            <span class="deck-region-label">Right</span>
            <div id="stripRight" class="strip-touch">${cellHtml("strip_right")}</div>
            <div class="knob-col">${KNOBS_LIVE.slice(3, 6).map((k) => `<div class="knob-slot"><span class="knob-block-label">${k}</span>${knobEncoderCellHtml(k)}</div>`).join("")}</div>
          </div>
        </div>
      </div>`;
  }
  bindCells();
  revokeDeckPreviewUrls();
  stopDeckMediaBackgrounds();
  void hydrateKeyPreviews(previewGen);
  void hydrateMediaBackgrounds(previewGen);
}

function openEditor(cid) {
  if (isKnobEncoderId(cid)) {
    openKnobEncoderEditor(cid);
    return;
  }
  selectedKnobEncoder = null;
  showKeyEditorPanel();

  selectedControl = cid;
  $("#selLabel").textContent = cid;
  const e = getButtonEntry(cid) || {};
  const action =
    (Array.isArray(e.actions) && e.actions.length > 0 && e.actions[0] && typeof e.actions[0] === "object"
      ? e.actions[0]
      : null) ||
    (e.action && typeof e.action === "object" ? e.action : null);

  const det = $("#advJsonDetails");
  if (det) det.open = false;

  if (isLiveSPageSwitchButton(cid)) {
    const sel = $("#actionType");
    if (sel) {
      sel.value = "";
      if (sel._refreshActionSelectTrigger) sel._refreshActionSelectTrigger();
    }
    renderActionFields("");
    const adv = $("#actionJsonAdv");
    if (adv) {
      adv.value = "";
      lastSyncedAdv = "";
    }
    $("#iconUri").value = "";
    $("#imagePath").value = "";
    $("#buttonText").value = "";
    $("#textColor").value = "";
    $("#backgroundColor").value = "";
    $("#fontSize").value = "";
    const ffp = $("#fontFilePath");
    if (ffp) ffp.value = "";
    populateDesignFieldsFromEntry({});
  } else if (action && action.type) {
    fillFieldsFromAction(action);
    const { icon, image } = splitIconAndImage(e);
    $("#iconUri").value = icon;
    $("#imagePath").value = image;
    $("#buttonText").value = e.text || e.label || "";
    $("#textColor").value = e.text_color || "";
    $("#backgroundColor").value = e.background || "";
    $("#fontSize").value = e.font_size != null && e.font_size !== "" ? String(e.font_size) : "";
    const ffpA = $("#fontFilePath");
    if (ffpA) ffpA.value = e.font_file != null && e.font_file !== "" ? String(e.font_file) : "";
    const gl = $("#graphicTextLayout");
    if (gl) {
      const v = String(e.graphic_text_layout || "split").toLowerCase();
      const overlayish = ["overlay", "overlap", "on_graphic", "stacked_on_graphic", "center"];
      gl.value = overlayish.includes(v) ? "overlay" : "split";
    }
    populateDesignFieldsFromEntry(e);
  } else {
    const sel = $("#actionType");
    if (sel) {
      sel.value = "";
      if (sel._refreshActionSelectTrigger) sel._refreshActionSelectTrigger();
    }
    renderActionFields("");
    const adv = $("#actionJsonAdv");
    if (adv) {
      adv.value = "";
      lastSyncedAdv = "";
    }
    const { icon, image } = splitIconAndImage(e);
    $("#iconUri").value = icon;
    $("#imagePath").value = image;
    $("#buttonText").value = e.text || e.label || "";
    $("#textColor").value = e.text_color || "";
    $("#backgroundColor").value = e.background || "";
    $("#fontSize").value = e.font_size != null && e.font_size !== "" ? String(e.font_size) : "";
    const ffpB = $("#fontFilePath");
    if (ffpB) ffpB.value = e.font_file != null && e.font_file !== "" ? String(e.font_file) : "";
    const gl = $("#graphicTextLayout");
    if (gl) {
      const v = String(e.graphic_text_layout || "split").toLowerCase();
      const overlayish = ["overlay", "overlap", "on_graphic", "stacked_on_graphic", "center"];
      gl.value = overlayish.includes(v) ? "overlay" : "split";
    }
    populateDesignFieldsFromEntry(e);
  }
  syncGraphicLayoutVisibility();

  syncLiveSButtonColorBlock(cid, e);
  syncKeyEditorPageSwitchMode(cid);

  void updatePreviewFromEntry(e, cid);
  maybeStartSidebarAnimPreview(e, cid);
  syncTestPressButton();
  syncCopyPasteButtons();
}

async function updatePreviewFromEntry(e, cid, animOpts) {
  const prev = $("#preview");
  if (!prev) return;
  revokeSidebarPreview();
  if (!hasRenderableVisual(e)) {
    prev.innerHTML = "";
    return;
  }
  if (cid && isLiveSPhysicalButton(cid) && !hasTactileGraphic(e)) {
    const raw = ((e && e.button_color) || "").trim();
    const css = cssColorForLedPreview(raw || "#202028");
    prev.innerHTML = `<div class="preview led-preview" style="background-color:${escapeHtml(css)}"></div>`;
    return;
  }
  try {
    const body = {
      entry: visualEntryForPreview(e),
      control_id: cid || "touch_0",
    };
    if (animOpts && animOpts.animationFrame != null) body.animation_frame = animOpts.animationFrame;
    if (animOpts && animOpts.pressElapsedFrames != null) body.press_elapsed_frames = animOpts.pressElapsedFrames;
    const r = await fetch("/api/preview_key", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (r.status === 404) {
      prev.innerHTML = "";
      return;
    }
    if (!r.ok) {
      prev.innerHTML = `<p class="error">${escapeHtml(await r.text())}</p>`;
      return;
    }
    const blob = await r.blob();
    sidebarPreviewUrl = URL.createObjectURL(blob);
    prev.innerHTML = `<img class="preview" src="${sidebarPreviewUrl}" alt="Key preview (matches device)"/>`;
  } catch (err) {
    prev.innerHTML = `<p class="error">${escapeHtml(String(err))}</p>`;
  }
}

// Live idle-animation preview: while the open control has idle_animation set, keep re-fetching
// the preview with an advancing frame counter so the config UI actually shows the loop, not just
// a static snapshot (the "previewable" half of the project's text-on-key design rule).
let sidebarAnimPreviewTimer = null;
let sidebarAnimPreviewFrame = 0;

function stopSidebarAnimPreview() {
  if (sidebarAnimPreviewTimer) {
    clearInterval(sidebarAnimPreviewTimer);
    sidebarAnimPreviewTimer = null;
  }
}

function maybeStartSidebarAnimPreview(entry, cid) {
  stopSidebarAnimPreview();
  const idleType = (entry && entry.idle_animation) || "none";
  if (idleType === "none") return;
  sidebarAnimPreviewFrame = 0;
  sidebarAnimPreviewTimer = setInterval(() => {
    sidebarAnimPreviewFrame += 1;
    void updatePreviewFromEntry(entry, cid, { animationFrame: sidebarAnimPreviewFrame });
  }, 100);
}

// Must mirror button_render.py's PRESS_ANIMATION_DURATION_TICKS / _PRESS_ANIMATION_DURATION_OVERRIDES.
const PRESS_ANIMATION_DURATION_TICKS = 4;
const PRESS_ANIMATION_DURATION_OVERRIDES = { slide_reappear: 8 };

async function previewPressAnimation() {
  if (!selectedControl) return;
  const draft = draftVisualEntryFromForm();
  const pressType = draft.press_animation || "none";
  if (pressType === "none") return;
  stopSidebarAnimPreview();
  const duration = PRESS_ANIMATION_DURATION_OVERRIDES[pressType] || PRESS_ANIMATION_DURATION_TICKS;
  for (let f = 0; f < duration; f++) {
    await updatePreviewFromEntry(draft, selectedControl, { pressElapsedFrames: f });
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  await updatePreviewFromEntry(draft, selectedControl);
  maybeStartSidebarAnimPreview(draft, selectedControl);
}

async function saveAction() {
  if (selectedKnobEncoder) return;
  if (!selectedControl) return;
  let entry;
  try {
    entry = buildEntryFromFormOrThrow();
  } catch (err) {
    $("#editError").textContent = err.message || String(err);
    setEditorAutosaveStatus(err.message || String(err));
    return;
  }
  $("#editError").textContent = "";
  setEditorAutosaveStatus("");
  setButtonEntry(selectedControl, entry);
  renderDeck();
  openEditor(selectedControl);
  clearTimeout(autosaveTimer);
  autosaveTimer = null;
  const ok = await runAutosave();
  if (!ok) return;
  await refreshSkin();
}

/**
 * Pure extraction (no side effects) of "what should this control's entry be, given the current
 * form state" — shared by the explicit Apply button and by silent autosave-while-typing. Throws
 * with a user-facing message on invalid input (e.g. bad JSON in Advanced, non-numeric font size);
 * callers must not persist anything when this throws.
 */
function buildEntryFromFormOrThrow() {
  if (isLiveSPageSwitchButton(selectedControl)) {
    const raw = ($("#buttonColorHex") && $("#buttonColorHex").value.trim()) || "";
    const entry = {};
    if (raw) {
      const bc = sanitizeButtonColorHex(raw);
      entry.button_color = bc || raw;
    }
    return entry.button_color ? entry : null;
  }

  const action = buildActionFromForm();
  const icon = $("#iconUri").value.trim();
  const img = $("#imagePath").value.trim();
  const txt = $("#buttonText").value.trim();
  const entry = {};
  if (action && action.type) entry.action = action;
  if (txt) entry.text = txt;
  const tc = $("#textColor").value.trim();
  if (tc) entry.text_color = tc;
  const bg = $("#backgroundColor").value.trim();
  if (bg) entry.background = bg;
  const fs = $("#fontSize").value.trim();
  if (fs) {
    const fsNum = Number(fs);
    if (!Number.isFinite(fsNum)) throw new Error("Max font size: invalid number");
    entry.font_size = fsNum;
  }
  const ff = ($("#fontFilePath") && $("#fontFilePath").value.trim()) || "";
  if (ff) entry.font_file = ff;
  if (icon) entry.icon = icon;
  if (img) entry.image = img;

  if (isLiveSPhysicalButton(selectedControl)) {
    const raw = $("#buttonColorHex").value.trim();
    if (raw) {
      const bc = sanitizeButtonColorHex(raw);
      entry.button_color = bc || raw;
    }
  }
  readDesignFieldsFromForm(entry);

  if (
    !entry.action &&
    !entry.image &&
    !entry.icon &&
    !entry.text &&
    !entry.background &&
    !entry.background_gradient_from &&
    !(isLiveSPhysicalButton(selectedControl) && entry.button_color)
  ) {
    return null;
  }
  return entry;
}

/**
 * Autosave-while-typing for the button editor: commits a valid form to `cfg` and schedules the
 * usual debounced save, but — unlike `saveAction()` — never calls `openEditor()` (which would
 * rebuild the whole form and steal focus/cursor position out from under the user mid-keystroke).
 * An invalid form is never persisted; the offending field gets `.field-invalid` from its own
 * `wireSmartField`/inline wiring and the sticky bar shows the error.
 */
function autoCommitControlIfValid() {
  if (selectedKnobEncoder || !selectedControl) return;
  let entry;
  try {
    entry = buildEntryFromFormOrThrow();
  } catch (err) {
    setEditorAutosaveStatus(err.message || String(err));
    return;
  }
  setEditorAutosaveStatus("");
  $("#editError").textContent = "";
  setButtonEntry(selectedControl, entry);
  renderDeck();
  scheduleAutosave();
}

/**
 * Delegated wiring for the whole button-editor form: any field inside #keyEditorBlock triggers a
 * silent, validation-gated autosave on "input"/"change", and a full commit (openEditor refresh +
 * immediate save + device redraw) on "focusout" (bubbles, unlike "blur" — no capture needed).
 * Covers every current field (and any future action-catalog-driven one) without per-field wiring.
 */
function wireKeyEditorAutoCommit() {
  const block = $("#keyEditorBlock");
  if (!block) return;
  const isEligible = (t) => t && t.matches && t.matches("input, select, textarea") && t.type !== "file";
  block.addEventListener("input", (e) => {
    if (isEligible(e.target)) {
      snapshotBeforeEditOnce();
      autoCommitControlIfValid();
    }
  });
  block.addEventListener("change", (e) => {
    if (isEligible(e.target)) {
      snapshotBeforeEditOnce();
      autoCommitControlIfValid();
    }
  });
  block.addEventListener("focusout", (e) => {
    if (isEligible(e.target)) void saveAction();
  });
}

function setEditorAutosaveStatus(message) {
  const el = $("#editorAutosaveStatus");
  if (!el) return;
  el.textContent = message || "";
  el.classList.toggle("invalid", !!message);
}

async function clearControl() {
  if (selectedKnobEncoder) return;
  if (!selectedControl) return;
  snapshotBeforeAction();
  if (isLiveSPageSwitchButton(selectedControl)) {
    setButtonEntry(selectedControl, null);
    renderDeck();
    openEditor(selectedControl);
    clearTimeout(autosaveTimer);
    autosaveTimer = null;
    const ok = await runAutosave();
    if (!ok) return;
    await refreshSkin();
    return;
  }
  setButtonEntry(selectedControl, null);
  renderDeck();
  openEditor(selectedControl);
  clearTimeout(autosaveTimer);
  autosaveTimer = null;
  const ok = await runAutosave();
  if (!ok) return;
  await refreshSkin();
}

async function uploadFileToAssets(file, library) {
  if (!file) throw new Error("No file selected");
  const lib = library || "images";
  const fd = new FormData();
  fd.append("file", file);
  const r = await fetch(`/api/upload?library=${encodeURIComponent(lib)}`, { method: "POST", body: fd });
  if (!r.ok) {
    const t = await r.text();
    throw new Error(t || `Upload failed (${r.status})`);
  }
  const j = await r.json();
  if (!j.path) throw new Error("Upload response missing path");
  return j.path;
}

async function uploadImage(ev) {
  const f = ev.target.files && ev.target.files[0];
  if (!f) return;
  try {
    const path = await uploadFileToAssets(f, "images");
    snapshotBeforeAction();
    const inp = $("#imagePath");
    if (inp) inp.value = path;
    const err = $("#editError");
    if (err) err.textContent = "";
    await saveAction();
  } catch (e) {
    const err = $("#editError");
    if (err) err.textContent = String(e.message || e);
  }
}

async function uploadFontFile(ev) {
  const f = ev.target.files && ev.target.files[0];
  if (!f) return;
  try {
    const path = await uploadFileToAssets(f, "fonts");
    snapshotBeforeAction();
    const inp = $("#fontFilePath");
    if (inp) inp.value = path;
    const err = $("#editError");
    if (err) err.textContent = "";
    scheduleSidebarPreviewRefresh();
    await saveAction();
  } catch (e) {
    const err = $("#editError");
    if (err) err.textContent = String(e.message || e);
  }
}

function addPage() {
  snapshotBeforeAction();
  ensurePages();
  cfg.pages.push({ name: `Page ${cfg.pages.length + 1}`, buttons: {} });
  pageIndex = cfg.pages.length - 1;
  syncPageSelect();
  renderDeck();
  scheduleAutosave();
  syncAgentPageIndex();
}

function syncPageSelect() {
  ensurePages();
  const sel = $("#pageSelect");
  sel.innerHTML = "";
  cfg.pages.forEach((p, i) => {
    const o = document.createElement("option");
    o.value = String(i);
    o.textContent = p.name || `Page ${i + 1}`;
    sel.appendChild(o);
  });
  sel.value = String(pageIndex);
  renderPageRail();
}

const PAGE_RAIL_HARDWARE_BADGES = ["①", "②", "③", "④"];

/** Clicking a rail item reuses the existing #pageSelect "change" wiring (page switch, agent sync, etc.). */
function selectPageIndex(i) {
  const sel = $("#pageSelect");
  if (!sel) return;
  sel.value = String(i);
  sel.dispatchEvent(new Event("change", { bubbles: true }));
}

/**
 * The agent (and the physical device) track their own `page_index` server-side; a background poll
 * (`refreshConnectionStatus`, every 1.5s) pulls it back into the client whenever they differ. Any
 * client-side operation that changes which numeric index the active page sits at (not just "switch
 * to a different page") must push that index to the agent too, or the next poll snaps the UI back
 * to the stale server-side page within ~1.5s.
 */
function syncAgentPageIndex() {
  muteAgentPagePollBriefly();
  void postAgentPageIndex(pageIndex).catch((e) => {
    $("#saveError").textContent = String(e);
  });
}

function removePageAt(i) {
  ensurePages();
  if (cfg.pages.length <= 1) return;
  const name = cfg.pages[i].name || `Page ${i + 1}`;
  if (!confirm(`Remove page "${name}"?`)) return;
  snapshotBeforeAction();
  const prevIndex = pageIndex;
  cfg.pages.splice(i, 1);
  if (pageIndex >= cfg.pages.length) pageIndex = cfg.pages.length - 1;
  else if (i < pageIndex) pageIndex -= 1;
  syncPageSelect();
  renderDeck();
  scheduleAutosave();
  if (pageIndex !== prevIndex) syncAgentPageIndex();
}

/** Index of the page currently being dragged in the rail, or null. */
let draggingPageIndex = null;

function reorderPage(fromIndex, toIndex) {
  ensurePages();
  snapshotBeforeAction();
  const prevIndex = pageIndex;
  const activePage = cfg.pages[pageIndex];
  const [moved] = cfg.pages.splice(fromIndex, 1);
  cfg.pages.splice(toIndex, 0, moved);
  pageIndex = cfg.pages.indexOf(activePage);
  syncPageSelect();
  renderDeck();
  scheduleAutosave();
  if (pageIndex !== prevIndex) syncAgentPageIndex();
}

function wirePageRailDrag(item, index) {
  item.addEventListener("dragstart", (e) => {
    draggingPageIndex = index;
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", String(index));
    item.classList.add("dragging");
  });
  item.addEventListener("dragend", () => {
    draggingPageIndex = null;
    item.classList.remove("dragging");
    document.querySelectorAll(".page-rail-item.drag-over").forEach((el) => el.classList.remove("drag-over"));
  });
  item.addEventListener("dragover", (e) => {
    if (draggingPageIndex === null || draggingPageIndex === index) return;
    e.preventDefault();
    item.classList.add("drag-over");
  });
  item.addEventListener("dragleave", () => item.classList.remove("drag-over"));
  item.addEventListener("drop", (e) => {
    item.classList.remove("drag-over");
    if (draggingPageIndex === null || draggingPageIndex === index) return;
    e.preventDefault();
    reorderPage(draggingPageIndex, index);
    draggingPageIndex = null;
  });
}

function renderPageRail() {
  const rail = $("#pageRail");
  if (!rail) return;
  rail.innerHTML = "";
  cfg.pages.forEach((p, i) => {
    const item = document.createElement("div");
    item.className = "page-rail-item" + (i === pageIndex ? " active" : "");
    item.draggable = true;
    const badgeHtml =
      i < 4
        ? `<span class="page-rail-badge" title="Reachable via the physical ${
            i === 0 ? "Circle" : `btn_${i}`
          } button">${PAGE_RAIL_HARDWARE_BADGES[i]}</span>`
        : `<span class="page-rail-badge page-rail-badge-muted" title="Not reachable by the physical page buttons — use agent.goto_page">&middot;</span>`;
    item.innerHTML = `${badgeHtml}<span class="page-rail-name"></span><button type="button" class="page-rail-delete" title="Remove page" aria-label="Remove page">✕</button>`;
    item.querySelector(".page-rail-name").textContent = p.name || `Page ${i + 1}`;
    item.addEventListener("click", (e) => {
      if (e.target.closest(".page-rail-delete")) return;
      selectPageIndex(i);
    });
    item.querySelector(".page-rail-delete").addEventListener("click", (e) => {
      e.stopPropagation();
      removePageAt(i);
    });
    wirePageRailDrag(item, i);
    rail.appendChild(item);
  });
}

function onModelChange() {
  ensureDevice();
  const sel = $("#deviceModel");
  if (sel) cfg.device.model = sel.value;
  ensurePages();
  updateLiveSPageChrome();
  renderDeck();
  if (selectedKnobEncoder && !liveKnobEncoderIds().includes(selectedKnobEncoder)) {
    closeKnobEncoderEditor();
  } else if (selectedKnobEncoder) {
    openKnobEncoderEditor(selectedKnobEncoder);
  } else if (selectedControl) {
    openEditor(selectedControl);
  }
  scheduleAutosave();
}

function syncKnobPagesEditor() {
  const ta = $("#knobPagesJson");
  if (!ta) return;
  try {
    const kp = cfg.knob_pages && typeof cfg.knob_pages === "object" ? cfg.knob_pages : {};
    ta.value = JSON.stringify(kp, null, 2);
  } catch {
    ta.value = "{}";
  }
}

async function applyKnobPagesJson() {
  const ta = $("#knobPagesJson");
  const err = $("#knobPagesError");
  if (!ta) return;
  if (err) err.textContent = "";
  try {
    const raw = ta.value.trim() || "{}";
    const o = JSON.parse(raw);
    if (typeof o !== "object" || o === null || Array.isArray(o)) {
      throw new Error("knob_pages must be a JSON object");
    }
    cfg.knob_pages = o;
    clearTimeout(autosaveTimer);
    autosaveTimer = null;
    const ok = await runAutosave();
    if (!ok) return;
    await refreshSkin();
    if (selectedKnobEncoder) {
      renderKnobEncoderForm(selectedKnobEncoder);
    }
    renderDeck();
  } catch (e) {
    if (err) err.textContent = String(e.message || e);
  }
}

async function saveKnobEncoderPagesFromForm() {
  const errEl = $("#knobEncoderError");
  if (errEl) errEl.textContent = "";
  const kid = selectedKnobEncoder;
  if (!kid) return;
  let pages;
  try {
    pages = collectKnobEncoderPagesFromDom();
  } catch (e) {
    if (errEl) errEl.textContent = String(e.message || e);
    return;
  }
  if (!cfg.knob_pages || typeof cfg.knob_pages !== "object") cfg.knob_pages = {};
  cfg.knob_pages[kid] = { pages };
  const durIn = $("#knobFeedbackDurationSec");
  if (durIn) {
    const v = parseFloat(durIn.value);
    if (!Number.isNaN(v)) {
      const clamped = Math.max(0.3, Math.min(2, v));
      cfg.knob_page_feedback = { ...(cfg.knob_page_feedback && typeof cfg.knob_page_feedback === "object" ? cfg.knob_page_feedback : {}), duration_sec: clamped };
    }
  }
  syncKnobPagesEditor();
  clearTimeout(autosaveTimer);
  autosaveTimer = null;
  const ok = await runAutosave();
  if (!ok) return;
  await refreshSkin();
  renderDeck();
}

async function init() {
  wireTabBar();
  wireUndoRedoKeyboard();
  void refreshBackupsList();
  try {
    const cr = await fetch("/api/action_catalog");
    if (cr.ok) {
      const j = await cr.json();
      actionCatalog = j.actions || [];
    }
    populateActionTypeSelect();
    cfg = await apiGet();
  } catch (e) {
    $("#saveError").textContent = String(e);
    return;
  }
  loadCopiedControlFromStorage();
  syncSpotifyFromCfg();
  void refreshSpotifyStatus();
  handleSpotifyReturnQuery();
  ensureTwitch();
  renderTwitchAccounts();
  ensureDevice();
  ensureLogging();
  syncLoggingFromCfg();
  const logLevelEl = $("#logLevel");
  if (logLevelEl) {
    logLevelEl.addEventListener("change", () => {
      ensureLogging();
      cfg.logging.level = logLevelEl.value;
      scheduleAutosave();
    });
  }
  syncHaFromCfg();
  wireSmartField($("#haBaseUrl"), {
    validate: () => true,
    onCommit: (raw) => {
      ensureHa();
      cfg.ha.base_url = raw.trim();
    },
  });
  wireSmartField($("#haToken"), {
    validate: () => true,
    onCommit: (raw) => {
      ensureHa();
      cfg.ha.token = raw.trim();
    },
  });

  syncObsFromCfg();
  wireSmartField($("#obsHost"), {
    validate: () => true,
    onCommit: (raw) => {
      ensureObs();
      cfg.obs.host = raw.trim();
    },
  });
  wireSmartField($("#obsPort"), {
    validate: (v) => FIELD_VALIDATORS.port(v) || "Port must be an integer 1–65535",
    optional: false,
    onCommit: (raw) => {
      ensureObs();
      cfg.obs.port = Number(raw.trim());
    },
  });
  wireSmartField($("#obsPassword"), {
    validate: () => true,
    onCommit: (raw) => {
      ensureObs();
      cfg.obs.password = raw;
    },
  });

  const btnOpenConfigFolder = $("#btnOpenConfigFolder");
  if (btnOpenConfigFolder) {
    btnOpenConfigFolder.addEventListener("click", () => {
      void fetch("/api/open_config_folder", { method: "POST" }).catch(() => {
        /* best-effort */
      });
    });
  }
  const autostartEl = $("#autostartToggle");
  if (autostartEl) {
    try {
      const ar = await fetch("/api/autostart");
      if (ar.ok) {
        const aj = await ar.json();
        autostartEl.checked = !!aj.enabled;
      }
    } catch {
      /* leave unchecked; user can still toggle */
    }
    autostartEl.addEventListener("change", () => {
      void (async () => {
        try {
          await fetch("/api/autostart", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ enabled: autostartEl.checked }),
          });
        } catch (e) {
          autostartEl.checked = !autostartEl.checked;
          $("#saveError").textContent = String(e);
        }
      })();
    });
  }
  try {
    const sr = await fetch("/api/status");
    if (sr.ok) {
      const sj = await sr.json();
      if (sj.deck_layout === "live" || sj.deck_layout === "live_s") {
        agentDeckLayout = sj.deck_layout;
      } else {
        agentDeckLayout = null;
      }
      ensurePages();
      if (typeof sj.page_index === "number") {
        syncUiToAgentPage(sj.page_index);
      }
    } else {
      ensurePages();
    }
  } catch {
    ensurePages();
  }
  updateLiveSPageChrome();
  const dm = $("#deviceModel");
  if (dm) dm.value = cfg.device.model || "auto";

  $("#pageName").textContent = currentPage().name || `Page ${pageIndex + 1}`;
  const pnInit = $("#pageNameInput");
  if (pnInit) pnInit.value = currentPage().name || "";
  syncPageSelect();
  renderDeck();
  syncKnobPagesEditor();
  syncTestPressButton();
  syncCopyPasteButtons();

  $("#pageSelect").addEventListener("change", () => {
    pageIndex = Number($("#pageSelect").value);
    muteAgentPagePollBriefly();
    // Respond immediately from the client's own state; the agent (and physical device) catch up
    // in the background. Never block the UI switch on this request's completion.
    void (async () => {
      try {
        await postAgentPageIndex(pageIndex);
      } catch (e) {
        $("#saveError").textContent = String(e);
      }
    })();
    renderDeck();
    renderPageRail();
    selectedControl = null;
    closeKnobEncoderEditor();
    const sl = $("#selLabel");
    if (sl) sl.textContent = "Select a control";
    syncTestPressButton();
  });

  $("#btnAddPage").addEventListener("click", addPage);
  const btnBackup = $("#btnBackup");
  if (btnBackup) btnBackup.addEventListener("click", () => void backupConfig());
  const btnWipeBackups = $("#btnWipeBackups");
  if (btnWipeBackups) btnWipeBackups.addEventListener("click", () => void wipeBackupsConfig());
  const btnReset = $("#btnResetDefaults");
  if (btnReset) btnReset.addEventListener("click", () => void resetConfigToDefaults());
  $("#btnApply").addEventListener("click", () => void saveAction());
  $("#btnClear").addEventListener("click", () => void clearControl());
  const btnCopyControl = $("#btnCopyControl");
  const btnPasteControl = $("#btnPasteControl");
  if (btnCopyControl) {
    btnCopyControl.addEventListener("click", () => {
      if (!selectedControl) return;
      const e = getButtonEntry(selectedControl);
      if (!e) return;
      copiedControlEntry = deepCloneJson(e);
      copiedControlMeta = {
        cid: selectedControl,
        at: Date.now(),
      };
      saveCopiedControlToStorage();
      setSaveStatus(`Copied ${selectedControl}`);
      syncCopyPasteButtons();
    });
  }
  if (btnPasteControl) {
    btnPasteControl.addEventListener("click", () => {
      if (!selectedControl || !copiedControlEntry) return;
      if (!canPasteToControl(selectedControl)) return;
      const err = $("#editError");
      if (err) err.textContent = "";
      void (async () => {
        try {
          const entry = deepCloneJson(copiedControlEntry);
          // Live S page-switch buttons are reserved for page switching; only LED color is editable.
          if (isLiveSPageSwitchButton(selectedControl)) {
            const c = entry && entry.button_color ? String(entry.button_color).trim() : "";
            if (c) setButtonEntry(selectedControl, { button_color: c });
            else setButtonEntry(selectedControl, null);
          } else {
            setButtonEntry(selectedControl, entry);
          }
          renderDeck();
          openEditor(selectedControl);
          clearTimeout(autosaveTimer);
          autosaveTimer = null;
          const ok = await runAutosave();
          if (!ok) return;
          await refreshSkin();
          setSaveStatus(`Pasted onto ${selectedControl}`);
        } catch (e) {
          if (err) err.textContent = String(e);
        }
      })();
    });
  }
  const btnTestPress = $("#btnTestPress");
  if (btnTestPress) {
    btnTestPress.addEventListener("click", () => {
      if (!selectedControl || !controlCanSimulate(selectedControl)) return;
      const err = $("#editError");
      if (err) err.textContent = "";
      void (async () => {
        try {
          await postSimulatePress(selectedControl, null);
        } catch (e) {
          if (err) err.textContent = String(e);
        }
      })();
    });
  }
  const btnTestKnobPush = $("#btnTestKnobPush");
  const btnTestKnobLeft = $("#btnTestKnobLeft");
  const btnTestKnobRight = $("#btnTestKnobRight");
  if (btnTestKnobPush) {
    btnTestKnobPush.addEventListener("click", () => {
      if (!selectedKnobEncoder) return;
      const err = $("#knobEncoderError");
      if (err) err.textContent = "";
      void (async () => {
        try {
          await postSimulatePress(selectedKnobEncoder, null);
        } catch (e) {
          if (err) err.textContent = String(e);
        }
      })();
    });
  }
  if (btnTestKnobLeft) {
    btnTestKnobLeft.addEventListener("click", () => {
      if (!selectedKnobEncoder) return;
      const err = $("#knobEncoderError");
      if (err) err.textContent = "";
      void (async () => {
        try {
          await postSimulatePress(selectedKnobEncoder, "left");
        } catch (e) {
          if (err) err.textContent = String(e);
        }
      })();
    });
  }
  if (btnTestKnobRight) {
    btnTestKnobRight.addEventListener("click", () => {
      if (!selectedKnobEncoder) return;
      const err = $("#knobEncoderError");
      if (err) err.textContent = "";
      void (async () => {
        try {
          await postSimulatePress(selectedKnobEncoder, "right");
        } catch (e) {
          if (err) err.textContent = String(e);
        }
      })();
    });
  }
  const fileUp = $("#fileUp");
  if (fileUp) fileUp.addEventListener("change", uploadImage);
  const btnBrowseImage = $("#btnBrowseImage");
  if (btnBrowseImage && fileUp) {
    btnBrowseImage.addEventListener("click", () => fileUp.click());
  }
  const fileUpFont = $("#fileUpFont");
  if (fileUpFont) fileUpFont.addEventListener("change", uploadFontFile);
  const btnBrowseFont = $("#btnBrowseFont");
  if (btnBrowseFont && fileUpFont) {
    btnBrowseFont.addEventListener("click", () => fileUpFont.click());
  }

  $("#actionType").addEventListener("change", () => {
    const t = $("#actionType").value;
    renderActionFields(t);
    const adv = $("#actionJsonAdv");
    if (adv) {
      if (t) {
        const spec = getSpec(t);
        const base = { type: t };
        if (spec && spec.fields) {
          for (const f of spec.fields) {
            if (f.default != null) base[f.name] = f.input === "number" ? Number(f.default) : f.default;
          }
        }
        adv.value = JSON.stringify(base, null, 2);
        lastSyncedAdv = adv.value.trim();
      } else {
        adv.value = "";
        lastSyncedAdv = "";
      }
    }
  });

  $("#pageNameInput").addEventListener("input", () => {
    currentPage().name = $("#pageNameInput").value;
    $("#pageName").textContent = currentPage().name || `Page ${pageIndex + 1}`;
    syncPageSelect();
    scheduleAutosave();
  });

  if (dm) dm.addEventListener("change", onModelChange);

  wireButtonColorInputs();
  wireDesignFieldInputs();
  wireKeyEditorAutoCommit();

  const btnKnobPages = $("#btnApplyKnobPages");
  if (btnKnobPages) btnKnobPages.addEventListener("click", () => void applyKnobPagesJson());

  const btnSaveKnobEnc = $("#btnSaveKnobEncoderPages");
  if (btnSaveKnobEnc) btnSaveKnobEnc.addEventListener("click", () => void saveKnobEncoderPagesFromForm());
  const btnAddKnobPg = $("#btnAddKnobEncoderPage");
  if (btnAddKnobPg) btnAddKnobPg.addEventListener("click", () => addKnobEncoderPageRow({}));
  const btnCloseKnob = $("#btnCloseKnobEncoderEditor");
  if (btnCloseKnob) btnCloseKnob.addEventListener("click", closeKnobEncoderEditor);

  const knobPgMount = $("#knobEncoderPagesMount");
  if (knobPgMount) {
    knobPgMount.addEventListener("click", (ev) => {
      const t = ev.target;
      if (t && t.classList && t.classList.contains("btn-remove-knob-page")) {
        const fs = t.closest(".knob-page-fieldset");
        if (fs) {
          fs.remove();
          renumberKnobPageLegends();
        }
      }
    });
  }

  startConnectionStatusPolling();

  const btnSpotifySave = $("#btnSpotifySave");
  if (btnSpotifySave) btnSpotifySave.addEventListener("click", () => void saveSpotifySettings());
  const btnSpotifyConnect = $("#btnSpotifyConnect");
  if (btnSpotifyConnect) {
    btnSpotifyConnect.addEventListener("click", () => {
      window.location.href = "/api/spotify/login";
    });
  }
  const btnSpotifyDisconnect = $("#btnSpotifyDisconnect");
  if (btnSpotifyDisconnect) {
    btnSpotifyDisconnect.addEventListener("click", () => {
      void (async () => {
        try {
          const r = await fetch("/api/spotify/disconnect", { method: "POST" });
          if (!r.ok) throw new Error(await r.text());
          await refreshSpotifyStatus();
        } catch (e) {
          const errEl = $("#spotifyErrorLine");
          if (errEl) {
            errEl.hidden = false;
            errEl.textContent = String(e);
          }
        }
      })();
    });
  }

  const btnAddTwitch = $("#btnAddTwitchAccount");
  if (btnAddTwitch) {
    btnAddTwitch.addEventListener("click", () => {
      ensureTwitch();
      cfg.twitch.push({ client_id: "", client_secret: "", access_token: "" });
      renderTwitchAccounts();
      scheduleAutosave();
    });
  }

  for (const id of [
    "buttonText",
    "iconUri",
    "imagePath",
    "textColor",
    "backgroundColor",
    "fontSize",
    "fontFilePath",
    "graphicTextLayout",
  ]) {
    const el = document.getElementById(id);
    if (!el) continue;
    el.addEventListener(el.tagName === "SELECT" ? "change" : "input", scheduleSidebarPreviewRefresh);
  }

  suppressAutosave = false;
  setSaveStatus("Saved");
}

document.addEventListener("DOMContentLoaded", init);
