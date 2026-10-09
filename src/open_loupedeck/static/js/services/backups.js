/*
 * services/backups.js — Services → Backups: list/restore/remove config backups, backup now, reset the
 * layout to defaults.
 */

import { apiGet, refreshSkin } from "../api.js";
import { renderDeck } from "../deck.js";
import { closeKnobEncoderEditor, syncKnobPagesEditor } from "../knobs.js";
import { currentPage, ensureDevice } from "../model.js";
import { pullAgentLayoutAndPage, syncPageSelect, updateLiveSPageChrome } from "../pages.js";
import { cancelPendingAutosave, runAutosave, scheduleAutosave, setSaveStatus } from "../save.js";
import { setServiceState, wireInlineConfirm } from "./cards.js";
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
    setSaveStatus(names ? t("svc.backups.done_named", { names }) : t("svc.backups.done"));
    void refreshBackupsList();
  } catch (e) {
    $("#saveError").textContent = String(e);
    setSaveStatus(t("svc.backups.failed"), true);
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
    setServiceState(
      "backups",
      "idle",
      rows.length ? t("svc.backups.count", { count: rows.length }) : t("svc.backups.none"),
    );
    if (!rows.length) {
      mount.innerHTML = "";
      const empty = document.createElement("p");
      empty.className = "hint";
      empty.textContent = t("svc.backups.empty");
      mount.appendChild(empty);
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
      btn.className = "btn btn-sm";
      btn.textContent = t("svc.backups.restore");
      wireInlineConfirm(btn, {
        promptKey: "svc.backups.restore_prompt",
        confirmKey: "svc.backups.restore_yes",
        vars: { name: b.name },
        onConfirm: () => void restoreBackupByName(b.name),
      });
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
    setSaveStatus(t("svc.backups.restored", { name }));
    void refreshBackupsList();
  } catch (e) {
    $("#saveError").textContent = String(e);
    setSaveStatus(t("svc.backups.restore_failed"), true);
  }
}

async function wipeBackupsConfig() {
  $("#saveError").textContent = "";
  cancelPendingAutosave();
  const saved = await runAutosave();
  if (!saved) return;
  try {
    const r = await fetch("/api/config/backups/wipe", { method: "POST" });
    if (!r.ok) throw new Error(await r.text());
    const j = await r.json();
    const n = j.count ?? 0;
    setSaveStatus(n ? t("svc.backups.removed", { count: n }) : t("svc.backups.none_to_remove"));
    void refreshBackupsList();
  } catch (e) {
    $("#saveError").textContent = String(e);
    setSaveStatus(t("svc.backups.remove_failed"), true);
  }
}

async function resetConfigToDefaults() {
  $("#saveError").textContent = "";
  cancelPendingAutosave();
  setSaveStatus(t("svc.maint.resetting"));
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
    $("#pageName").textContent = currentPage().name || t("pages.default_name", { number: state.pageIndex + 1 });
    syncPageSelect();
    renderDeck();
    syncKnobPagesEditor();
    state.suppressAutosave = false;
    scheduleAutosave(); // the four hardware pages may have been padded on load
    setSaveStatus(t("svc.maint.reset_done"));
    await refreshSkin();
  } catch (e) {
    $("#saveError").textContent = String(e);
    setSaveStatus(t("svc.maint.reset_failed"), true);
  }
}

/** Services → Backups: backup now, remove backups, reset layout. */
export function wireBackupButtons() {
  const btnBackup = $("#btnBackup");
  if (btnBackup) btnBackup.addEventListener("click", () => void backupConfig());
  const btnWipeBackups = $("#btnWipeBackups");
  if (btnWipeBackups) {
    wireInlineConfirm(btnWipeBackups, {
      promptKey: "svc.maint.wipe_prompt",
      confirmKey: "svc.maint.wipe_yes",
      onConfirm: () => void wipeBackupsConfig(),
    });
  }
  const btnReset = $("#btnResetDefaults");
  if (btnReset) {
    wireInlineConfirm(btnReset, {
      promptKey: "svc.maint.reset_prompt",
      confirmKey: "svc.maint.reset_yes",
      onConfirm: () => void resetConfigToDefaults(),
    });
  }
}
