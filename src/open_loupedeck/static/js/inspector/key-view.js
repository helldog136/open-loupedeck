/*
 * inspector/key-view.js — The inspector of a control with a press (display key, button, pedal), built
 * from its capabilities: header (name, scope, copy / paste / clear), the scope bar (this page / every
 * page), step "What should it do?" (action picker + the action's parameter fields), "Appearance" when
 * the control shows an image, "Light" when it has an LED, then "Advanced". Changes apply live through
 * edit.js, in the scope being edited; `refresh()` re-reads the stored entry (after an edit, Undo, a
 * language change) without rebuilding fields the user is typing in.
 */

import { buildActionFromFormIn, fillActionFieldsInContainer, renderActionFieldsInto } from "../action-fields.js";
import { actionShortName, getSpec } from "../catalog.js";
import { entryActions, getEntry, gotoPageIndex, pageName } from "../model.js";
import { createActionPicker } from "../pickers/action-picker.js";
import { state } from "../state.js";
import { createAdvancedStep } from "./advanced.js";
import { createAppearanceStep } from "./appearance.js";
import { canPaste, clearControl, copyControl, pasteControl } from "./clipboard.js";
import { capabilities, controlName } from "./controls.js";
import { el, hasFocus, nextId, svgIcon } from "./dom.js";
import { editEntry } from "./edit.js";
import { entryAction, setEntryAction } from "./entry.js";
import { createLightStep } from "./light.js";
import { createScopeBar, inheritsGlobal } from "./scope.js";

/** A fresh action of `type`: catalog defaults, plus same-named parameters carried over from `prev`. */
export function newAction(type, prev) {
  const spec = getSpec(type);
  const out = { type };
  for (const f of (spec && spec.fields) || []) {
    if (prev && prev[f.name] != null && prev[f.name] !== "") out[f.name] = prev[f.name];
    else if (f.default != null) out[f.name] = f.input === "number" ? Number(f.default) : f.default;
  }
  return out;
}

/** Short text of a key / button binding (scope bar): the page it opens, its action, or its label. */
export function describeEntry(e) {
  const page = gotoPageIndex(e);
  if (page != null) return t("inspector.describe.goto_page", { page: pageName(page) });
  const acts = entryActions(e);
  const text = String((e && (e.text || e.label)) || "").trim();
  if (acts.length) return text ? `${actionShortName(acts[0].type)} (${text})` : actionShortName(acts[0].type);
  return text;
}

/** Header shared by every control view: name, scope line and the copy / paste / clear tools. */
export function createHeader(cid, onChanged) {
  const live = el("span", { class: "sr-only", role: "status" });
  const tool = (idAttr, icon, key, onClick) => {
    const b = el("button", { type: "button", class: "btn btn-ghost insp-tool", id: idAttr, "aria-label": t(key), title: t(key) }, svgIcon(icon));
    b.addEventListener("click", () => {
      if (onClick()) {
        live.textContent = t(`${key}.done`, { name: controlName(cid) });
        onChanged();
      }
    });
    return b;
  };
  const bCopy = tool("btnCopyControl", "copy", "inspector.copy", () => copyControl(cid));
  const bPaste = tool("btnPasteControl", "paste", "inspector.paste", () => pasteControl(cid));
  const bClear = tool("btnClearControl", "trash", "inspector.clear", () => clearControl(cid));
  const root = el(
    "header",
    { class: "insp-head" },
    el("div", { class: "insp-head-text" }, el("h2", { class: "insp-title", text: controlName(cid) })),
    el("div", { class: "insp-tools", role: "toolbar", "aria-label": t("inspector.tools") }, bCopy, bPaste, bClear),
    live,
  );
  return {
    root,
    sync() {
      const has = !!getEntry(cid);
      bCopy.disabled = !has;
      bClear.disabled = !has;
      bPaste.disabled = !canPaste(cid);
    },
  };
}

/** Per-control UI state kept while the same control stays open (and across Undo / language changes). */
const uiByControl = new Map();
/** Advanced stays open from one control to the next once the user opened it. */
let advOpen = false;

/** Actions that make sense on a control without a screen (live displays only draw on keys). */
function catalogFor(caps) {
  const all = state.actionCatalog || [];
  return caps.image ? all : all.filter((a) => a && a.type && !String(a.type).startsWith("display."));
}

