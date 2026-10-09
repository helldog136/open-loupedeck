/*
 * services/logging.js — Services → Logging: log level (cfg.logging).
 */

import { scheduleAutosave } from "../save.js";
import { state } from "../state.js";
import { $ } from "../util.js";
import { setServiceState } from "./cards.js";

export function ensureLogging() {
  if (!state.cfg.logging || typeof state.cfg.logging !== "object") {
    state.cfg.logging = { dir: "", level: "INFO", file: true, console: true };
  }
  if (state.cfg.logging.level == null || String(state.cfg.logging.level).trim() === "") {
    state.cfg.logging.level = "INFO";
  }
}

export function syncLoggingFromCfg() {
  const sel = $("#logLevel");
  if (!sel) return;
  let lv = String(state.cfg.logging && state.cfg.logging.level ? state.cfg.logging.level : "INFO").trim().toUpperCase();
  const allowed = new Set(["DEBUG", "INFO", "WARNING", "WARN", "ERROR", "CRITICAL"]);
  if (!allowed.has(lv)) lv = "INFO";
  sel.value = lv;
  setServiceState("logging", "idle", lv);
}

/** Services → Logging: level select. */
export function wireLogLevelSelect() {
  const logLevelEl = $("#logLevel");
  if (logLevelEl) {
    logLevelEl.addEventListener("change", () => {
      ensureLogging();
      state.cfg.logging.level = logLevelEl.value;
      setServiceState("logging", "idle", logLevelEl.value);
      scheduleAutosave();
    });
  }
}
