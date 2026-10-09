/*
 * inspector/panel.js — Inspector chrome shared with other modules: the enabled state of the header
 * buttons (copy / paste / clear) and of the test-press button. Modules that change the selection
 * (pages.js) call these; the inspector re-syncs itself through the "inspector:sync" event.
 */

import { canPasteToControl, controlCanSimulate, getButtonEntry } from "../model.js";
import { emit, state } from "../state.js";
import { $ } from "../util.js";

export function syncTestPressButton() {
  const btn = $("#btnTestPress");
  if (!btn) return;
  const ok = controlCanSimulate(state.selectedControl);
  btn.disabled = !state.selectedControl || !ok;
}

export function syncCopyPasteButtons() {
  const sel = state.selectedControl;
  const bCopy = $("#btnCopyControl");
  const bPaste = $("#btnPasteControl");
  const bClear = $("#btnClearControl");
  if (bCopy) bCopy.disabled = !sel || !getButtonEntry(sel);
  if (bClear) bClear.disabled = !sel || !getButtonEntry(sel);
  if (bPaste) bPaste.disabled = !(sel && state.copiedControlEntry && canPasteToControl(sel));
  // The selection may have been changed by another module (page switch): let the inspector follow.
  emit("inspector:sync");
}

/** Show the inspector and let it re-sync with the selection. */
export function showKeyEditorPanel() {
  const k = $("#keyEditorBlock");
  if (k) k.hidden = false;
  emit("inspector:sync");
}
