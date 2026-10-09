/*
 * inspector/knob-view.js — The knob inspector. A knob has no screen and no pages of its own: what it
 * does depends on the deck page being shown, stored in `pages[i].knobs.<knobId>`:
 *   rotate: { duo, params }            one linked setting (left / right = - / +), a "duo"
 *         | { left, right }            Advanced: two free actions
 *   press:  action                     independent of the rotation
 *   feedback_sec: 0..2                 optional per-knob display time of the feedback
 * The view shows the role of this knob on every page (chips), the three zones under the knob (left /
 * press / right; left and right are one choice while linked), the picker for the active zone, the
 * display time and test buttons, and Advanced (split left / right, JSON). Every change goes through
 * `editRole` (Undo snapshot, autosave, deck captions). It also provides the knob captions of the deck
 * (the role name on the page shown). Duos come from GET /api/knob_duos (translated server side).
 */

import { buildActionFromFormIn, fillActionFieldsInContainer, renderActionFieldsInto } from "../action-fields.js";
import { postSimulatePress } from "../api.js";
import { getSpec } from "../catalog.js";
import { renderDeck, setKnobCaptionProvider } from "../deck.js";
import { createActionPicker } from "../pickers/action-picker.js";
import { flushAutosave, scheduleAutosave } from "../save.js";
import { emit, state } from "../state.js";
import { snapshotBeforeAction, snapshotBeforeEditOnce } from "../undo.js";
import { $, deepCloneJson } from "../util.js";
import { el, nextId } from "./dom.js";
import { newAction } from "./key-view.js";

/* ---- duo catalogue --------------------------------------------------------------------------- */

let duos = [];
let active = null; // the open view's { refresh }, to redraw it when the catalogue arrives

const duoById = (id) => duos.find((d) => d.id === id) || null;
const lang = () => (window.i18n && window.i18n.lang) || "";

/** (Re)load the duo catalogue in the UI language, then redraw the deck captions and the open view. */
async function loadDuos() {
  try {
    const l = lang();
    const r = await fetch(`/api/knob_duos${l ? `?lang=${encodeURIComponent(l)}` : ""}`);
    if (r.ok) duos = (await r.json()).duos || [];
  } catch {
    /* keep the previous catalogue */
  }
  if (state.cfg && state.cfg.pages) renderDeck();
  if (active) active.refresh();
}

const DROP = Symbol("drop");

/** Params with the duo's defaults applied and numbers clamped (mirrors knob_duos.resolved_params). */
function resolveParams(duo, stored) {
  const src = stored && typeof stored === "object" ? stored : {};
  const out = {};
  for (const p of duo.params || []) {
    let v = src[p.name];
    if (v == null || (typeof v === "string" && !v.trim())) v = p.default;
    if (v == null) continue;
    if (p.kind === "number") {
      let n = Number(v);
      if (!Number.isFinite(n)) n = Number(p.default);
      if (!Number.isFinite(n)) continue;
      if (p.min != null) n = Math.max(p.min, n);
      if (p.max != null) n = Math.min(p.max, n);
      out[p.name] = n;
    } else out[p.name] = String(v).trim();
  }
  return out;
}

function fillTemplate(tpl, p) {
  if (Array.isArray(tpl)) return tpl.map((x) => fillTemplate(x, p)).filter((x) => x !== DROP);
  if (tpl && typeof tpl === "object") {
    const keys = Object.keys(tpl);
    if (keys.length === 2 && "param" in tpl && "sign" in tpl) {
      const v = p[tpl.param];
      if (v == null) return DROP;
      return tpl.sign === 1 ? v : Number(v) * tpl.sign;
    }
    const out = {};
    for (const k of keys) {
      const f = fillTemplate(tpl[k], p);
      if (f !== DROP) out[k] = f;
    }
    return out;
  }
  return tpl;
}

/** The concrete actions of one side of a duo (what the agent runs). */
function expandDuo(duo, stored, side) {
  return fillTemplate(duo[side], resolveParams(duo, stored));
}

/* ---- stored role ----------------------------------------------------------------------------- */

