/*
 * inspector/scope.js — "This page / Every page": which binding of a control the inspector edits, with
 * the inheritance made visible. Every control has an optional binding for every page (`global`) and
 * one per page that overrides it (`pages[i].controls`); the device uses the page's own when there is
 * one (model.js resolvedBinding).
 *
 * The bar says, in words, what applies on the page shown and offers the next sensible step:
 *   this page, inherits the every-page binding -> "Override on this page" / "Edit the one for every page"
 *   this page, overrides it                    -> "Remove this page's override"
 *   this page, own binding, nothing global     -> "Use on every page"
 *   every page, this page overrides it         -> "Show this page's own"
 * `inherits()` is true in the first case: the view then shows the bar and a summary instead of editors,
 * so nobody edits the wrong binding by accident. Changing scope calls `onScope()` (the inspector
 * rebuilds the view).
 */

import { editScope, globalEntry, overridingPages, pageEntry, pageName, setEditScope, setEntry } from "../model.js";
import { state } from "../state.js";
import { snapshotBeforeAction } from "../undo.js";
import { deepCloneJson } from "../util.js";
import { el, nextId } from "./dom.js";
import { afterBindingChange } from "./edit.js";

/** True when the control, edited on this page, only shows the binding for every page. */
export function inheritsGlobal(cid) {
  return editScope(cid) === "page" && !pageEntry(cid) && !!globalEntry(cid);
}

/**
 * `describe(entry)` -> short text of a binding ("Next track", "Volume"); `onScope()` after a change of
 * scope or of where the binding lives.
 */
export function createScopeBar(cid, { describe = () => "", onScope = () => {} } = {}) {
  const id = nextId("insp-scope");
  const label = el("span", { class: "insp-scope-label", id: `${id}-l`, text: t("inspector.scope.label") });
  const bPage = el("button", { type: "button", "data-scope": "page", text: t("inspector.scope.this_page") });
  const bAll = el("button", { type: "button", "data-scope": "global", text: t("inspector.scope.every_page") });
  const seg = el("div", { class: "seg insp-scope-seg", role: "group", "aria-labelledby": `${id}-l` }, bPage, bAll);
  const status = el("p", { class: "insp-scope-status", id: `${id}-s`, role: "status" });
  const actions = el("div", { class: "insp-scope-actions" });
  const root = el("div", { class: "insp-scopebar" }, el("div", { class: "insp-scope-row" }, label, seg), status, actions);
  seg.setAttribute("aria-describedby", `${id}-s`);

  const pick = (scope) => {
    if (scope === editScope(cid)) return;
    setEditScope(cid, scope);
    onScope();
  };
  bPage.addEventListener("click", () => pick("page"));
  bAll.addEventListener("click", () => pick("global"));

  function action(key, cls, fn) {
    const b = el("button", { type: "button", class: `btn btn-sm ${cls}`, "data-scope-action": key, text: t(`inspector.scope.${key}`) });
    b.addEventListener("click", fn);
    return b;
  }

  /** Move or copy bindings, then tell the inspector (one Undo step). */
  function change(mutate, scope) {
    snapshotBeforeAction();
    mutate();
    if (scope) setEditScope(cid, scope);
    afterBindingChange();
    onScope();
  }

  const quote = (e) => {
    const s = e ? String(describe(e) || "").trim() : "";
    return s || t("inspector.scope.something");
  };

  function sync() {
    const scope = editScope(cid);
    const own = pageEntry(cid);
    const all = globalEntry(cid);
    const page = pageName(state.pageIndex);
    bPage.setAttribute("aria-pressed", String(scope === "page"));
    bAll.setAttribute("aria-pressed", String(scope === "global"));
    actions.textContent = "";
    root.dataset.state = "";
    if (scope === "page") {
      if (own && all) {
        root.dataset.state = "override";
        status.textContent = t("inspector.scope.status.overrides", { page, what: quote(all) });
        actions.append(action("remove_override", "", () => change(() => setEntry(cid, null, "page"))));
      } else if (!own && all) {
        root.dataset.state = "inherits";
        status.textContent = t("inspector.scope.status.inherits", { page, what: quote(all) });
        actions.append(
          action("override", "btn-primary", () => change(() => setEntry(cid, deepCloneJson(all), "page"))),
          action("edit_global", "", () => pick("global")),
        );
      } else if (own) {
        status.textContent = t("inspector.scope.status.page_only", { page });
        actions.append(
          action("make_global", "", () =>
            change(() => {
              setEntry(cid, deepCloneJson(own), "global");
              setEntry(cid, null, "page");
            }, "global"),
          ),
        );
      } else {
        status.textContent = t("inspector.scope.status.page_empty", { page });
      }
      return;
    }
    const others = overridingPages(cid);
    const here = others.includes(state.pageIndex);
    if (!all) {
      status.textContent = t("inspector.scope.status.global_empty");
    } else if (!others.length) {
      status.textContent = t("inspector.scope.status.global");
    } else {
      status.textContent = t("inspector.scope.status.global_except", { pages: others.map((i) => pageName(i)).join(", ") });
    }
    if (here) {
      root.dataset.state = "overridden";
      actions.append(action("show_page", "", () => pick("page")));
    }
  }
  sync();
  return { root, sync };
}
