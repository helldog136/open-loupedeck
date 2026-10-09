/*
 * action-fields.js — Action parameter forms generated from the catalog: render fields into a
 * container, fill them from an action, build an action back from them (main editor and knob rotate
 * blocks).
 */

import { uploadFileToAssets } from "./api.js";
import { getSpec } from "./catalog.js";
import {
  keySequenceStepsFromHidden,
  renderKeySequenceChips,
  renderKeySequenceField,
  stopKeySequenceRecording,
} from "./key-sequence.js";
import { setSaveStatus } from "./save.js";
import { $, uploadLibraryParamForFile } from "./util.js";

/** Resolve a catalog field control inside an action-fields container (data-param + id suffix fallback). */
function actionFieldEl(container, field) {
  if (!container || !field || field.name == null) return null;
  const name = String(field.name);
  const esc =
    typeof CSS !== "undefined" && typeof CSS.escape === "function"
      ? CSS.escape(name)
      : name.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
  let el = container.querySelector(`[data-param="${esc}"]`);
  if (el) return el;
  const suf = name.replace(/[^a-zA-Z0-9_]/g, "_");
  return container.querySelector(`input[id$="_${suf}"],select[id$="_${suf}"],textarea[id$="_${suf}"]`);
}

/** Field label in plain language: the catalog's translated label, plus "(optional)". */
function fieldLabelText(f) {
  const base = f.label || f.name;
  return f.optional ? `${base} ${t("inspector.field.optional")}` : base;
}

/** The catalog's help text for a field, as a hint under it (nothing when there is none). */
function appendFieldHelp(wrap, f) {
  if (!f.help) return;
  const p = document.createElement("p");
  p.className = "hint field-help";
  p.textContent = f.help;
  wrap.appendChild(p);
}

/** One "asset" parameter row: path input + Browse… (uploads to the asset library, fills the path). */
function renderAssetField(container, wrap, f, idPrefix) {
  const lab = document.createElement("label");
  lab.className = "field-label";
  lab.textContent = fieldLabelText(f);
  const fid = `${idPrefix}_${String(f.name).replace(/[^a-zA-Z0-9_]/g, "_")}`;
  const row = document.createElement("div");
  row.className = "path-with-browse";
  const input = document.createElement("input");
  input.type = "text";
  input.dataset.param = f.name;
  input.setAttribute("data-param", String(f.name));
  input.className = "mono path-input";
  input.id = fid;
  lab.htmlFor = fid;
  if (f.placeholder) input.placeholder = f.placeholder;
  const browse = document.createElement("button");
  browse.type = "button";
  browse.className = "btn-browse";
  browse.textContent = t("inspector.field.browse");
  const fileIn = document.createElement("input");
  fileIn.type = "file";
  fileIn.hidden = true;
  fileIn.accept =
    f.accept != null && String(f.accept).trim() !== "" ? String(f.accept) : "*/*";
  browse.addEventListener("click", () => fileIn.click());
  fileIn.addEventListener("change", async (ev) => {
    const file = ev.target.files && ev.target.files[0];
    ev.target.value = "";
    if (!file) return;
    const errEl = $("#editError");
    try {
      const lib = uploadLibraryParamForFile(file);
      const rel = await uploadFileToAssets(file, lib);
      // After `await`, the form may have been re-rendered; the closure `input` can be detached.
      const live =
        document.getElementById(fid) ||
        (container && container.isConnected && container.querySelector(`#${fid}`)) ||
        input;
      if (live) {
        live.value = rel;
        live.dispatchEvent(new Event("input", { bubbles: true }));
      }
      if (errEl) errEl.textContent = "";
      const saveErr = $("#saveError");
      if (saveErr) saveErr.textContent = "";
      if (idPrefix === "ap") setSaveStatus(t("inspector.field.uploaded"));
    } catch (e) {
      const msg = String(e.message || e);
      if (errEl) errEl.textContent = msg;
      const saveErr = $("#saveError");
      if (saveErr) saveErr.textContent = msg;
    }
  });
  row.appendChild(input);
  row.appendChild(browse);
  row.appendChild(fileIn);
  wrap.appendChild(lab);
  wrap.appendChild(row);
  appendFieldHelp(wrap, f);
  container.appendChild(wrap);
}

/**
 * Render action parameter fields into a container (main key editor or knob rotate block).
 * @param {HTMLElement} container
 * @param {string} type action type
 * @param {string} idPrefix unique prefix for input ids (e.g. "ap" for main form)
 */
