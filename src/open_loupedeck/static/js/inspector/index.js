/*
 * inspector/index.js — The right-hand inspector panel (#mount-inspector): empty state, opening a
 * control ("control:open" cid) in the key view or the page-button view, opening a knob ("knob:open"
 * {knobId}) in a registered view (or the legacy encoder editor), and re-syncing after Undo, a page
 * switch or a language change.
 *
 * Extension point for other packages (e.g. the knob editor):
 *   registerInspectorView("knob", {
 *     render(container, ctx) { ... },   // ctx = { knobId, close() }; container is empty and visible
 *     destroy() { ... },                // called before the panel shows something else
 *     refresh?() { ... },               // optional: config replaced (Undo) / language changed
 *   });
 */

import { isKnobEncoderId } from "../model.js";
import { openKnobEncoderEditor } from "../knobs.js";
import { on, state } from "../state.js";
import { $ } from "../util.js";
import { controlKind } from "./controls.js";
import { el } from "./dom.js";
import { createKeyView } from "./key-view.js";
import { createPageButtonView } from "./page-button-view.js";
import { stopSidebarAnimPreview } from "./preview.js";

const views = new Map();
/** What the panel shows: { type: "empty" | "control" | "view" | "legacy-knob", id, view } */
let current = { type: "empty" };
let host = null;

/** Register (or replace) a named inspector view; "knob" is used for `knob:open`. */
export function registerInspectorView(name, view) {
  if (!name || !view || typeof view.render !== "function") throw new Error("registerInspectorView: view needs render()");
  views.set(name, view);
  if (name === "knob" && (current.type === "legacy-knob" || (current.type === "view" && current.name === "knob"))) {
    openKnob(current.id);
  }
}

function blocks() {
  return { key: $("#keyEditorBlock"), knob: $("#knobEncoderEditorBlock") };
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

function showInspectorBlock() {
  const b = blocks();
  if (b.key) b.key.hidden = false;
  if (b.knob) b.knob.hidden = true;
}

function renderEmpty() {
  teardown();
  showInspectorBlock();
  host.append(
    el(
      "div",
      { class: "insp-step insp-empty-state" },
      el("div", { class: "insp-empty-deck", "aria-hidden": "true" }, ...Array.from({ length: 6 }, () => el("span"))),
      el("strong", { text: t("inspector.empty.title") }),
      el("span", { text: t("inspector.empty.hint") }),
    ),
  );
}

/** Open a control (touch key, side screen, button) — the handler of "control:open". */
export function openControl(cid) {
  if (!host) return;
  if (isKnobEncoderId(cid)) {
    openKnob(cid);
    return;
  }
  if (!cid) {
    state.selectedControl = null;
    renderEmpty();
    return;
  }
  const sameControl = current.type === "control" && current.id === cid;
  state.selectedKnobEncoder = null;
  state.selectedControl = cid;
  if (sameControl) {
    showInspectorBlock();
    current.view.refresh(true);
    return;
  }
  teardown();
  showInspectorBlock();
  const kind = controlKind(cid);
  const view = kind === "pageButton" ? createPageButtonView(host, cid) : createKeyView(host, cid, kind);
  current = { type: "control", id: cid, kind, view };
  // Narrow screens stack the inspector under the deck: bring it into view.
  if (window.matchMedia && window.matchMedia("(max-width: 960px)").matches) {
    host.closest("#mount-inspector")?.scrollIntoView({ block: "start", behavior: "smooth" });
  }
}

/** Open a knob: the registered "knob" view, else the legacy encoder editor. */
export function openKnob(knobId) {
  if (!host) return;
  const v = views.get("knob");
  teardown();
  state.selectedControl = null;
  state.selectedKnobEncoder = knobId;
  if (!v) {
    current = { type: "legacy-knob", id: knobId };
    openKnobEncoderEditor(knobId);
    return;
  }
  showInspectorBlock();
  v.render(host, { knobId, close: () => openControl(null) });
  current = { type: "view", name: "knob", id: knobId, view: v };
}

/** Re-read the config into whatever is open (Undo/redo, backup restore, device model change). */
export function refreshInspector() {
  if (!host) return;
  if (current.type === "control") {
    const cid = current.id;
    if (state.selectedControl !== cid) return renderEmpty();
    if (controlKind(cid) !== current.kind) {
      // The device model changed what this control is (e.g. a Live S page button on a Live).
      teardown();
      return openControl(cid);
    }
    current.view.refresh(true);
  } else if (current.type === "view" && current.view.refresh) {
    current.view.refresh();
  } else if (current.type === "legacy-knob") {
    openKnobEncoderEditor(current.id);
  }
}

/** Rebuild the open view (labels change with the language). */
function rebuild() {
  if (current.type === "control") {
    const cid = current.id;
    teardown();
    openControl(cid);
  } else if (current.type === "view" && current.view.refresh) current.view.refresh();
  else if (current.type === "empty") renderEmpty();
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
  const b = blocks();
  host = b.key;
  if (!host) return;
  renderEmpty();
  on("control:open", openControl);
  on("knob:open", (arg) => openKnob(arg && typeof arg === "object" ? arg.knobId : arg));
  // Another module changed the selection (page switch, legacy encoder editor closed).
  on("inspector:sync", () => {
    if (current.type === "control" && state.selectedControl !== current.id) {
      if (state.selectedControl) openControl(state.selectedControl);
      else renderEmpty();
    } else if (current.type === "legacy-knob" && !state.selectedKnobEncoder && !b.key.hidden) {
      renderEmpty();
    }
  });
  document.addEventListener("i18n:change", async () => {
    await reloadCatalog();
    rebuild();
  });
}

/** For tests and other modules: the control currently open (null when none). */
export function openedControl() {
  return current.type === "control" ? current.id : null;
}
