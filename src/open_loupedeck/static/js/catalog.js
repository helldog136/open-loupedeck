/*
 * catalog.js — Action catalog and the categorised action-type picker that enhances a native <select>
 * (main editor and knob rotate selects).
 */

import { state } from "./state.js";
import { $ } from "./util.js";

export function getSpec(type) {
  return state.actionCatalog.find((a) => a.type === type) || null;
}

export function populateActionTypeSelect() {
  const sel = $("#actionType");
  if (!sel) return;
  sel.innerHTML = "";
  const o0 = document.createElement("option");
  o0.value = "";
  o0.textContent = "— No action —";
  sel.appendChild(o0);
  for (const a of state.actionCatalog) {
    const o = document.createElement("option");
    o.value = a.type;
    o.textContent = a.label || a.type;
    sel.appendChild(o);
  }
  enhanceActionTypeSelect(sel, state.actionCatalog);
}

/* ---------------------------------------------------------------------------------------------
 * Categorized action-type picker: click the trigger for a list of categories (OBS, Spotify, ...);
 * hovering (or clicking, for touch) a category flies out a submenu of that category's actions.
 * The underlying <select> stays the single source of truth — picking an item just sets its value
 * and dispatches "change", so every existing consumer (form rendering, autosave, knob rotate
 * wiring, ...) keeps working unchanged. Reused for both the main action-type select and each
 * knob's rotate-left/rotate-right selects.
 * ------------------------------------------------------------------------------------------- */

let openActionSelectPanel = null; // { wrap, panel, trigger }
let actionSelectGlobalListenersInstalled = false;

function closeOpenActionSelectPanel() {
  if (!openActionSelectPanel) return;
  const cur = openActionSelectPanel;
  openActionSelectPanel = null;
  cur.panel.remove(); // body-appended (see openPanel) — must detach, not just hide
  cur.trigger.setAttribute("aria-expanded", "false");
}

function ensureActionSelectGlobalListeners() {
  if (actionSelectGlobalListenersInstalled) return;
  actionSelectGlobalListenersInstalled = true;
  document.addEventListener("click", (e) => {
    if (
      openActionSelectPanel &&
      !openActionSelectPanel.wrap.contains(e.target) &&
      !openActionSelectPanel.panel.contains(e.target)
    ) {
      closeOpenActionSelectPanel();
    }
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && openActionSelectPanel) closeOpenActionSelectPanel();
  });
  // The editor panel this lives in scrolls internally (overflow: auto); "scroll" does not bubble,
  // so this must be capture-phase on window to see it and keep the (fixed-positioned) dropdown
  // from visually drifting away from its trigger. Scrolling *inside* the dropdown's own panel
  // (long category lists) must not close it -- only scrolling some other ancestor should.
  window.addEventListener(
    "scroll",
    (e) => {
      if (openActionSelectPanel && !openActionSelectPanel.panel.contains(e.target)) {
        closeOpenActionSelectPanel();
      }
    },
    true,
  );
  window.addEventListener("resize", () => closeOpenActionSelectPanel());
}

/** Split a catalog label like "OBS — set program scene" into ["OBS", "set program scene"]. */
function splitCategoryFromLabel(label) {
  const s = String(label || "");
  const i = s.indexOf(" — ");
  return i === -1 ? null : [s.slice(0, i), s.slice(i + 3)];
}

/**
 * Attach the categorized dropdown UI to an already-populated <select> (main action-type select or
 * a per-knob rotate select). Safe to call more than once on the same element — later calls just
 * refresh the trigger label and item list rather than re-wrapping it.
 * @param {HTMLSelectElement} selectEl
 * @param {{type: string, label: string, category?: string}[]} items
 */