/** `onScope()` is called when the edited scope changes (the inspector rebuilds the view). */
export function createKeyView(host, cid, { onScope = () => {} } = {}) {
  if (!uiByControl.has(cid)) uiByControl.set(cid, { customOpen: false, pop: null });
  const ui = uiByControl.get(cid);
  ui.advOpen = advOpen;
  const id = nextId("insp-key");
  const caps = capabilities(cid);

  const view = el("div", { class: "insp-view", "data-control": cid, "data-kind": caps.kind || "" });
  // Edited on this page while only the binding for every page exists: the bar asks what to do.
  const inheriting = inheritsGlobal(cid);
  const header = createHeader(cid, () => (inheriting ? onScope() : refresh(true)));
  const scopeBar = createScopeBar(cid, { describe: describeEntry, onScope });
  view.append(header.root, scopeBar.root);
  host.append(view);

  if (inheriting) {
    header.sync();
    return {
      cid,
      refresh() {
        header.sync();
        scopeBar.sync();
        if (!inheritsGlobal(cid)) onScope();
      },
      setCatalog() {},
      focus() {},
      destroy() {
        view.remove();
      },
    };
  }

  let stepNo = 0;
  const ctx = {
    cid,
    kind: caps.kind,
    caps,
    ui,
    entry: () => getEntry(cid) || {},
    action: () => entryAction(getEntry(cid)),
    spec: () => {
      const a = entryAction(getEntry(cid));
      return a ? getSpec(a.type) : null;
    },
    lang: () => (window.i18n && window.i18n.lang) || undefined,
    edit(mutate, opts) {
      editEntry(cid, mutate, opts);
      refresh();
    },
    onActionJson: () => renderParams(true),
    playPress: () => look && look.playPress(),
  };

  // --- step: action ----------------------------------------------------------------------------
  const step1 = el("section", { class: "insp-step insp-step-action", "aria-labelledby": `${id}-h1` });
  step1.append(
    el(
      "h3",
      { id: `${id}-h1` },
      el("b", { "aria-hidden": "true", text: String(++stepNo) }),
      el("span", { text: t("inspector.step1.title", { name: controlName(cid) }) }),
    ),
  );
  const pickerHost = el("div", { class: "insp-picker" });
  const help = el("p", { class: "hint insp-help", hidden: true });
  const params = el("div", { class: "insp-params action-fields" });
  const paramsErr = el("p", { class: "msg-error", role: "alert", hidden: true });
  step1.append(pickerHost, help, params, paramsErr);
  let pickerValue = (ctx.action() && ctx.action().type) || "";
  const picker = createActionPicker(pickerHost, {
    catalog: catalogFor(caps),
    value: pickerValue,
    lang: ctx.lang(),
    onChange: (type) => {
      pickerValue = type;
      const prev = ctx.action();
      if (prev && prev.type === type) return;
      editEntry(cid, (e) => setEntryAction(e, newAction(type, prev)));
      renderParams(true);
      refresh();
    },
  });

  let paramsType = null;
  /** (Re)build the parameter fields for the stored action; `force` rebuilds even for the same type. */
  function renderParams(force = false) {
    const a = ctx.action();
    const type = (a && a.type) || "";
    if (!force && type === paramsType) {
      if (a && !hasFocus(params)) fillActionFieldsInContainer(params, a, type);
      return;
    }
    paramsType = type;
    renderActionFieldsInto(params, type, "ap");
    if (a) fillActionFieldsInContainer(params, a, type);
    const spec = getSpec(type);
    help.textContent = (spec && spec.help) || "";
    help.hidden = !help.textContent;
    paramsErr.hidden = true;
  }

  function commitParams() {
    const a = ctx.action();
    if (!a || !a.type) return;
    const spec = getSpec(a.type);
    let built;
    try {
      built = buildActionFromFormIn(params, a.type);
    } catch (err) {
      paramsErr.textContent = err.message || String(err);
      paramsErr.hidden = false;
      return;
    }
    paramsErr.hidden = true;
    // Keep parameters the form does not show (offline_fallback, keys set through the JSON view).
    const shown = new Set(((spec && spec.fields) || []).map((f) => f.name));
    const extras = {};
    if (spec && spec.fields && spec.fields.length) {
      for (const [k, v] of Object.entries(a)) if (k !== "type" && !shown.has(k)) extras[k] = v;
    }
    const action = { type: a.type, ...extras, ...built };
    editEntry(cid, (e) => setEntryAction(e, action), { typing: true });
    refresh();
  }
  const isParamInput = (n) => n && n.matches && n.matches("input, select, textarea") && n.type !== "file";
  params.addEventListener("input", (ev) => isParamInput(ev.target) && commitParams());
  params.addEventListener("change", (ev) => isParamInput(ev.target) && ev.target.tagName === "SELECT" && commitParams());
  view.append(step1);

  // --- optional steps: appearance (image output), light (LED output), advanced -------------------
  let look = null;
  let light = null;
  if (caps.image) {
    ++stepNo;
    look = createAppearanceStep(ctx);
    view.append(look.root);
  } else if (!caps.led) {
    view.append(el("p", { class: "hint insp-note", text: t("inspector.button.no_screen") }));
  }
  if (caps.led) {
    light = createLightStep(ctx, ++stepNo);
    view.append(light.root);
  }
  ctx.advNumber = ++stepNo;
  const adv = createAdvancedStep(ctx);
  adv.root.addEventListener("toggle", () => (advOpen = adv.root.open));
  view.append(adv.root);

  function refresh(rebuildParams = false) {
    if (inheritsGlobal(cid)) {
      onScope(); // the binding this page edited went away (Undo): show the choice again
      return;
    }
    const a = ctx.action();
    const type = (a && a.type) || "";
    if (type !== pickerValue) {
      pickerValue = type;
      picker.setValue(type);
    }
    renderParams(rebuildParams);
    header.sync();
    scopeBar.sync();
    if (look) look.sync();
    if (light) light.sync();
    adv.sync();
  }

  refresh(true);

  return {
    cid,
    refresh,
    setCatalog() {
      picker.setCatalog(catalogFor(caps));
      renderParams(true);
    },
    focus() {
      picker.focus();
    },
    destroy() {
      picker.destroy();
      if (look) look.destroy();
      if (light) light.destroy();
      adv.destroy();
      view.remove();
    },
  };
}

/** A control the editor cannot bind yet (a slider or touch strip without a press). */
export function createUnsupportedView(host, cid) {
  const kind = capabilities(cid).kind || "";
  const view = el(
    "div",
    { class: "insp-view", "data-control": cid, "data-kind": kind },
    el(
      "header",
      { class: "insp-head" },
      el("div", { class: "insp-head-text" }, el("h2", { class: "insp-title", text: controlName(cid) })),
    ),
    el(
      "section",
      { class: "insp-step insp-unsupported" },
      el("strong", { text: t("inspector.unsupported.title") }),
      el("p", { class: "hint", text: t(kind === "strip" ? "inspector.unsupported.touch" : "inspector.unsupported.value") }),
    ),
  );
  host.append(view);
  return { cid, refresh() {}, setCatalog() {}, focus() {}, destroy: () => view.remove() };
}
