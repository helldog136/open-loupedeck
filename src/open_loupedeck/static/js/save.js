/*
 * save.js — Autosave: debounced PUT of state.cfg, the header save-status text, and cancelling a
 * pending save.
 */

import { apiPut } from "./api.js";
import { state } from "./state.js";
import { $ } from "./util.js";

export function setSaveStatus(text, isError = false) {
  const el = $("#saveStatus");
  if (!el) return;
  el.textContent = text || "";
  el.classList.toggle("save-status-error", !!isError);
}

export function scheduleAutosave() {
  if (state.suppressAutosave) return;
  clearTimeout(state.autosaveTimer);
  setSaveStatus("Pending…");
  state.autosaveTimer = setTimeout(() => {
    void runAutosave();
  }, 500);
}

/** Drop a pending debounced save (callers then save immediately, or not at all). */
export function cancelPendingAutosave() {
  clearTimeout(state.autosaveTimer);
  state.autosaveTimer = null;
}

export async function runAutosave() {
  $("#saveError").textContent = "";
  setSaveStatus("Saving…");
  try {
    await apiPut(state.cfg);
    setSaveStatus("Saved");
    return true;
  } catch (e) {
    const msg = String(e);
    $("#saveError").textContent = msg;
    setSaveStatus("Save failed", true);
    return false;
  }
}