const curPage = () => (state.cfg && state.cfg.pages && state.cfg.pages[state.pageIndex]) || null;
const roleOf = (page, id) => (page && page.knobs && page.knobs[id]) || null;
const isEmpty = (v) => v == null || (Array.isArray(v) && !v.length) || (typeof v === "object" && !Array.isArray(v) && !Object.keys(v).length);

/** One action of a stored value (an action, or a list of exactly one); null when empty. */
function single(v) {
  if (isEmpty(v)) return null;
  if (Array.isArray(v)) return v.length === 1 && v[0] && v[0].type ? v[0] : null;
  return v.type ? v : null;
}
const isSplit = (role) => !!(role && role.rotate && !role.rotate.duo && (role.rotate.left || role.rotate.right));

function pruneRole(r) {
  for (const k of ["rotate", "press"]) if (isEmpty(r[k])) delete r[k];
  if (r.rotate && !r.rotate.duo) {
    for (const s of ["left", "right"]) if (isEmpty(r.rotate[s])) delete r.rotate[s];
    if (!r.rotate.left && !r.rotate.right) delete r.rotate;
  }
  if (r.feedback_sec != null && !Number.isFinite(Number(r.feedback_sec))) delete r.feedback_sec;
  return Object.keys(r).length ? r : null;
}

function setRole(page, id, role) {
  if (role) {
    if (!page.knobs || typeof page.knobs !== "object") page.knobs = {};
    page.knobs[id] = role;
  } else if (page.knobs) {
    delete page.knobs[id];
    if (!Object.keys(page.knobs).length) delete page.knobs;
  }
}

/** Change this knob's role on the page shown: Undo snapshot, write, deck captions, autosave. */
function editRole(knobId, mutate, { typing = false } = {}) {
  const page = curPage();
  if (!page) return;
  if (typing) snapshotBeforeEditOnce();
  else snapshotBeforeAction();
  const cur = roleOf(page, knobId);
  const draft = cur ? deepCloneJson(cur) : {};
  mutate(draft);
  setRole(page, knobId, pruneRole(draft));
  renderDeck();
  scheduleAutosave();
}

/* ---- names and texts ------------------------------------------------------------------------- */

function actionName(a) {
  const spec = a && getSpec(a.type);
  const label = (spec && spec.label) || (a && a.type) || "";
  const parts = String(label).split(/\s[—-]\s/);
  return parts.length > 1 ? parts.slice(1).join(" - ") : label;
}

/** Short name of a role (the caption under the knob on the deck). */
function roleName(role) {
  if (!role) return "";
  const r = role.rotate;
  if (r && r.duo) {
    const d = duoById(r.duo);
    return d ? d.label : r.duo;
  }
  if (r && (r.left || r.right)) return t("inspector.knob.role.custom");
  if (role.press) return t("inspector.knob.role.press_only");
  return "";
}
const caption = (knobId) => roleName(roleOf(curPage(), knobId)) || t("inspector.knob.role.none");

/** What the deck flashes after a turn / a push: "Volume +5", "Next track", the action's name. */
function feedbackText(role, side) {
  if (!role) return "";
  if (side === "press") {
    const a = single(role.press);
    return a ? actionName(a) : role.press ? t("inspector.knob.role.custom") : "";
  }
  const r = role.rotate;
  if (!r) return "";
  if (r.duo) {
    const d = duoById(r.duo);
    if (!d) return r.duo;
    const p = resolveParams(d, r.params);
    if ((d.params || []).some((x) => x.required && p[x.name] == null)) return t("knob.feedback.needs_setup", { name: d.label });
    return t(d[`${side}_label_key`], p);
  }
  const a = single(r[side]);
  return a ? actionName(a) : r[side] ? t("inspector.knob.role.custom") : "";
}

const knobName = (id) => {
  const k = `inspector.knob.name.${id}`;
  const s = t(k);
  return s === k ? id : s;
};
const pageName = (i) => {
  const p = state.cfg.pages[i];
  return (p && p.name) || t("pages.default_name", { number: i + 1 });
};

/* ---- per-session UI memory ------------------------------------------------------------------- */

/** Which zone is open ("rot" while linked, "left" / "right" once split, "press"), and the split switch. */
const ui = { knobId: null, zone: "rot", split: false, advOpen: false };

