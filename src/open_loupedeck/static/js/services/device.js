/*
 * services/device.js — Services > General > Hardware: the `device.model` select, listing every model
 * the server knows (Loupedeck, virtual…) plus "Detect automatically", and a line saying which model
 * the editor lays out (the connected device wins over the choice).
 */

import { connectedModel, ensureDevice, knownModels } from "../model.js";
import { state } from "../state.js";
import { snapshotBeforeAction } from "../undo.js";
import { $ } from "../util.js";

const FAMILY_KEYS = { loupedeck: "svc.general.family.loupedeck", virtual: "svc.general.family.virtual" };

/** (Re)build the options and select the configured value. */
export function renderModelSelect() {
  const sel = $("#deviceModel");
  if (!sel) return;
  ensureDevice();
  const value = String(state.cfg.device.model || "auto");
  sel.replaceChildren();
  const auto = document.createElement("option");
  auto.value = "auto";
  auto.textContent = t("svc.general.model_auto");
  sel.append(auto);
  const groups = new Map();
  for (const m of knownModels()) {
    if (!groups.has(m.family)) {
      const g = document.createElement("optgroup");
      const key = FAMILY_KEYS[m.family];
      g.label = key ? t(key) : m.family;
      groups.set(m.family, g);
      sel.append(g);
    }
    const o = document.createElement("option");
    o.value = m.config_name || m.id;
    o.textContent = m.name;
    groups.get(m.family).append(o);
  }
  // A configured name may be an alias (`virtual` for virtual_15): select the model it names.
  const known = knownModels().find((m) => m.id === value || (m.config_names || []).includes(value));
  sel.value = known ? known.config_name || known.id : "auto";
  syncModelHint();
}

/** Which model the editor shows, and why. */
export function syncModelHint() {
  const hint = $("#deviceModelHint");
  if (!hint) return;
  const dev = connectedModel();
  const auto = !state.cfg.device || !state.cfg.device.model || state.cfg.device.model === "auto";
  if (dev) hint.textContent = t("svc.general.model_connected", { name: dev.name });
  else if (auto && state.model) hint.textContent = t("svc.general.model_editing", { name: state.model.name });
  else hint.textContent = "";
}

/** `onChange()` after `device.model` changed (the caller re-lays out the editor and saves). */
export function wireModelSelect(onChange) {
  const sel = $("#deviceModel");
  if (!sel) return;
  sel.addEventListener("change", () => {
    snapshotBeforeAction();
    ensureDevice();
    state.cfg.device.model = sel.value;
    onChange();
  });
}
