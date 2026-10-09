/*
 * inspector/clipboard.js — Copy / paste a control's entry between keys (persisted in localStorage).
 */

import { refreshSkin } from "../api.js";
import { renderDeck } from "../deck.js";
import { openEditor } from "./editor.js";
import { syncCopyPasteButtons } from "./panel.js";
import { canPasteToControl, getButtonEntry, isLiveSPageSwitchButton, setButtonEntry } from "../model.js";
import { cancelPendingAutosave, runAutosave, setSaveStatus } from "../save.js";
import { state } from "../state.js";
import { $, deepCloneJson } from "../util.js";

export function loadCopiedControlFromStorage() {
  try {
    const raw = localStorage.getItem("ld_clipboard_control_v1");
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
    localStorage.setItem(
      "ld_clipboard_control_v1",
      JSON.stringify({ entry: state.copiedControlEntry, meta: state.copiedControlMeta })
    );
  } catch {
    /* ignore */
  }
}

/** Key editor: copy / paste a control (clipboard persisted in localStorage). */
export function wireCopyPasteButtons() {
  const btnCopyControl = $("#btnCopyControl");
  const btnPasteControl = $("#btnPasteControl");
  if (btnCopyControl) {
    btnCopyControl.addEventListener("click", () => {
      if (!state.selectedControl) return;
      const e = getButtonEntry(state.selectedControl);
      if (!e) return;
      state.copiedControlEntry = deepCloneJson(e);
      state.copiedControlMeta = {
        cid: state.selectedControl,
        at: Date.now(),
      };
      saveCopiedControlToStorage();
      setSaveStatus(`Copied ${state.selectedControl}`);
      syncCopyPasteButtons();
    });
  }
  if (btnPasteControl) {
    btnPasteControl.addEventListener("click", () => {
      if (!state.selectedControl || !state.copiedControlEntry) return;
      if (!canPasteToControl(state.selectedControl)) return;
      const err = $("#editError");
      if (err) err.textContent = "";
      void (async () => {
        try {
          const entry = deepCloneJson(state.copiedControlEntry);
          // Live S page-switch buttons are reserved for page switching; only LED color is editable.
          if (isLiveSPageSwitchButton(state.selectedControl)) {
            const c = entry && entry.button_color ? String(entry.button_color).trim() : "";
            if (c) setButtonEntry(state.selectedControl, { button_color: c });
            else setButtonEntry(state.selectedControl, null);
          } else {
            setButtonEntry(state.selectedControl, entry);
          }
          renderDeck();
          openEditor(state.selectedControl);
          cancelPendingAutosave();
          const ok = await runAutosave();
          if (!ok) return;
          await refreshSkin();
          setSaveStatus(`Pasted onto ${state.selectedControl}`);
        } catch (e) {
          if (err) err.textContent = String(e);
        }
      })();
    });
  }
}