/* ---- one action (press, split left / right): picker + parameter fields ----------------------- */

let editorSeq = 0;
const knobCatalog = () => (state.actionCatalog || []).filter((a) => a && a.type && !String(a.type).startsWith("display."));

/** `onSet(action | null, typing)` is called on every change; `value` is the stored action / list. */
function createActionEditor(host, { value, onSet }) {
  const a0 = single(value);
  let cur = a0;
  const multi = !a0 && !isEmpty(value);
  const prefix = `kna${++editorSeq}`;
  const pickerHost = el("div", { class: "insp-picker" });
  const help = el("p", { class: "hint", hidden: true });
  const params = el("div", { class: "insp-params action-fields" });
  const err = el("p", { class: "msg-error", role: "alert", hidden: true });
  const clear = el("button", { type: "button", class: "btn-link kn-clear", text: t("inspector.knob.action.clear"), hidden: !value });
  host.append(pickerHost, help, params, err, clear);
  if (multi) {
    host.prepend(el("p", { class: "hint", text: t("inspector.knob.action.multi") }));
  }

  function renderParams() {
    const type = (cur && cur.type) || "";
    renderActionFieldsInto(params, type, prefix);
    if (cur) fillActionFieldsInContainer(params, cur, type);
    const spec = type ? getSpec(type) : null;
    help.textContent = (spec && spec.help) || "";
    help.hidden = !help.textContent;
    err.hidden = true;
  }

  const picker = createActionPicker(pickerHost, {
    catalog: knobCatalog(),
    value: (cur && cur.type) || "",
    lang: lang() || undefined,
    onChange: (type) => {
      if (cur && cur.type === type) return;
      cur = newAction(type, cur);
      onSet(cur, false);
      clear.hidden = false;
      renderParams();
    },
  });

  function commit() {
    if (!cur) return;
    const spec = getSpec(cur.type);
    let built;
    try {
      built = buildActionFromFormIn(params, cur.type);
    } catch (e) {
      err.textContent = e.message || String(e);
      err.hidden = false;
      return;
    }
    err.hidden = true;
    const shown = new Set(((spec && spec.fields) || []).map((f) => f.name));
    const extras = {};
    if (spec && spec.fields && spec.fields.length) for (const [k, v] of Object.entries(cur)) if (k !== "type" && !shown.has(k)) extras[k] = v;
    cur = { type: cur.type, ...extras, ...built };
    onSet(cur, true);
  }
  const isInput = (n) => n && n.matches && n.matches("input, select, textarea") && n.type !== "file";
  params.addEventListener("input", (ev) => isInput(ev.target) && commit());
  params.addEventListener("change", (ev) => isInput(ev.target) && ev.target.tagName === "SELECT" && commit());
  clear.addEventListener("click", () => {
    cur = null;
    onSet(null, false);
    picker.setValue("");
    clear.hidden = true;
    renderParams();
  });
  renderParams();
  return { destroy: () => picker.destroy() };
}

/* ---- the view -------------------------------------------------------------------------------- */

let root = null; // the open view's element
let ctxClose = null;
let editors = [];
let restoreFocus = null;
let lightSync = () => {};

function numberOrNull(raw) {
  const s = String(raw).trim();
  if (s === "") return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : NaN;
}