export function enhanceActionTypeSelect(selectEl, items) {
  if (!selectEl) return;
  selectEl._actionSelectItems = items;
  if (selectEl._refreshActionSelectTrigger) {
    selectEl._refreshActionSelectTrigger();
    return;
  }

  const wrap = document.createElement("div");
  wrap.className = "action-select";
  selectEl.parentNode.insertBefore(wrap, selectEl);
  wrap.appendChild(selectEl);
  selectEl.classList.add("action-select-native");
  selectEl.tabIndex = -1;

  const trigger = document.createElement("button");
  trigger.type = "button";
  trigger.className = "action-select-trigger";
  trigger.setAttribute("aria-haspopup", "true");
  trigger.setAttribute("aria-expanded", "false");
  wrap.appendChild(trigger);

  function currentLabel() {
    const t = selectEl.value;
    if (!t) return "— No action —";
    const found = (selectEl._actionSelectItems || []).find((i) => i.type === t);
    return (found && found.label) || t;
  }

  function refreshTrigger() {
    trigger.textContent = currentLabel();
  }
  selectEl._refreshActionSelectTrigger = refreshTrigger;
  refreshTrigger();

  function pick(type) {
    selectEl.value = type;
    refreshTrigger();
    closeOpenActionSelectPanel();
    selectEl.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function groupByCategory() {
    const groups = new Map();
    for (const it of selectEl._actionSelectItems || []) {
      const cat = it.category || splitCategoryFromLabel(it.label)?.[0] || "Other";
      if (!groups.has(cat)) groups.set(cat, []);
      groups.get(cat).push(it);
    }
    return groups;
  }

  function itemLabel(it) {
    const split = splitCategoryFromLabel(it.label);
    return (split && split[1]) || it.label || it.type;
  }

  // Appended to <body> (not `wrap`) and position: fixed, so it visually escapes the editor
  // panel's `overflow: auto` instead of being clipped at that panel's edge. Categories expand
  // inline (accordion-style) rather than flying out sideways: a sideways flyout needs the
  // submenu positioned relative to the viewport's right edge, which turned out unreliable in the
  // packaged app's webview (reported: the submenu rendered off-screen, needing horizontal
  // scrolling to reach) -- an inline list only ever needs vertical space, which the panel already
  // scrolls for.
  function openPanel() {
    closeOpenActionSelectPanel();
    ensureActionSelectGlobalListeners();

    const panel = document.createElement("div");
    panel.className = "action-select-panel";

    const noneRow = document.createElement("div");
    noneRow.className = "action-select-item";
    noneRow.textContent = "— No action —";
    if (!selectEl.value) noneRow.classList.add("selected");
    noneRow.addEventListener("click", () => pick(""));
    panel.appendChild(noneRow);

    for (const [cat, groupItems] of groupByCategory()) {
      const isOpenCategory = groupItems.some((it) => it.type === selectEl.value);

      const row = document.createElement("div");
      row.className = "action-select-category";
      if (isOpenCategory) row.classList.add("open");
      const caret = document.createElement("span");
      caret.className = "action-select-caret";
      caret.textContent = isOpenCategory ? "▾" : "▸";
      row.appendChild(caret);
      const catLabel = document.createElement("span");
      catLabel.textContent = cat;
      row.appendChild(catLabel);

      const sublist = document.createElement("div");
      sublist.className = "action-select-sublist";
      sublist.hidden = !isOpenCategory;
      for (const it of groupItems) {
        const subRow = document.createElement("div");
        subRow.className = "action-select-item action-select-subitem";
        subRow.textContent = itemLabel(it);
        if (it.type === selectEl.value) subRow.classList.add("selected");
        subRow.addEventListener("click", (e) => {
          e.stopPropagation();
          pick(it.type);
        });
        sublist.appendChild(subRow);
      }

      row.addEventListener("click", () => {
        const willOpen = sublist.hidden;
        sublist.hidden = !willOpen;
        row.classList.toggle("open", willOpen);
        caret.textContent = willOpen ? "▾" : "▸";
      });

      panel.appendChild(row);
      panel.appendChild(sublist);
    }

    document.body.appendChild(panel);
    const triggerRect = trigger.getBoundingClientRect();
    panel.style.left = `${Math.round(triggerRect.left)}px`;
    panel.style.top = `${Math.round(triggerRect.bottom + 4)}px`;
    panel.style.minWidth = `${Math.round(triggerRect.width)}px`;
    panel.style.maxHeight = `${Math.max(160, window.innerHeight - triggerRect.bottom - 16)}px`;

    trigger.setAttribute("aria-expanded", "true");
    openActionSelectPanel = { wrap, panel, trigger };

    const selectedEl = panel.querySelector(".action-select-item.selected");
    if (selectedEl) selectedEl.scrollIntoView({ block: "nearest" });
  }

  trigger.addEventListener("click", (e) => {
    e.stopPropagation();
    if (openActionSelectPanel && openActionSelectPanel.wrap === wrap) closeOpenActionSelectPanel();
    else openPanel();
  });
}

/** Action types that do not apply to encoder rotation (e.g. display-only overlays). */
export function knobCompatibleActionList() {
  return state.actionCatalog.filter(
    (a) => a && a.type && !String(a.type).startsWith("display.")
  );
}

/**
 * Fill a &lt;select&gt; with action types suitable for knob rotate (excludes display.*).
 * @param {string} [currentType] if set and incompatible, append one option so the value stays visible.
 */
export function populateKnobActionSelect(sel, currentType) {
  if (!sel) return;
  sel.innerHTML = "";
  const o0 = document.createElement("option");
  o0.value = "";
  o0.textContent = "— No action —";
  sel.appendChild(o0);
  const list = knobCompatibleActionList();
  for (const a of list) {
    const o = document.createElement("option");
    o.value = a.type;
    o.textContent = a.label || a.type;
    sel.appendChild(o);
  }
  const ct = currentType != null && String(currentType).trim() !== "" ? String(currentType).trim() : "";
  if (ct && !list.some((a) => a.type === ct)) {
    const spec = getSpec(ct);
    if (spec) {
      const ox = document.createElement("option");
      ox.value = ct;
      ox.textContent = `${spec.label || ct} (not for knobs — choose another)`;
      sel.appendChild(ox);
    }
  }
}
