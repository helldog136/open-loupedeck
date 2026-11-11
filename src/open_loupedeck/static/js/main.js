/*
 * main.js — Entry point (loaded as <script type="module">): boots every module in order on
 * DOMContentLoaded and hosts the cross-module reactions (config replaced, edited device model changed).
 */

import { apiGet } from "./api.js";
import { renderDeck } from "./deck.js";
import "./page-field.js";
import "./pickers/sound-picker.js";
import "./wow-chord.js";
import { loadCopiedControlFromStorage } from "./inspector/clipboard.js";
import { initInspector, refreshInspector } from "./inspector/index.js";
import { ensureDevice, ensureGlobal, ensurePages, loadDeviceModels, resolveEditorModel } from "./model.js";
import { pullAgentPage, refreshPageTabs, syncAgentPageIndex, syncPageSelect, wirePageSelect } from "./pages.js";
import { renderOnboarding, wireOnboarding } from "./onboarding.js";
import { scheduleAutosave, setSaveStatus } from "./save.js";
import { refreshBackupsList, wireBackupButtons } from "./services/backups.js";
import { initBrightnessCard, setServiceState, wireConfigureButtons, wireWowCacheButton } from "./services/cards.js";
import { renderModelSelect, syncModelHint, wireModelSelect } from "./services/device.js";
import { ensureHa, syncHaFromCfg, wireHaFields } from "./services/ha.js";
import { ensureLogging, syncLoggingFromCfg, wireLogLevelSelect } from "./services/logging.js";
import { ensureObs, syncObsFromCfg, wireObsFields } from "./services/obs.js";
import {
  handleSpotifyReturnQuery,
  redrawSpotifyState,
  refreshSpotifyStatus,
  syncSpotifyFromCfg,
  wireSpotifyButtons,
} from "./services/spotify.js";
import { initAutostartToggle, wireOpenConfigFolderButton } from "./services/system.js";
import {
  ensureTwitch,
  redrawTwitchState,
  renderTwitchAccounts,
  wireTwitchAddButton,
  wireTwitchMainButton,
} from "./services/twitch.js";
import { wireTabBar } from "./shell.js";
import { on, state } from "./state.js";
import { renderStatusChips, startConnectionStatusPolling } from "./status.js";
import { wireUndoRedoKeyboard } from "./undo.js";
import { $ } from "./util.js";

/** The edited model changed (device plugged, model select, undo of it): re-lay out everything. */
function onModelChanged() {
  if (state.selectedControl && !(state.model && state.model.controls.some((c) => c.id === state.selectedControl))) {
    state.selectedControl = null;
  }
  state.editScopes.clear();
  renderModelSelect();
  syncPageSelect();
  renderDeck();
  renderOnboarding();
  refreshInspector({ rebuild: true });
}

/** Re-sync every view after `cfg`/`pageIndex` were replaced wholesale (undo/redo, backup restore). */
function onConfigReplaced(prevPageIndex) {
  ensurePages();
  ensureDevice();
  ensureGlobal();
  ensureLogging();
  ensureHa();
  ensureObs();
  ensureTwitch();
  if (state.pageIndex >= state.cfg.pages.length) state.pageIndex = Math.max(0, state.cfg.pages.length - 1);
  syncSpotifyFromCfg();
  syncLoggingFromCfg();
  syncHaFromCfg();
  syncObsFromCfg();
  renderTwitchAccounts();
  if (resolveEditorModel()) onModelChanged();
  else renderModelSelect();
  syncPageSelect();
  renderDeck();
  renderOnboarding();
  refreshInspector();
  scheduleAutosave();
  if (state.pageIndex !== prevPageIndex) void syncAgentPageIndex();
}

/** Services > General > Hardware changed `device.model`. */
function onModelSelected() {
  if (resolveEditorModel()) onModelChanged();
  else syncModelHint();
  scheduleAutosave();
}

/** Fetch the action catalog and the config; false (error shown) when the config cannot be loaded. */
async function loadCatalogAndConfig() {
  try {
    // Labels, option labels and help texts come translated in the UI language.
    if (window.i18n && window.i18n.ready) await window.i18n.ready;
    const lang = (window.i18n && window.i18n.lang) || "";
    const cr = await fetch(`/api/action_catalog${lang ? `?lang=${encodeURIComponent(lang)}` : ""}`);
    if (cr.ok) {
      const j = await cr.json();
      state.actionCatalog = j.actions || [];
    }
    state.cfg = await apiGet();
  } catch (e) {
    $("#saveError").textContent = String(e);
    return false;
  }
  return true;
}

/**
 * Boot sequence. Keep the order unless you know why (e.g. listeners on the same element run in
 * registration order, autosave stays suppressed until the very end).
 */
async function init() {
  // Strings: wait for the language to be loaded so the first render is already translated.
  if (window.i18n && window.i18n.ready) await window.i18n.ready;
  wireTabBar();
  wireUndoRedoKeyboard();
  void refreshBackupsList();
  if (!(await loadCatalogAndConfig())) return;
  ensureDevice();
  ensureGlobal();
  await loadDeviceModels();
  loadCopiedControlFromStorage();
  syncSpotifyFromCfg();
  void refreshSpotifyStatus();
  handleSpotifyReturnQuery();
  ensureTwitch();
  renderTwitchAccounts();
  ensureLogging();
  syncLoggingFromCfg();
  wireLogLevelSelect();
  syncHaFromCfg();
  wireHaFields();
  syncObsFromCfg();
  wireObsFields();
  wireOpenConfigFolderButton();
  wireWowCacheButton();
  renderModelSelect();
  wireModelSelect(onModelSelected);
  await initAutostartToggle();
  await initBrightnessCard();
  const loadedPageCount = Array.isArray(state.cfg.pages) ? state.cfg.pages.length : 0;
  await pullAgentPage();

  syncPageSelect();
  renderDeck();
  renderOnboarding();
  wireOnboarding();

  wirePageSelect();
  wireBackupButtons();
  initInspector();

  startConnectionStatusPolling();

  wireSpotifyButtons();
  wireTwitchAddButton();
  wireTwitchMainButton();
  wireConfigureButtons();
  refreshLanguageCard();
  state.suppressAutosave = false;
  setSaveStatus(t("status.saved"));
  // An older config with fewer than four pages was padded on load: save it so the agent knows them too.
  if (state.cfg.pages.length !== loadedPageCount) scheduleAutosave();
}

/** The Language card's pill shows the language in use. */
function refreshLanguageCard() {
  const api = window.i18n;
  if (!api) return;
  const known = (api.languages || []).find((l) => l.code === api.lang);
  setServiceState("language", "idle", known ? known.name : api.lang);
}

/** A language change re-renders every string that JS (not data-i18n) wrote. */
document.addEventListener("i18n:change", () => {
  if (!state.cfg || !state.cfg.pages) return;
  refreshLanguageCard();
  refreshPageTabs();
  renderModelSelect();
  renderStatusChips();
  redrawSpotifyState();
  redrawTwitchState();
  renderTwitchAccounts();
  void refreshBackupsList();
  setSaveStatus(t("status.saved"));
});

on("config:replaced", onConfigReplaced);
on("model:changed", onModelChanged);
// "control:open" is handled by the inspector (inspector/index.js).
document.addEventListener("DOMContentLoaded", init);
