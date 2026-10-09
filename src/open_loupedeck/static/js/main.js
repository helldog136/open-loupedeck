/*
 * main.js — Entry point (loaded as <script type="module">): boots every module in the original order
 * on DOMContentLoaded and hosts the cross-module reactions (config replaced, device model change).
 */

import { apiGet } from "./api.js";
import { populateActionTypeSelect } from "./catalog.js";
import { renderDeck } from "./deck.js";
import { loadCopiedControlFromStorage, wireCopyPasteButtons } from "./inspector/clipboard.js";
import {
  openEditor,
  wireActionTypeSelect,
  wireApplyClearButtons,
  wireKeyEditorAutoCommit,
  wireTestPressButton,
  wireUploadButtons,
} from "./inspector/editor.js";
import { syncCopyPasteButtons, syncTestPressButton } from "./inspector/panel.js";
import {
  wireButtonColorInputs,
  wireDesignFieldInputs,
  wireSidebarPreviewInputs,
} from "./inspector/preview.js";
import {
  closeKnobEncoderEditor,
  openKnobEncoderEditor,
  syncKnobPagesEditor,
  wireKnobEditorButtons,
  wireKnobTestButtons,
} from "./knobs.js";
import { currentPage, ensureDevice, ensureGlobalButtons, ensurePages, liveKnobEncoderIds } from "./model.js";
import {
  pullAgentLayoutAndPage,
  syncAgentPageIndex,
  syncPageSelect,
  updateLiveSPageChrome,
  wirePageNameInput,
  wirePageSelect,
} from "./pages.js";
import { scheduleAutosave, setSaveStatus } from "./save.js";
import { refreshBackupsList, wireBackupButtons } from "./services/backups.js";
import { ensureHa, syncHaFromCfg, wireHaFields } from "./services/ha.js";
import { ensureLogging, syncLoggingFromCfg, wireLogLevelSelect } from "./services/logging.js";
import { ensureObs, syncObsFromCfg, wireObsFields } from "./services/obs.js";
import {
  handleSpotifyReturnQuery,
  refreshSpotifyStatus,
  syncSpotifyFromCfg,
  wireSpotifyButtons,
} from "./services/spotify.js";
import { initAutostartToggle, wireOpenConfigFolderButton } from "./services/system.js";
import { ensureTwitch, renderTwitchAccounts, wireTwitchAddButton } from "./services/twitch.js";
import { wireTabBar } from "./shell.js";
import { on, state } from "./state.js";
import { startConnectionStatusPolling } from "./status.js";
import { wireUndoRedoKeyboard } from "./undo.js";
import { $ } from "./util.js";

/** Re-sync every view after `cfg`/`pageIndex` were replaced wholesale (undo/redo, backup restore). */
function onConfigReplaced(prevPageIndex) {
  ensurePages();
  ensureDevice();
  ensureLogging();
  ensureHa();
  ensureObs();
  ensureTwitch();
  ensureGlobalButtons();
  if (state.pageIndex >= state.cfg.pages.length) state.pageIndex = Math.max(0, state.cfg.pages.length - 1);
  syncSpotifyFromCfg();
  syncLoggingFromCfg();
  syncHaFromCfg();
  syncObsFromCfg();
  renderTwitchAccounts();
  syncPageSelect();
  renderDeck();
  if (state.selectedControl) openEditor(state.selectedControl);
  scheduleAutosave();
  if (state.pageIndex !== prevPageIndex) syncAgentPageIndex();
}

/** Services toolbar: device model select (auto / Live S / Live) re-lays out the deck and editors. */
function onModelChange() {
  ensureDevice();
  const sel = $("#deviceModel");
  if (sel) state.cfg.device.model = sel.value;
  ensurePages();
  updateLiveSPageChrome();
  renderDeck();
  if (state.selectedKnobEncoder && !liveKnobEncoderIds().includes(state.selectedKnobEncoder)) {
    closeKnobEncoderEditor();
  } else if (state.selectedKnobEncoder) {
    openKnobEncoderEditor(state.selectedKnobEncoder);
  } else if (state.selectedControl) {
    openEditor(state.selectedControl);
  }
  scheduleAutosave();
}

/** Fetch the action catalog and the config; false (error shown) when the config cannot be loaded. */
async function loadCatalogAndConfig() {
  try {
    const cr = await fetch("/api/action_catalog");
    if (cr.ok) {
      const j = await cr.json();
      state.actionCatalog = j.actions || [];
    }
    populateActionTypeSelect();
    state.cfg = await apiGet();
  } catch (e) {
    $("#saveError").textContent = String(e);
    return false;
  }
  return true;
}

/**
 * Boot sequence. The order is the historical one from the single-file app.js: keep it unless you
 * know why (e.g. listeners on the same element run in registration order, autosave stays
 * suppressed until the very end).
 */
async function init() {
  wireTabBar();
  wireUndoRedoKeyboard();
  void refreshBackupsList();
  if (!(await loadCatalogAndConfig())) return;
  loadCopiedControlFromStorage();
  syncSpotifyFromCfg();
  void refreshSpotifyStatus();
  handleSpotifyReturnQuery();
  ensureTwitch();
  renderTwitchAccounts();
  ensureDevice();
  ensureLogging();
  syncLoggingFromCfg();
  wireLogLevelSelect();
  syncHaFromCfg();
  wireHaFields();
  syncObsFromCfg();
  wireObsFields();
  wireOpenConfigFolderButton();
  await initAutostartToggle();
  await pullAgentLayoutAndPage();
  updateLiveSPageChrome();
  const dm = $("#deviceModel");
  if (dm) dm.value = state.cfg.device.model || "auto";

  $("#pageName").textContent = currentPage().name || `Page ${state.pageIndex + 1}`;
  const pnInit = $("#pageNameInput");
  if (pnInit) pnInit.value = currentPage().name || "";
  syncPageSelect();
  renderDeck();
  syncKnobPagesEditor();
  syncTestPressButton();
  syncCopyPasteButtons();

  wirePageSelect();
  wireBackupButtons();
  wireApplyClearButtons();
  wireCopyPasteButtons();
  wireTestPressButton();
  wireKnobTestButtons();
  wireUploadButtons();
  wireActionTypeSelect();
  wirePageNameInput();
  if (dm) dm.addEventListener("change", onModelChange);

  wireButtonColorInputs();
  wireDesignFieldInputs();
  wireKeyEditorAutoCommit();

  wireKnobEditorButtons();
  startConnectionStatusPolling();

  wireSpotifyButtons();
  wireTwitchAddButton();
  wireSidebarPreviewInputs();
  state.suppressAutosave = false;
  setSaveStatus("Saved");
}

on("config:replaced", onConfigReplaced);
on("control:open", openEditor);
document.addEventListener("DOMContentLoaded", init);
