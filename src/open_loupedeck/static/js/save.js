/*
 * save.js — Autosave: debounced PUT of state.cfg, the header save-status text, flushing a pending save
 * (so a dependent request, like the agent's page index, never overtakes it) and cancelling it.
 */

import { apiPut } from "./api.js";
import { state } from "./state.js";
import { $ } from "./util.js";

/** True between scheduleAutosave() and the moment the PUT starts. */
let dirty = false;
/** The PUT currently in flight (resolved when nothing is being saved). */
let inflight = Promise.resolve(true);

export function setSaveStatus(text, isError = false) {
  const el = $("#saveStatus");
  if (!el) return;
  el.textContent = text || "";
  el.classList.toggle("save-status-error", !!isError);
}

export function scheduleAutosave() {
  if (state.suppressAutosave) return;
  clearTimeout(state.autosaveTimer);
  dirty = true;
  setSaveStatus(t("status.pending"));
  state.autosaveTimer = setTimeout(() => {
    void runAutosave();
  }, 500);
}

/** Drop a pending debounced save (callers then save immediately, or not at all). */
export function cancelPendingAutosave() {
  clearTimeout(state.autosaveTimer);
  state.autosaveTimer = null;
  dirty = false;
}

async function putConfig() {
  $("#saveError").textContent = "";
  setSaveStatus(t("status.saving"));
  try {
    await apiPut(state.cfg);
    setSaveStatus(t("status.saved"));
    return true;
  } catch (e) {
    $("#saveError").textContent = String(e);
    setSaveStatus(t("status.save_failed"), true);
    return false;
  }
}

export function runAutosave() {
  cancelPendingAutosave();
  // Chain behind an earlier PUT so two saves can never land out of order.
  inflight = inflight.then(putConfig);
  return inflight;
}

/** Resolve once everything edited so far is on disk and known to the agent. */
export async function flushAutosave() {
  if (dirty) return runAutosave();
  return inflight;
}
