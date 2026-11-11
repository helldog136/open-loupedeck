/*
 * inspector/index.js — The right-hand inspector panel (#mount-inspector): empty state, and opening a
 * control ("control:open" cid) in the view its capabilities call for (controls.js viewKind): the knob
 * view for a control that rotates (knob-view.js, registered as "knob"), the action view for one with a
 * press (key-view.js: action, + Appearance with an image, + Light with an LED), a note otherwise.
 * Re-syncs after Undo, a page switch, a change of edited scope or a language change.
 *
 * Extension point (the knob view is registered through it):
 *   registerInspectorView("knob", {
 *     render(container, ctx) { ... },   // ctx = { knobId, close(), onScope() }; container is empty and visible
 *     destroy() { ... },                // called before the panel shows something else
 *     refresh?() { ... },               // optional: config replaced (Undo) / language changed
 *   });
 * "knob:open" ({knobId}) is still accepted and opens a knob like "control:open".
 */

import { control } from "../model.js";
import { on, state } from "../state.js";
import { $ } from "../util.js";
import { viewKind } from "./controls.js";
import { el } from "./dom.js";
import { createKeyView, createUnsupportedView } from "./key-view.js";
import { initKnobView, knobView } from "./knob-view.js";
import { stopSidebarAnimPreview } from "./preview.js";

const views = new Map();
/** What the panel shows: { type: "empty" | "control" | "view", id, kind, view } */
let current = { type: "empty" };
let host = null;

/** Register (or replace) a named inspector view; "knob" is used for controls that rotate. */
export function registerInspectorView(name, view) {
  if (!name || !view || typeof view.render !== "function") throw new Error("registerInspectorView: view needs render()");
  views.set(name, view);
  if (name === "knob" && current.type === "view" && current.name === "knob") openKnob(current.id);
}

function teardown() {
  stopSidebarAnimPreview();
  if (current.view) {
    try {
      current.view.destroy();
    } catch (err) {
      console.error(err);
    }
  }
  if (host) host.textContent = "";
  current = { type: "empty" };
}

function renderEmpty() {
  teardown();
  host.hidden = false;
  const keys = state.model ? state.model.controls.filter((c) => c.kind === "key").length : 0;
  host.append(
    el(
      "div",
      { class: "insp-step insp-empty-state" },
      el("div", { class: "insp-empty-deck", "aria-hidden": "true" }, ...Array.from({ length: 6 }, () => el("span"))),
      el("strong", { text: t(keys ? "inspector.empty.title" : "inspector.empty.title_controls") }),
      el("span", { text: t("inspector.empty.hint") }),
      el("span", { class: "insp-empty-keys", text: t("inspector.empty.keys") }),
    ),
  );
}

/** Rebuild whatever control is open (its edited scope changed, or the binding moved). */
function reopen() {
  const cid = current.id;
  if (!cid) return;
  teardown();
  openControl(cid);
}

/** Open a control — the handler of "control:open". */
export function openControl(cid) {
  if (!host) return;
  if (!cid || !control(cid)) {
    state.selectedControl = null;
    renderEmpty();
    return;
  }
  const kind = viewKind(cid);
  if (kind === "knob") {
    openKnob(cid);
    return;
  }
  state.selectedControl = cid;
  if (current.type === "control" && current.id === cid && current.kind === kind) {
    host.hidden = false;
    current.view.refresh(true);
    return;
  }
  teardown();
  host.hidden = false;
  const view = kind === "action" ? createKeyView(host, cid, { onScope: reopen }) : createUnsupportedView(host, cid);
  current = { type: "control", id: cid, kind, view };
  revealOnNarrowScreens();
}

/** Open a control that rotates in the registered "knob" view. */
export function openKnob(knobId) {
  if (!host) return;
  const v = views.get("knob");
  if (!v) return;
  teardown();
  state.selectedControl = knobId;
  host.hidden = false;
  v.render(host, { knobId, close: () => openControl(null), onScope: reopen });
  current = { type: "view", name: "knob", id: knobId, view: v };
  revealOnNarrowScreens();
}

/** Narrow screens stack the inspector under the deck: bring it into view. */
function revealOnNarrowScreens() {
  if (window.matchMedia && window.matchMedia("(max-width: 960px)").matches) {
    host.closest("#mount-inspector")?.scrollIntoView({ block: "start", behavior: "smooth" });
  }
}

/**
 * Re-read the config into whatever is open (Undo/redo, backup restore). `rebuild`: the edited model
 * changed, so the control's capabilities (and the view's steps) may have too.
 */
export function refreshInspector({ rebuild = false } = {}) {
  if (!host) return;
  const cid = current.id;
  if (current.type === "empty") return renderEmpty();
  if (state.selectedControl !== cid || !control(cid)) {
    state.selectedControl = null;
    return renderEmpty();
  }
  if (rebuild) return reopen();
  if (current.type === "control") {
    if (viewKind(cid) !== current.kind) return reopen();
    current.view.refresh(true);
  } else if (current.view.refresh) {
    current.view.refresh();
  }
}

/** Rebuild the open view (labels change with the language). */
function rebuild() {
  if (current.type === "empty") renderEmpty();
  else reopen();
}

/** Labels, option labels and help come translated from the server: reload the catalog in the new language. */
async function reloadCatalog() {
  const lang = (window.i18n && window.i18n.lang) || "";
  try {
    const r = await fetch(`/api/action_catalog${lang ? `?lang=${encodeURIComponent(lang)}` : ""}`);
    if (r.ok) state.actionCatalog = (await r.json()).actions || [];
  } catch {
    /* keep the previous catalog */
  }
}

/** Mount the inspector (once, after the config and catalog are loaded). */
export function initInspector() {
  host = $("#keyEditorBlock");
  if (!host) return;
  views.set("knob", knobView);
  initKnobView();
  renderEmpty();
  on("control:open", openControl);
  on("knob:open", (arg) => openControl(arg && typeof arg === "object" ? arg.knobId : arg));
  on("inspector:reopen", reopen);
  // Another module changed the selection or the page shown (page switch).
  on("inspector:sync", () => {
    if (state.selectedControl !== (current.id || null)) {
      if (state.selectedControl) openControl(state.selectedControl);
      else renderEmpty();
    } else if (current.type !== "empty") {
      // Same control, other page: what this page binds may differ (inherits / overrides).
      reopen();
    }
  });
  document.addEventListener("i18n:change", async () => {
    await reloadCatalog();
    rebuild();
  });
}