function render(host, knobId) {
  for (const e of editors) e.destroy();
  editors = [];
  if (root) root.remove();
  const id = nextId("insp-knob");
  const page = curPage();
  const splitNow = () => ui.split || isSplit(roleOf(curPage(), knobId));
  const zoneOn = (z) => (splitNow() ? ui.zone === z : z === "press" ? ui.zone === "press" : ui.zone !== "press");

  root = el("div", { class: "insp-view kn-view", "data-knob": knobId });

  // header
  root.append(
    el(
      "header",
      { class: "insp-head" },
      el(
        "div",
        { class: "insp-head-text" },
        el("h2", { class: "insp-title", text: knobName(knobId) }),
        el("span", { class: "insp-scope", text: t("inspector.knob.scope", { page: page ? pageName(state.pageIndex) : "" }) }),
      ),
    ),
  );

  // step 1: role
  const step1 = el("section", { class: "insp-step", "aria-labelledby": `${id}-h1` });
  step1.append(el("h3", { id: `${id}-h1` }, el("b", { "aria-hidden": "true", text: "1" }), el("span", { text: t("inspector.knob.step1.title") })));
  const chips = el("div", { class: "chips kn-chips", role: "group", "aria-label": t("inspector.knob.pages") });
  step1.append(el("p", { class: "hint", text: t("inspector.knob.pages.hint") }), chips);
  const dialHost = el("div", { class: "kn-dial-wrap" });
  const panel = el("div", { class: "kn-panel" });
  const applyMsg = el("span", { class: "hint", role: "status" });
  const applyAll = el("button", { type: "button", class: "btn-link", text: t("inspector.knob.apply_all") });
  step1.append(dialHost, panel, el("p", { class: "kn-apply" }, applyAll, " ", applyMsg));
  root.append(step1);

  function renderChips() {
    chips.textContent = "";
    state.cfg.pages.forEach((p, i) => {
      const r = roleName(roleOf(p, knobId)) || t("inspector.knob.role.none");
      const b = el("button", { type: "button", "data-pg": String(i), "aria-pressed": String(i === state.pageIndex), title: t("inspector.knob.show_page") });
      b.append(el("span", { class: "kn-chip-name", text: `${i + 1} ${pageName(i)}` }), el("span", { class: "kn-chip-role", text: r }));
      b.addEventListener("click", () => {
        if (i === state.pageIndex) return;
        restoreFocus = `[data-pg="${i}"]`;
        const sel = $("#pageSelect");
        if (!sel) return;
        sel.value = String(i);
        sel.dispatchEvent(new Event("change"));
      });
      chips.append(b);
    });
  }

  function renderDial() {
    const r = roleOf(curPage(), knobId);
    const none = t("inspector.knob.role.none");
    const zone = (z, glyph, title, text) => {
      const b = el("button", { type: "button", class: `kn-zone kn-z-${z}`, "data-zone": z, "aria-pressed": String(zoneOn(z === "press" ? "press" : z)) });
      b.append(el("span", { class: "kn-glyph", "aria-hidden": "true", text: glyph }), el("span", { class: "kn-zt", text: title }), el("span", { class: "kn-za", text: text || none }));
      b.addEventListener("click", () => {
        ui.zone = z === "press" ? "press" : splitNow() ? z : "rot";
        restoreFocus = `[data-zone="${z}"]`;
        renderAll();
      });
      return b;
    };
    dialHost.textContent = "";
    dialHost.append(
      el("div", { class: "kn-knob" }, el("span", { class: "kn-notch", "aria-hidden": "true" }), el("span", { class: "kn-knob-role", text: roleName(r) || none })),
      el(
        "div",
        { class: "kn-zones" },
        zone("left", "↶", t("inspector.knob.zone.left"), feedbackText(r, "left")),
        zone("press", "●", t("inspector.knob.zone.press"), feedbackText(r, "press")),
        zone("right", "↷", t("inspector.knob.zone.right"), feedbackText(r, "right")),
      ),
      el("div", { class: `kn-link${splitNow() ? "" : " on"}`, text: splitNow() ? t("inspector.knob.split.note") : t("inspector.knob.linked") }),
    );
  }

  function renderPanel() {
    panel.textContent = "";
    const r = roleOf(curPage(), knobId);
    if (ui.zone === "press") return renderPressPanel(r);
    if (splitNow()) return renderSplitPanel(r);
    return renderDuoPanel(r);
  }

  function renderDuoPanel(r) {
    const sel = r && r.rotate && r.rotate.duo ? r.rotate : null;
    panel.append(el("div", { class: "kn-label", text: t("inspector.knob.rotation.title") }));
    const list = el("div", { class: "kn-duos", role: "group", "aria-label": t("inspector.knob.rotation.title") });
    const nothing = el("button", { type: "button", class: "kn-duo", "aria-pressed": String(!sel) }, el("span", { class: "kn-duo-name", text: t("inspector.knob.role.none") }));
    nothing.addEventListener("click", () => {
      editRole(knobId, (x) => delete x.rotate);
      restoreFocus = ".kn-duo";
      renderAll();
    });
    list.append(nothing);
    if (!duos.length) list.append(el("p", { class: "hint", text: t("inspector.knob.duos.loading") }));
    for (const d of duos) {
      const on = !!sel && sel.duo === d.id;
      const p = on ? resolveParams(d, sel.params) : null;
      const left = on ? t(d.left_label_key, p) : d.left_label;
      const right = on ? t(d.right_label_key, p) : d.right_label;
      const b = el("button", { type: "button", class: "kn-duo", "data-duo": d.id, "aria-pressed": String(on) });
      b.append(
        el("span", { class: "kn-duo-name", text: d.label }),
        el("small", { text: t("inspector.knob.duo.sides", { left, right }) }),
      );
      b.addEventListener("click", () => {
        if (on) return;
        editRole(knobId, (x) => {
          const prev = x.rotate && x.rotate.duo ? x.rotate.params || {} : {};
          const params = {};
          for (const q of d.params || []) {
            if (prev[q.name] != null && prev[q.name] !== "") params[q.name] = prev[q.name];
            else if (q.default != null) params[q.name] = q.default;
          }
          x.rotate = { duo: d.id, params };
        });
        restoreFocus = `[data-duo="${d.id}"]`;
        renderAll();
      });
      list.append(b);
    }
    panel.append(list);
    if (!sel) return;
    const d = duoById(sel.duo);
    if (!d || !(d.params || []).length) return;
    const need = el("p", { class: "msg-error", role: "status", hidden: true });
    const showNeed = () => {
      const cur = roleOf(curPage(), knobId);
      const dd = duoById(cur && cur.rotate && cur.rotate.duo);
      const p = dd ? resolveParams(dd, cur.rotate.params) : {};
      need.hidden = !dd || !(dd.params || []).some((x) => x.required && p[x.name] == null);
      need.textContent = dd ? t("knob.feedback.needs_setup", { name: dd.label }) : "";
    };
    const grid = el("div", { class: "kn-params" });
    for (const q of d.params) {
      const fid = nextId(`${id}-p`);
      const input = el("input", { id: fid, type: q.kind === "number" ? "number" : "text", class: "full-width", autocomplete: "off", spellcheck: "false" });
      if (q.kind === "number") {
        if (q.min != null) input.min = String(q.min);
        if (q.max != null) input.max = String(q.max);
        input.step = "1";
        if (q.default != null) input.placeholder = String(q.default);
      }
      const stored = sel.params && sel.params[q.name];
      input.value = stored != null ? String(stored) : q.default != null && q.kind === "number" ? String(q.default) : "";
      input.addEventListener("input", () => {
        const v = q.kind === "number" ? numberOrNull(input.value) : input.value.trim() || null;
        if (Number.isNaN(v)) return;
        editRole(
          knobId,
          (x) => {
            if (!x.rotate || !x.rotate.duo) return;
            const params = { ...(x.rotate.params || {}) };
            if (v == null) delete params[q.name];
            else params[q.name] = v;
            x.rotate.params = params;
          },
          { typing: true },
        );
        lightSync();
        showNeed();
      });
      grid.append(el("div", { class: "insp-field" }, el("label", { for: fid, text: `${q.label}${q.required ? " *" : ""}` }), input));
    }
    panel.append(grid, need);
    showNeed();
  }

  function renderSplitPanel(r) {
    const side = ui.zone === "right" ? "right" : "left";
    panel.append(el("div", { class: "kn-label", text: t(`inspector.knob.split.${side}`) }));
    const host = el("div", { class: "kn-action" });
    panel.append(host);
    const rot = r && r.rotate && !r.rotate.duo ? r.rotate : null;
    editors.push(
      createActionEditor(host, {
        value: rot && rot[side],
        onSet: (a, typing) => {
          editRole(
            knobId,
            (x) => {
              if (!x.rotate || x.rotate.duo) x.rotate = {};
              if (a) x.rotate[side] = a;
              else delete x.rotate[side];
            },
            { typing },
          );
          lightSync();
        },
      }),
    );
  }

  function renderPressPanel(r) {
    panel.append(el("div", { class: "kn-label", text: t("inspector.knob.press.title") }));
    const host = el("div", { class: "kn-action" });
    panel.append(host);
    editors.push(
      createActionEditor(host, {
        value: r && r.press,
        onSet: (a, typing) => {
          editRole(
            knobId,
            (x) => {
              if (a) x.press = a;
              else delete x.press;
            },
            { typing },
          );
          lightSync();
        },
      }),
    );
  }

  applyAll.addEventListener("click", () => {
    snapshotBeforeAction();
    const src = roleOf(curPage(), knobId);
    for (const p of state.cfg.pages) setRole(p, knobId, src ? deepCloneJson(src) : null);
    renderDeck();
    scheduleAutosave();
    renderAll();
    applyMsg.textContent = t("inspector.knob.apply_all.done", { pages: state.cfg.pages.length });
  });

  // step 2: display and test
  const step2 = el("section", { class: "insp-step", "aria-labelledby": `${id}-h2` });
  step2.append(el("h3", { id: `${id}-h2` }, el("b", { "aria-hidden": "true", text: "2" }), el("span", { text: t("inspector.knob.step2.title") })));
  const slider = el("input", { type: "range", id: `${id}-secs`, min: "0", max: "2", step: "0.1", "aria-describedby": `${id}-secs-v` });
  const secsTag = el("span", { class: "tag", id: `${id}-secs-v` });
  const effSecs = () => {
    const r = roleOf(curPage(), knobId);
    if (r && r.feedback_sec != null) return Number(r.feedback_sec);
    const g = state.cfg.knob_page_feedback && Number(state.cfg.knob_page_feedback.duration_sec);
    return Number.isFinite(g) ? g : 2;
  };
  const paintSecs = () => {
    const v = effSecs();
    if (document.activeElement !== slider) slider.value = String(v);
    secsTag.textContent = v === 0 ? t("inspector.knob.secs.off") : t("inspector.knob.secs.value", { value: v.toFixed(1) });
  };
  slider.addEventListener("input", () => {
    const v = Math.round(Number(slider.value) * 10) / 10;
    const r = roleOf(curPage(), knobId);
    if (r && r.feedback_sec != null) editRole(knobId, (x) => (x.feedback_sec = v), { typing: true });
    else {
      snapshotBeforeEditOnce();
      state.cfg.knob_page_feedback = { ...(state.cfg.knob_page_feedback || {}), duration_sec: v };
      scheduleAutosave();
    }
    paintSecs();
  });
  const testMsg = el("p", { class: "hint", role: "status" });
  const testBtn = (side, glyphKey) => {
    const b = el("button", { type: "button", class: "btn kn-test", "data-test": side, text: t(glyphKey) });
    b.addEventListener("click", () => void runTest(side));
    return b;
  };
  async function runTest(side) {
    const r = roleOf(curPage(), knobId);
    const text = feedbackText(r, side) || t("inspector.knob.test.nothing");
    testMsg.textContent = "";
    emit("knob:flash", { knobId, text });
    try {
      await flushAutosave();
      await postSimulatePress(knobId, side === "press" ? null : side);
    } catch {
      testMsg.textContent = t("inspector.knob.test.no_device");
    }
  }
  step2.append(
    el("div", { class: "insp-row" }, el("div", { class: "insp-row-head" }, el("label", { class: "insp-row-label", for: `${id}-secs`, text: t("inspector.knob.secs.label") }), secsTag), slider),
    el("p", { class: "hint", text: t("inspector.knob.screenless") }),
    el("div", { class: "kn-tests" }, testBtn("left", "inspector.knob.test.left"), testBtn("press", "inspector.knob.test.press"), testBtn("right", "inspector.knob.test.right")),
    testMsg,
  );
  root.append(step2);

  // step 3: advanced
  const adv = el(
    "details",
    { class: "acc insp-adv" },
    el("summary", {}, el("span", {}, el("b", { class: "insp-num", "aria-hidden": "true", text: "3" }), t("inspector.step3.title"))),
  );
  adv.open = ui.advOpen;
  adv.addEventListener("toggle", () => (ui.advOpen = adv.open));
  const advBody = el("div", { class: "acc-body insp-adv-body" });
  const splitBtn = el("button", { type: "button", class: "btn kn-split", text: "" });
  splitBtn.addEventListener("click", () => {
    if (splitNow()) {
      ui.split = false;
      ui.zone = "rot";
      editRole(knobId, (x) => delete x.rotate);
    } else {
      ui.split = true;
      ui.zone = "left";
      const cur = roleOf(curPage(), knobId);
      const d = cur && cur.rotate && cur.rotate.duo ? duoById(cur.rotate.duo) : null;
      if (d) editRole(knobId, (x) => (x.rotate = { left: expandDuo(d, cur.rotate.params, "left"), right: expandDuo(d, cur.rotate.params, "right") }));
    }
    renderAll();
  });
  const json = el("textarea", { class: "mono full-width insp-json", rows: "8", spellcheck: "false", "aria-label": t("inspector.knob.json.label") });
  const jsonMsg = el("p", { class: "hint insp-json-msg", role: "status" });
  const jsonApply = el("button", { type: "button", class: "btn", text: t("inspector.knob.json.apply") });
  const paintJson = () => {
    if (document.activeElement === json) return;
    json.value = JSON.stringify(roleOf(curPage(), knobId) || {}, null, 2);
  };
  jsonApply.addEventListener("click", () => {
    let o;
    try {
      o = JSON.parse(json.value.trim() || "{}");
      if (!o || typeof o !== "object" || Array.isArray(o)) throw new Error(t("inspector.knob.json.object"));
    } catch (e) {
      jsonMsg.textContent = e.message || String(e);
      jsonMsg.classList.add("is-error");
      return;
    }
    jsonMsg.classList.remove("is-error");
    jsonMsg.textContent = t("inspector.knob.json.applied");
    editRole(knobId, (x) => {
      for (const k of Object.keys(x)) delete x[k];
      Object.assign(x, o);
    });
    ui.split = false;
    renderAll();
  });
  advBody.append(
    el("div", { class: "insp-group" }, el("h4", { text: t("inspector.knob.split.title") }), el("p", { class: "hint", text: t("inspector.knob.split.hint") }), splitBtn),
    el("div", { class: "insp-group" }, el("h4", { text: t("inspector.knob.json.title") }), el("p", { class: "hint", text: t("inspector.knob.json.hint") }), json, jsonApply, jsonMsg),
  );
  adv.append(advBody);
  root.append(adv);
  host.append(root);

  lightSync = () => {
    renderChips();
    renderDial();
    paintJson();
    paintSecs();
  };
  function renderAll() {
    const sp = splitNow();
    if (!sp && (ui.zone === "left" || ui.zone === "right")) ui.zone = "rot";
    if (sp && ui.zone === "rot") ui.zone = "left";
    splitBtn.textContent = sp ? t("inspector.knob.split.off") : t("inspector.knob.split.on");
    renderChips();
    renderDial();
    renderPanel();
    paintJson();
    paintSecs();
    if (restoreFocus) {
      const n = root.querySelector(restoreFocus);
      restoreFocus = null;
      if (n) n.focus();
    }
  }
  renderAll();
}

/* ---- inspector view contract ----------------------------------------------------------------- */

export const knobView = {
  render(host, { knobId, close }) {
    if (ui.knobId !== knobId) {
      ui.knobId = knobId;
      ui.zone = "rot";
      ui.split = false;
    }
    ctxClose = close;
    this._host = host;
    this._knobId = knobId;
    active = this;
    render(host, knobId);
  },
  /** Config replaced (Undo), page switched, language changed: redraw (typing in a field is not interrupted). */
  refresh() {
    if (!this._host || !root) return;
    const a = document.activeElement;
    if (a && root.contains(a) && a.matches("input, textarea")) {
      lightSync();
      return;
    }
    if (!curPage()) return ctxClose && ctxClose();
    render(this._host, this._knobId);
  },
  destroy() {
    for (const e of editors) e.destroy();
    editors = [];
    if (root) root.remove();
    root = null;
    active = null;
    lightSync = () => {};
  },
};

/** Called once by the inspector: knob captions for the deck, duo catalogue (reloaded per language). */
export function initKnobView() {
  setKnobCaptionProvider(caption);
  void loadDuos();
  document.addEventListener("i18n:change", () => void loadDuos());
}
