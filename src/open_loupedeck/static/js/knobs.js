/*
 * knobs.js — Encoder (knob) editor: per-knob dial pages with rotate-left/right actions, the
 * all-encoders JSON editor, and the knob test buttons.
 */

import {
  buildActionFromFormIn,
  fillActionFieldsInContainer,
  renderActionFieldsInto,
} from "./action-fields.js";
import { postSimulatePress, refreshSkin } from "./api.js";
import { enhanceActionTypeSelect, knobCompatibleActionList, populateKnobActionSelect } from "./catalog.js";
import { renderDeck } from "./deck.js";
import { showKeyEditorPanel, syncCopyPasteButtons, syncTestPressButton } from "./inspector/panel.js";
import { stopSidebarAnimPreview } from "./inspector/preview.js";
import { knobPageLabelFromConfig } from "./model.js";
import { cancelPendingAutosave, runAutosave } from "./save.js";
import { state } from "./state.js";
import { $ } from "./util.js";

/** Unique id prefix for knob rotate action field rows (asset browse, etc.). */
let knobRotateFieldSeq = 0;

function parseRotateValueForUi(val) {
  if (val == null || val === "") return { mode: "empty" };
  if (Array.isArray(val)) {
    if (val.length === 0) return { mode: "empty" };
    if (
      val.length === 1 &&
      val[0] &&
      typeof val[0] === "object" &&
      !Array.isArray(val[0]) &&
      val[0].type
    ) {
      return { mode: "form", action: val[0] };
    }
    try {
      return { mode: "json", text: JSON.stringify(val, null, 2) };
    } catch {
      return { mode: "empty" };
    }
  }
  if (typeof val === "object" && val !== null && val.type) {
    return { mode: "form", action: val };
  }
  try {
    return { mode: "json", text: JSON.stringify(val, null, 2) };
  } catch {
    return { mode: "empty" };
  }
}

function appendKnobRotateUI(fs, side, rotateVal) {
  const parsed = parseRotateValueForUi(rotateVal);
  const wrap = document.createElement("div");
  wrap.className = `knob-rot-side knob-rot-${side}`;

  const lab = document.createElement("label");
  lab.className = "row";
  lab.textContent = side === "left" ? "Rotate left" : "Rotate right";
  wrap.appendChild(lab);

  const sel = document.createElement("select");
  sel.className = `full-width knob-rot-type-${side}`;
  const curType =
    parsed.mode === "form" && parsed.action && parsed.action.type ? String(parsed.action.type) : "";
  populateKnobActionSelect(sel, curType);

  const fields = document.createElement("div");
  fields.className = `knob-rot-fields-${side} knob-rot-fields`;

  const adv = document.createElement("details");
  adv.className = "knob-rot-json-details";
  const sum = document.createElement("summary");
  sum.textContent = "Advanced: JSON (arrays or multiple actions)";
  const taAdv = document.createElement("textarea");
  taAdv.className = `mono full-width knob-rot-json-${side}`;
  taAdv.rows = 4;
  taAdv.spellcheck = false;
  adv.appendChild(sum);
  adv.appendChild(taAdv);

  if (parsed.mode === "json") {
    taAdv.value = parsed.text;
    adv.open = true;
  } else if (parsed.mode === "form" && parsed.action) {
    const act = parsed.action;
    sel.value = act.type || "";
    if (sel._refreshActionSelectTrigger) sel._refreshActionSelectTrigger();
    const prefix = `kr${++knobRotateFieldSeq}`;
    renderActionFieldsInto(fields, sel.value, prefix);
    fillActionFieldsInContainer(fields, act, sel.value);
  }

  sel.addEventListener("change", () => {
    const prefix = `kr${++knobRotateFieldSeq}`;
    renderActionFieldsInto(fields, sel.value, prefix);
    taAdv.value = "";
    adv.open = false;
  });

  wrap.appendChild(sel);
  // Enhance once the select is in the DOM (the picker wraps it in place).
  enhanceActionTypeSelect(sel, knobCompatibleActionList());
  wrap.appendChild(fields);
  wrap.appendChild(adv);
  fs.appendChild(wrap);
}

function collectRotateSide(fs, side) {
  const label = side === "left" ? "Rotate left" : "Rotate right";
  const ta = fs.querySelector(`.knob-rot-json-${side}`);
  if (ta && ta.value.trim()) {
    try {
      return JSON.parse(ta.value.trim());
    } catch (e) {
      throw new Error(`${label} (JSON): ${e.message || e}`);
    }
  }
  const sel = fs.querySelector(`.knob-rot-type-${side}`);
  const fields = fs.querySelector(`.knob-rot-fields-${side}`);
  const type = sel && sel.value;
  if (!type) return undefined;
  try {
    return buildActionFromFormIn(fields, type);
  } catch (e) {
    throw new Error(`${label}: ${e.message || e}`);
  }
}

