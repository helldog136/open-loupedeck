/*
 * inspector/editor.js — Key editor: open a control into the form, build the entry from the form,
 * autosave while typing, Apply / Clear, image and font uploads, test press, action type changes.
 */

import {
  buildActionFromFormIn,
  fillActionFieldsInContainer,
  mergeAssetFieldValuesFromForm,
  renderActionFieldsInto,
} from "../action-fields.js";
import { postSimulatePress, refreshSkin, uploadFileToAssets } from "../api.js";
import { getSpec } from "../catalog.js";
import { renderDeck } from "../deck.js";
import {
  fillLookFieldsFromEntry,
  populateDesignFieldsFromEntry,
  readDesignFieldsFromForm,
  syncGraphicLayoutVisibility,
  syncLiveSButtonColorBlock,
} from "./look-fields.js";
import {
  setEditorAutosaveStatus,
  showKeyEditorPanel,
  syncCopyPasteButtons,
  syncKeyEditorPageSwitchMode,
  syncTestPressButton,
} from "./panel.js";
import {
  maybeStartSidebarAnimPreview,
  scheduleSidebarPreviewRefresh,
  updatePreviewFromEntry,
} from "./preview.js";
import { openKnobEncoderEditor } from "../knobs.js";
import {
  controlCanSimulate,
  getButtonEntry,
  isKnobEncoderId,
  isLiveSPageSwitchButton,
  isLiveSPhysicalButton,
  setButtonEntry,
} from "../model.js";
import { cancelPendingAutosave, runAutosave, scheduleAutosave } from "../save.js";
import { state } from "../state.js";
import { snapshotBeforeAction, snapshotBeforeEditOnce } from "../undo.js";
import { $, sanitizeButtonColorHex } from "../util.js";

function renderActionFields(type) {
  const container = $("#actionFields");
  if (!container) return;
  renderActionFieldsInto(container, type, "ap");
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
    state.lastSyncedAdv = adv.value.trim();
  }
}

function useAdvancedJson() {
  const det = $("#advJsonDetails");
  const adv = $("#actionJsonAdv");
  if (!det || !det.open || !adv) return false;
  const cur = adv.value.trim();
  if (!cur) return false;
  return cur !== state.lastSyncedAdv;
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

/** Reset the main action picker, its parameter fields and the Advanced JSON to "no action". */
function clearMainActionForm() {
  const sel = $("#actionType");
  if (sel) {
    sel.value = "";
    if (sel._refreshActionSelectTrigger) sel._refreshActionSelectTrigger();
  }
  renderActionFields("");
  const adv = $("#actionJsonAdv");
  if (adv) {
    adv.value = "";
    state.lastSyncedAdv = "";
  }
}

export function openEditor(cid) {
  if (isKnobEncoderId(cid)) {
    openKnobEncoderEditor(cid);
    return;
  }
  state.selectedKnobEncoder = null;
  showKeyEditorPanel();

  state.selectedControl = cid;
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
    clearMainActionForm();
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
    fillLookFieldsFromEntry(e);
  } else {
    clearMainActionForm();
    fillLookFieldsFromEntry(e);
  }
  syncGraphicLayoutVisibility();

  syncLiveSButtonColorBlock(cid, e);
  syncKeyEditorPageSwitchMode(cid);

  void updatePreviewFromEntry(e, cid);
  maybeStartSidebarAnimPreview(e, cid);
  syncTestPressButton();
  syncCopyPasteButtons();
}

async function saveAction() {
  if (state.selectedKnobEncoder) return;
  if (!state.selectedControl) return;
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
  setButtonEntry(state.selectedControl, entry);
  renderDeck();
  openEditor(state.selectedControl);
  cancelPendingAutosave();
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
  if (isLiveSPageSwitchButton(state.selectedControl)) {
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

  if (isLiveSPhysicalButton(state.selectedControl)) {
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
    !(isLiveSPhysicalButton(state.selectedControl) && entry.button_color)
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
  if (state.selectedKnobEncoder || !state.selectedControl) return;
  let entry;
  try {
    entry = buildEntryFromFormOrThrow();
  } catch (err) {
    setEditorAutosaveStatus(err.message || String(err));
    return;
  }
  setEditorAutosaveStatus("");
  $("#editError").textContent = "";
  setButtonEntry(state.selectedControl, entry);
  renderDeck();
  scheduleAutosave();
}

/**
 * Delegated wiring for the whole button-editor form: any field inside #keyEditorBlock triggers a
 * silent, validation-gated autosave on "input"/"change", and a full commit (openEditor refresh +
 * immediate save + device redraw) on "focusout" (bubbles, unlike "blur" — no capture needed).
 * Covers every current field (and any future action-catalog-driven one) without per-field wiring.
 */
export function wireKeyEditorAutoCommit() {
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

async function clearControl() {
  if (state.selectedKnobEncoder) return;
  if (!state.selectedControl) return;
  snapshotBeforeAction();
  if (isLiveSPageSwitchButton(state.selectedControl)) {
    setButtonEntry(state.selectedControl, null);
    renderDeck();
    openEditor(state.selectedControl);
    cancelPendingAutosave();
    const ok = await runAutosave();
    if (!ok) return;
    await refreshSkin();
    return;
  }
  setButtonEntry(state.selectedControl, null);
  renderDeck();
  openEditor(state.selectedControl);
  cancelPendingAutosave();
  const ok = await runAutosave();
  if (!ok) return;
  await refreshSkin();
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

/** Key editor: Apply to key / Clear. */
export function wireApplyClearButtons() {
  $("#btnApply").addEventListener("click", () => void saveAction());
  $("#btnClear").addEventListener("click", () => void clearControl());
}

/** Key editor: simulate a press of the selected control. */
export function wireTestPressButton() {
  const btnTestPress = $("#btnTestPress");
  if (btnTestPress) {
    btnTestPress.addEventListener("click", () => {
      if (!state.selectedControl || !controlCanSimulate(state.selectedControl)) return;
      const err = $("#editError");
      if (err) err.textContent = "";
      void (async () => {
        try {
          await postSimulatePress(state.selectedControl, null);
        } catch (e) {
          if (err) err.textContent = String(e);
        }
      })();
    });
  }
}

/** Key editor: image and font Browse… buttons. */
export function wireUploadButtons() {
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
}

/** Key editor: action type change re-renders the parameter fields and Advanced JSON. */
export function wireActionTypeSelect() {
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
        state.lastSyncedAdv = adv.value.trim();
      } else {
        adv.value = "";
        state.lastSyncedAdv = "";
      }
    }
  });
}
