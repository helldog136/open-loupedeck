/*
 * inspector/clipboard.js — Copy / paste a control's binding between controls (persisted in
 * localStorage) and clear a control. Used by the inspector header buttons. A binding only pastes onto
 * a control of the same shape (a knob role onto a knob, an action + look onto a key / button); it goes
 * to the scope being edited.
 */

import { bindingShape, control, getEntry } from "../model.js";
import { setSaveStatus } from "../save.js";
import { state } from "../state.js";
import { deepCloneJson } from "../util.js";
import { controlName } from "./controls.js";
import { editEntry } from "./edit.js";

const STORAGE_KEY = "ld_clipboard_control_v2";

export function loadCopiedControlFromStorage() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return;
    const j = JSON.parse(raw);
    if (!j || typeof j !== "object") return;
    if (j.entry && typeof j.entry === "object") state.copiedControlEntry = j.entry;
    if (j.meta && typeof j.meta === "object") state.copiedControlMeta = j.meta;
  } catch {
    /* ignore */
  }
}

function saveCopiedControlToStorage() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ entry: state.copiedControlEntry, meta: state.copiedControlMeta }));
  } catch {
    /* private mode / blocked storage: the clipboard still works for this session */
  }
}

export function copyControl(cid) {
  const e = cid && getEntry(cid);
  if (!e) return false;
  state.copiedControlEntry = deepCloneJson(e);
  state.copiedControlMeta = { cid, shape: bindingShape(cid), at: Date.now() };
  saveCopiedControlToStorage();
  setSaveStatus(t("inspector.copy.done", { name: controlName(cid) }));
  return true;
}

export function canPaste(cid) {
  if (!cid || !state.copiedControlEntry || !control(cid)) return false;
  const meta = state.copiedControlMeta || {};
  return (meta.shape || "action") === bindingShape(cid);
}

export function pasteControl(cid) {
  if (!canPaste(cid)) return false;
  const src = deepCloneJson(state.copiedControlEntry);
  editEntry(cid, (e) => {
    for (const k of Object.keys(e)) delete e[k];
    Object.assign(e, src);
  });
  setSaveStatus(t("inspector.paste.done", { name: controlName(cid) }));
  return true;
}

export function clearControl(cid) {
  if (!cid || !getEntry(cid)) return false;
  editEntry(cid, (e) => {
    for (const k of Object.keys(e)) delete e[k];
  });
  setSaveStatus(t("inspector.clear.done", { name: controlName(cid) }));
  return true;
}
