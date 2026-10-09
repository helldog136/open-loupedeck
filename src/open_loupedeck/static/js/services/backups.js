/*
 * services/backups.js — Services → Backups: list/restore/remove config backups, backup now, reset the
 * layout to defaults.
 */

import { apiGet, refreshSkin } from "../api.js";
import { renderDeck } from "../deck.js";
import { closeKnobEncoderEditor, syncKnobPagesEditor } from "../knobs.js";
import { currentPage, ensureDevice } from "../model.js";
import { pullAgentLayoutAndPage, syncPageSelect, updateLiveSPageChrome } from "../pages.js";
import { cancelPendingAutosave, runAutosave, setSaveStatus } from "../save.js";
import { ensureLogging, syncLoggingFromCfg } from "./logging.js";
import { syncSpotifyFromCfg } from "./spotify.js";
import { state } from "../state.js";
import { applyCfgSnapshot, snapshotBeforeAction } from "../undo.js";
import { $ } from "../util.js";

async function backupConfig() {
  $("#saveError").textContent = "";
  cancelPendingAutosave();
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

export async function refreshBackupsList() {
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
      JSON.stringify({ cfg: j.config, pageIndex: Math.max(0, Math.min(state.pageIndex, restoredPageCount - 1)) }),
    );
    state.selectedControl = null;
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
  cancelPendingAutosave();
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
  cancelPendingAutosave();
  setSaveStatus("Resetting…");
  try {
    const r = await fetch("/api/config/reset", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirm: true }),
    });
    if (!r.ok) throw new Error(await r.text());
    const j = await r.json();
    state.cfg = await apiGet();
    state.suppressAutosave = true;
    ensureDevice();
    await pullAgentLayoutAndPage();
    updateLiveSPageChrome();
    syncSpotifyFromCfg();
    ensureLogging();
    syncLoggingFromCfg();
    $("#pageName").textContent = currentPage().name || `Page ${state.pageIndex + 1}`;
    const pnR = $("#pageNameInput");
    if (pnR) pnR.value = currentPage().name || "";
    syncPageSelect();
    renderDeck();
    syncKnobPagesEditor();
    state.suppressAutosave = false;
    setSaveStatus("Reset ok");
    await refreshSkin();
  } catch (e) {
    $("#saveError").textContent = String(e);
    setSaveStatus("Reset failed", true);
  }
}

/** Services → Backups: backup now, remove backups, reset layout. */
export function wireBackupButtons() {
  const btnBackup = $("#btnBackup");
  if (btnBackup) btnBackup.addEventListener("click", () => void backupConfig());
  const btnWipeBackups = $("#btnWipeBackups");
  if (btnWipeBackups) btnWipeBackups.addEventListener("click", () => void wipeBackupsConfig());
  const btnReset = $("#btnResetDefaults");
  if (btnReset) btnReset.addEventListener("click", () => void resetConfigToDefaults());
}