function renumberKnobPageLegends() {
  const mount = $("#knobEncoderPagesMount");
  if (!mount) return;
  mount.querySelectorAll(".knob-page-fieldset").forEach((fs, i) => {
    const n = fs.querySelector(".knob-page-num");
    if (n) n.textContent = String(i + 1);
  });
}

function addKnobEncoderPageRow(page) {
  const mount = $("#knobEncoderPagesMount");
  if (!mount) return;
  const p = page && typeof page === "object" ? page : {};
  const leftVal = p.rotate_left ?? p.left;
  const rightVal = p.rotate_right ?? p.right;

  const fs = document.createElement("fieldset");
  fs.className = "knob-page-fieldset";
  const leg = document.createElement("legend");
  leg.append("Page ");
  const numSpan = document.createElement("span");
  numSpan.className = "knob-page-num";
  leg.appendChild(numSpan);
  fs.appendChild(leg);

  const labN = document.createElement("label");
  labN.className = "row";
  labN.textContent = "Page name (shown on touch when you push to select this page)";
  fs.appendChild(labN);
  const nameIn = document.createElement("input");
  nameIn.type = "text";
  nameIn.className = "full-width knob-page-name";
  nameIn.value = knobPageLabelFromConfig(p);
  fs.appendChild(nameIn);

  appendKnobRotateUI(fs, "left", leftVal);
  appendKnobRotateUI(fs, "right", rightVal);

  const rm = document.createElement("button");
  rm.type = "button";
  rm.className = "btn-remove-knob-page";
  rm.textContent = "Remove this page";
  fs.appendChild(rm);

  mount.appendChild(fs);
  renumberKnobPageLegends();
}

function renderKnobEncoderForm(knobId) {
  const mount = $("#knobEncoderPagesMount");
  if (!mount) return;
  mount.innerHTML = "";
  const spec = state.cfg.knob_pages && state.cfg.knob_pages[knobId];
  const pages = spec && Array.isArray(spec.pages) ? spec.pages.filter((x) => x && typeof x === "object") : [];
  if (pages.length === 0) {
    addKnobEncoderPageRow({});
  } else {
    for (const pg of pages) {
      addKnobEncoderPageRow(pg);
    }
  }
}

function collectKnobEncoderPagesFromDom() {
  const mount = $("#knobEncoderPagesMount");
  if (!mount) return [];
  const out = [];
  for (const fs of mount.querySelectorAll(".knob-page-fieldset")) {
    const name = (fs.querySelector(".knob-page-name") && fs.querySelector(".knob-page-name").value.trim()) || "";
    const rotate_left = collectRotateSide(fs, "left");
    const rotate_right = collectRotateSide(fs, "right");
    if (!name && rotate_left === undefined && rotate_right === undefined) continue;
    const o = {};
    if (name) o.name = name;
    if (rotate_left !== undefined) o.rotate_left = rotate_left;
    if (rotate_right !== undefined) o.rotate_right = rotate_right;
    out.push(o);
  }
  return out;
}

export function openKnobEncoderEditor(kid) {
  stopSidebarAnimPreview();
  state.selectedKnobEncoder = kid;
  state.selectedControl = null;
  const k = $("#keyEditorBlock");
  const kn = $("#knobEncoderEditorBlock");
  if (k) k.hidden = true;
  if (kn) kn.hidden = false;
  const title = $("#knobEncoderTitle");
  if (title) title.textContent = `Encoder: ${kid}`;
  const err = $("#knobEncoderError");
  if (err) err.textContent = "";
  const dur = $("#knobFeedbackDurationSec");
  if (dur) {
    const d = state.cfg.knob_page_feedback && state.cfg.knob_page_feedback.duration_sec;
    dur.value =
      d != null && !Number.isNaN(Number(d))
        ? String(Math.max(0.3, Math.min(2, Number(d))))
        : "2";
  }
  renderKnobEncoderForm(kid);
  syncKnobPagesEditor();
  syncTestPressButton();
}

export function closeKnobEncoderEditor() {
  state.selectedKnobEncoder = null;
  showKeyEditorPanel();
  const sl = $("#selLabel");
  if (sl) sl.textContent = "Select a control";
  syncTestPressButton();
  syncCopyPasteButtons();
}

export function syncKnobPagesEditor() {
  const ta = $("#knobPagesJson");
  if (!ta) return;
  try {
    const kp = state.cfg.knob_pages && typeof state.cfg.knob_pages === "object" ? state.cfg.knob_pages : {};
    ta.value = JSON.stringify(kp, null, 2);
  } catch {
    ta.value = "{}";
  }
}