export function renderActionFieldsInto(container, type, idPrefix) {
  stopKeySequenceRecording(); // any full rebuild invalidates whatever was recording
  if (!container) return;
  container.innerHTML = "";
  if (!type) return;
  const spec = getSpec(type);
  if (!spec) return;

  if (spec.fields && spec.fields.length > 0) {
    for (const f of spec.fields) {
      const wrap = document.createElement("div");
      wrap.className = "field-row";

      if (f.input === "key_sequence") {
        const lab = document.createElement("label");
        lab.className = "field-label";
        lab.textContent = fieldLabelText(f);
        wrap.appendChild(lab);
        renderKeySequenceField(wrap, f, idPrefix);
        container.appendChild(wrap);
        continue;
      }

      if (f.input === "asset") {
        renderAssetField(container, wrap, f, idPrefix);
        continue;
      }

      const lab = document.createElement("label");
      lab.className = "field-label";
      lab.textContent = fieldLabelText(f);

      let input;
      if (f.input === "select") {
        input = document.createElement("select");
        input.dataset.param = f.name;
        input.setAttribute("data-param", String(f.name));
        for (const opt of f.options || []) {
          const op = document.createElement("option");
          op.value = opt;
          op.textContent = (f.option_labels && f.option_labels[String(opt)]) || opt;
          input.appendChild(op);
        }
        if (f.default != null) input.value = String(f.default);
      } else if (f.input === "json") {
        input = document.createElement("textarea");
        input.dataset.param = f.name;
        input.setAttribute("data-param", String(f.name));
        input.rows = 3;
        input.spellcheck = false;
        if (f.placeholder) input.placeholder = f.placeholder;
      } else if (f.input === "number") {
        input = document.createElement("input");
        input.type = "number";
        input.dataset.param = f.name;
        input.setAttribute("data-param", String(f.name));
        if (f.placeholder) input.placeholder = f.placeholder;
      } else {
        input = document.createElement("input");
        input.type = "text";
        input.dataset.param = f.name;
        input.setAttribute("data-param", String(f.name));
        if (f.placeholder) input.placeholder = f.placeholder;
      }
      lab.appendChild(input);
      wrap.appendChild(lab);
      appendFieldHelp(wrap, f);
      container.appendChild(wrap);
    }
    return;
  }

  if (spec.params_json) {
    const hint = document.createElement("p");
    hint.className = "hint";
    hint.textContent = t("inspector.field.params_json", { example: '{"scene": "Main"}' });
    container.appendChild(hint);
    const ta = document.createElement("textarea");
    ta.className = "action-params-json";
    if (idPrefix === "ap") {
      ta.id = "actionParamsJson";
    }
    ta.setAttribute("aria-label", t("inspector.field.params_label"));
    ta.rows = 8;
    ta.spellcheck = false;
    container.appendChild(ta);
  }
}

export function fillActionFieldsInContainer(container, action, type) {
  if (!container || !action || !type) return;
  const spec = getSpec(type);
  if (!spec) return;
  const rest = { ...action };
  delete rest.type;

  if (spec.fields && spec.fields.length > 0) {
    for (const f of spec.fields) {
      const el = actionFieldEl(container, f);
      if (!el) continue;
      if (f.input === "key_sequence") {
        const arr = Array.isArray(action[f.name]) ? action[f.name] : [];
        el.value = JSON.stringify(arr);
        const chipsEl = el.closest(".key-sequence-field")?.querySelector(".key-sequence-chips");
        renderKeySequenceChips(chipsEl, el);
        continue;
      }
      const v = action[f.name];
      if (v === undefined || v === null) {
        if (f.default != null) el.value = String(f.default);
        else el.value = "";
        continue;
      }
      if (f.input === "json") {
        el.value = typeof v === "string" ? v : JSON.stringify(v, null, 2);
      } else {
        el.value = String(v);
      }
    }
  } else if (spec.params_json) {
    const ta = container.querySelector(".action-params-json");
    if (ta) ta.value = Object.keys(rest).length ? JSON.stringify(rest, null, 2) : "";
  }
}

/** When Advanced JSON overrides the form, still copy non-empty asset path fields from the form (Browse… only updates inputs). */
export function mergeAssetFieldValuesFromForm(container, type, action) {
  if (!action || typeof action !== "object" || Array.isArray(action)) return action;
  const spec = getSpec(type);
  if (!spec || !spec.fields || !container) return action;
  for (const f of spec.fields) {
    if (f.input !== "asset") continue;
    const el = actionFieldEl(container, f);
    if (!el) continue;
    const raw = String(el.value).trim();
    if (!raw) continue;
    action[f.name] = raw;
  }
  return action;
}

export function buildActionFromFormIn(container, type) {
  if (!type) return null;
  const spec = getSpec(type);
  const out = { type };
  if (!spec) return out;

  if (spec.fields && spec.fields.length > 0) {
    for (const f of spec.fields) {
      const el = actionFieldEl(container, f);
      if (!el) continue;
      if (f.input === "key_sequence") {
        const steps = keySequenceStepsFromHidden(el);
        if (steps.length > 0) out[f.name] = steps;
        continue;
      }
      const raw = String(el.value).trim();
      if (!raw) {
        continue;
      }
      if (f.input === "json") {
        try {
          out[f.name] = JSON.parse(raw);
        } catch {
          throw new Error(t("inspector.error.invalid_json", { field: f.label || f.name }));
        }
      } else if (f.input === "number") {
        out[f.name] = Number(raw);
      } else {
        out[f.name] = raw;
      }
    }
    return out;
  }

  if (spec.params_json) {
    const ta = container.querySelector(".action-params-json");
    const raw = ta && ta.value.trim();
    if (raw) {
      let extra;
      try {
        extra = JSON.parse(raw);
      } catch {
        throw new Error(t("inspector.error.params_json"));
      }
      if (typeof extra !== "object" || extra === null || Array.isArray(extra)) {
        throw new Error(t("inspector.error.params_object"));
      }
      Object.assign(out, extra);
    }
    return out;
  }

  return out;
}
