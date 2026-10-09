/*
 * services/ha.js — Services → Home Assistant: base URL and long-lived token (cfg.ha).
 */

import { wireSmartField } from "../forms.js";
import { state } from "../state.js";
import { $ } from "../util.js";

export function ensureHa() {
  if (!state.cfg.ha || typeof state.cfg.ha !== "object") {
    state.cfg.ha = { base_url: "", token: "" };
  }
}

export function syncHaFromCfg() {
  ensureHa();
  const urlEl = $("#haBaseUrl");
  const tokEl = $("#haToken");
  if (urlEl) urlEl.value = state.cfg.ha.base_url || "";
  if (tokEl) tokEl.value = state.cfg.ha.token || "";
}

/** Services → Home Assistant: URL and token fields. */
export function wireHaFields() {
  wireSmartField($("#haBaseUrl"), {
    validate: () => true,
    onCommit: (raw) => {
      ensureHa();
      state.cfg.ha.base_url = raw.trim();
    },
  });
  wireSmartField($("#haToken"), {
    validate: () => true,
    onCommit: (raw) => {
      ensureHa();
      state.cfg.ha.token = raw.trim();
    },
  });
}