async function applyKnobPagesJson() {
  const ta = $("#knobPagesJson");
  const err = $("#knobPagesError");
  if (!ta) return;
  if (err) err.textContent = "";
  try {
    const raw = ta.value.trim() || "{}";
    const o = JSON.parse(raw);
    if (typeof o !== "object" || o === null || Array.isArray(o)) {
      throw new Error("knob_pages must be a JSON object");
    }
    state.cfg.knob_pages = o;
    cancelPendingAutosave();
    const ok = await runAutosave();
    if (!ok) return;
    await refreshSkin();
    if (state.selectedKnobEncoder) {
      renderKnobEncoderForm(state.selectedKnobEncoder);
    }
    renderDeck();
  } catch (e) {
    if (err) err.textContent = String(e.message || e);
  }
}

async function saveKnobEncoderPagesFromForm() {
  const errEl = $("#knobEncoderError");
  if (errEl) errEl.textContent = "";
  const kid = state.selectedKnobEncoder;
  if (!kid) return;
  let pages;
  try {
    pages = collectKnobEncoderPagesFromDom();
  } catch (e) {
    if (errEl) errEl.textContent = String(e.message || e);
    return;
  }
  if (!state.cfg.knob_pages || typeof state.cfg.knob_pages !== "object") state.cfg.knob_pages = {};
  state.cfg.knob_pages[kid] = { pages };
  const durIn = $("#knobFeedbackDurationSec");
  if (durIn) {
    const v = parseFloat(durIn.value);
    if (!Number.isNaN(v)) {
      const clamped = Math.max(0.3, Math.min(2, v));
      state.cfg.knob_page_feedback = { ...(state.cfg.knob_page_feedback && typeof state.cfg.knob_page_feedback === "object" ? state.cfg.knob_page_feedback : {}), duration_sec: clamped };
    }
  }
  syncKnobPagesEditor();
  cancelPendingAutosave();
  const ok = await runAutosave();
  if (!ok) return;
  await refreshSkin();
  renderDeck();
}

/** Encoder editor: simulate push / turn left / turn right. */
export function wireKnobTestButtons() {
  const btnTestKnobPush = $("#btnTestKnobPush");
  const btnTestKnobLeft = $("#btnTestKnobLeft");
  const btnTestKnobRight = $("#btnTestKnobRight");
  if (btnTestKnobPush) {
    btnTestKnobPush.addEventListener("click", () => {
      if (!state.selectedKnobEncoder) return;
      const err = $("#knobEncoderError");
      if (err) err.textContent = "";
      void (async () => {
        try {
          await postSimulatePress(state.selectedKnobEncoder, null);
        } catch (e) {
          if (err) err.textContent = String(e);
        }
      })();
    });
  }
  if (btnTestKnobLeft) {
    btnTestKnobLeft.addEventListener("click", () => {
      if (!state.selectedKnobEncoder) return;
      const err = $("#knobEncoderError");
      if (err) err.textContent = "";
      void (async () => {
        try {
          await postSimulatePress(state.selectedKnobEncoder, "left");
        } catch (e) {
          if (err) err.textContent = String(e);
        }
      })();
    });
  }
  if (btnTestKnobRight) {
    btnTestKnobRight.addEventListener("click", () => {
      if (!state.selectedKnobEncoder) return;
      const err = $("#knobEncoderError");
      if (err) err.textContent = "";
      void (async () => {
        try {
          await postSimulatePress(state.selectedKnobEncoder, "right");
        } catch (e) {
          if (err) err.textContent = String(e);
        }
      })();
    });
  }
}

/** Encoder editor: save / add page / close / remove page / all-encoders JSON. */
export function wireKnobEditorButtons() {
  const btnKnobPages = $("#btnApplyKnobPages");
  if (btnKnobPages) btnKnobPages.addEventListener("click", () => void applyKnobPagesJson());

  const btnSaveKnobEnc = $("#btnSaveKnobEncoderPages");
  if (btnSaveKnobEnc) btnSaveKnobEnc.addEventListener("click", () => void saveKnobEncoderPagesFromForm());
  const btnAddKnobPg = $("#btnAddKnobEncoderPage");
  if (btnAddKnobPg) btnAddKnobPg.addEventListener("click", () => addKnobEncoderPageRow({}));
  const btnCloseKnob = $("#btnCloseKnobEncoderEditor");
  if (btnCloseKnob) btnCloseKnob.addEventListener("click", closeKnobEncoderEditor);

  const knobPgMount = $("#knobEncoderPagesMount");
  if (knobPgMount) {
    knobPgMount.addEventListener("click", (ev) => {
      const t = ev.target;
      if (t && t.classList && t.classList.contains("btn-remove-knob-page")) {
        const fs = t.closest(".knob-page-fieldset");
        if (fs) {
          fs.remove();
          renumberKnobPageLegends();
        }
      }
    });
  }
}
