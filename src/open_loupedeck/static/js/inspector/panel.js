/*
 * inspector/panel.js — Inspector chrome shared by the key and encoder editors: which panel is shown,
 * page-switch-button mode, button enabled states, the sticky autosave/validation line.
 */

import { canPasteToControl, controlCanSimulate, getButtonEntry, isLiveSPageSwitchButton } from "../model.js";
import { state } from "../state.js";
import { $ } from "../util.js";

export function syncTestPressButton() {
  const btn = $("#btnTestPress");
  if (!btn) return;
  const ok = controlCanSimulate(state.selectedControl);
  btn.disabled = !state.selectedControl || !ok;
  btn.title = ok
    ? "Run the same action as a physical press on this control (no USB)"
    : "Side strips are not simulated (hardware uses touch coordinates)";
}

export function syncCopyPasteButtons() {
  const bCopy = $("#btnCopyControl");
  const bPaste = $("#btnPasteControl");
  if (bCopy) bCopy.disabled = !state.selectedControl || !getButtonEntry(state.selectedControl);
  if (bPaste) {
    const ok = !!state.selectedControl && !!state.copiedControlEntry && canPasteToControl(state.selectedControl);
    bPaste.disabled = !ok;
  }
}

export function syncKeyEditorPageSwitchMode(cid) {
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

export function showKeyEditorPanel() {
  const k = $("#keyEditorBlock");
  const kn = $("#knobEncoderEditorBlock");
  if (k) k.hidden = false;
  if (kn) kn.hidden = true;
}

export function setEditorAutosaveStatus(message) {
  const el = $("#editorAutosaveStatus");
  if (!el) return;
  el.textContent = message || "";
  el.classList.toggle("invalid", !!message);
}
