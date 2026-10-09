/*
 * services/system.js — Services toolbar: open the config folder, start at login.
 */

import { $ } from "../util.js";

/** Services toolbar: open the config folder. */
export function wireOpenConfigFolderButton() {
  const btnOpenConfigFolder = $("#btnOpenConfigFolder");
  if (btnOpenConfigFolder) {
    btnOpenConfigFolder.addEventListener("click", () => {
      void fetch("/api/open_config_folder", { method: "POST" }).catch(() => {
        /* best-effort */
      });
    });
  }
}

/** Services toolbar: "start at login" toggle (reads the current state first). */
export async function initAutostartToggle() {
  const autostartEl = $("#autostartToggle");
  if (autostartEl) {
    try {
      const ar = await fetch("/api/autostart");
      if (ar.ok) {
        const aj = await ar.json();
        autostartEl.checked = !!aj.enabled;
      }
    } catch {
      /* leave unchecked; user can still toggle */
    }
    autostartEl.addEventListener("change", () => {
      void (async () => {
        try {
          await fetch("/api/autostart", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ enabled: autostartEl.checked }),
          });
        } catch (e) {
          autostartEl.checked = !autostartEl.checked;
          $("#saveError").textContent = String(e);
        }
      })();
    });
  }
}
