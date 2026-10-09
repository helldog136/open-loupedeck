/*
 * services/obs.js — Services → OBS: WebSocket host / port / password (cfg.obs).
 */

import { FIELD_VALIDATORS, wireSmartField } from "../forms.js";
import { state } from "../state.js";
import { $ } from "../util.js";

export function ensureObs() {
  if (!state.cfg.obs || typeof state.cfg.obs !== "object") {
    state.cfg.obs = { host: "127.0.0.1", port: 4455, password: "" };
  }
}

export function syncObsFromCfg() {
  ensureObs();
  const hostEl = $("#obsHost");
  const portEl = $("#obsPort");
  const pwEl = $("#obsPassword");
  if (hostEl) hostEl.value = state.cfg.obs.host || "";
  if (portEl) portEl.value = state.cfg.obs.port != null ? String(state.cfg.obs.port) : "";
  if (pwEl) pwEl.value = state.cfg.obs.password || "";
}

/** Services → OBS: host, port and password fields. */
export function wireObsFields() {
  wireSmartField($("#obsHost"), {
    validate: () => true,
    onCommit: (raw) => {
      ensureObs();
      state.cfg.obs.host = raw.trim();
    },
  });
  wireSmartField($("#obsPort"), {
    validate: (v) => FIELD_VALIDATORS.port(v) || "Port must be an integer 1–65535",
    optional: false,
    onCommit: (raw) => {
      ensureObs();
      state.cfg.obs.port = Number(raw.trim());
    },
  });
  wireSmartField($("#obsPassword"), {
    validate: () => true,
    onCommit: (raw) => {
      ensureObs();
      state.cfg.obs.password = raw;
    },
  });
}
