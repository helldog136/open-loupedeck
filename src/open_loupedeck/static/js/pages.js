/*
 * pages.js — Page tabs and page header: the four hardware pages (page N = round button N, coloured with
 * that button's LED), extra pages 5+, inline rename, add/remove, and keeping the UI's page in sync with
 * the agent's page_index (both directions).
 */

import { postAgentPageIndex } from "./api.js";
import { renderDeck } from "./deck.js";
import { syncCopyPasteButtons, syncTestPressButton } from "./inspector/panel.js";
import { HARDWARE_PAGE_COUNT, clampPageIndex, currentPage, ensurePages } from "./model.js";
import { flushAutosave, scheduleAutosave } from "./save.js";
import { emit, state } from "./state.js";
import { snapshotBeforeAction } from "./undo.js";
import { $, cssColorForLedPreview } from "./util.js";

/**
 * While we are changing the page ourselves (click a tab, add/remove a page), ignore the status poll's
 * reported page_index. The poll can race a local change in either direction — a response already in
 * flight when we click, or a POST that takes a while because the agent waits for the physical redraw —
 * and trusting it snaps the UI back to the old page for a moment. The mute covers the whole sync
 * (until the agent has the new index) plus a short cooldown afterwards; later, a poll reporting a
 * different page (e.g. a real button press) is applied normally.
 */
const PAGE_INDEX_POLL_COOLDOWN_MS = 2000;
let pageIndexPollMutedUntil = 0;

function muteAgentPagePollBriefly() {
  pageIndexPollMutedUntil = Date.now() + PAGE_INDEX_POLL_COOLDOWN_MS;
}

/** Round buttons bound to pages 1-4, and the LED colour used when the config has none yet. */
const PAGE_BUTTON_IDS = ["btn_circle", "btn_1", "btn_2", "btn_3"];
const DEFAULT_PAGE_LEDS = ["#3b6bff", "#ff8a2b", "#e040c8", "#2de0c0"];

function pageLedColor(i) {
  if (i >= HARDWARE_PAGE_COUNT) return null;
  const e = state.cfg.global_buttons && state.cfg.global_buttons[PAGE_BUTTON_IDS[i]];
  const raw = e && e.button_color && String(e.button_color).trim();
  return raw ? cssColorForLedPreview(raw) : DEFAULT_PAGE_LEDS[i];
}

function pageLabel(i) {
  const p = state.cfg.pages[i];
  return (p && p.name) || t("pages.default_name", { number: i + 1 });
}

function resetSelectionLabel() {
  const sl = $("#selLabel");
  if (sl) sl.textContent = t("shell.select_control");
}

export function syncUiToAgentPage(agentIndex) {
  if (Date.now() < pageIndexPollMutedUntil) return;
  const target = clampPageIndex(agentIndex);
  const changed = target !== state.pageIndex;
  state.pageIndex = target;
  const sel = $("#pageSelect");
  if (sel) sel.value = String(state.pageIndex);
  $("#pageName").textContent = currentPage().name || pageLabel(state.pageIndex);
  if (changed) {
    renderDeck();
    renderPageRail();
    state.selectedControl = null;
    resetSelectionLabel();
    syncTestPressButton();
    syncCopyPasteButtons();
  }
}

/** One-shot GET /api/status: adopt the agent's resolved deck layout and current page. */
export async function pullAgentLayoutAndPage() {
  try {
    const sr = await fetch("/api/status");
    if (sr.ok) {
      const sj = await sr.json();
      if (sj.deck_layout === "live" || sj.deck_layout === "live_s") {
        state.agentDeckLayout = sj.deck_layout;
      } else {
        state.agentDeckLayout = null;
      }
      ensurePages();
      if (typeof sj.page_index === "number") {
        syncUiToAgentPage(sj.page_index);
      }
    } else {
      ensurePages();
    }
  } catch {
    ensurePages();
  }
}

/** Kept for callers that re-lay out the deck: the tabs are the same for every model. */
export function updateLiveSPageChrome() {
  renderPageRail();
}

function addPage() {
  snapshotBeforeAction();
  ensurePages();
  state.cfg.pages.push({
    id: state.cfg.pages.length,
    name: t("pages.default_name", { number: state.cfg.pages.length + 1 }),
    buttons: {},
  });
  state.pageIndex = state.cfg.pages.length - 1;
  syncPageSelect();
  renderDeck();
  scheduleAutosave();
  syncAgentPageIndex();
}

export function syncPageSelect() {
  ensurePages();
  const sel = $("#pageSelect");
  sel.innerHTML = "";
  state.cfg.pages.forEach((p, i) => {
    const o = document.createElement("option");
    o.value = String(i);
    o.textContent = p.name || pageLabel(i);
    sel.appendChild(o);
  });
  sel.value = String(state.pageIndex);
  renderPageRail();
}

/** Clicking a tab reuses the hidden #pageSelect "change" wiring (page switch, agent sync, etc.). */
function selectPageIndex(i) {
  const sel = $("#pageSelect");
  if (!sel) return;
  sel.value = String(i);
  sel.dispatchEvent(new Event("change", { bubbles: true }));
}

/**
 * The agent (and the physical device) track their own `page_index` server-side; a background poll
 * (every 1.5 s) pulls it back into the client whenever they differ. Any client-side operation that
 * changes which numeric index the active page sits at must push that index to the agent too, or the
 * next poll snaps the UI back to the stale server-side page.
 *
 * The agent only knows pages it has been sent, and the debounced autosave is what sends them: so a
 * freshly added page must be saved BEFORE its index is posted, or the agent rejects/ignores the index
 * and the poll then pulls the UI back (the old "Add page jumps back to page 1" bug).
 */
export async function syncAgentPageIndex() {
  pageIndexPollMutedUntil = Number.POSITIVE_INFINITY;
  try {
    await flushAutosave();
    await postAgentPageIndex(state.pageIndex);
  } catch (e) {
    $("#saveError").textContent = String(e);
  } finally {
    muteAgentPagePollBriefly();
  }
}

function removePageAt(i) {
  ensurePages();
  if (i < HARDWARE_PAGE_COUNT || state.cfg.pages.length <= HARDWARE_PAGE_COUNT) return;
  snapshotBeforeAction(); // no confirmation: Undo brings the page back
  const prevIndex = state.pageIndex;
  state.cfg.pages.splice(i, 1);
  if (state.pageIndex >= state.cfg.pages.length) state.pageIndex = state.cfg.pages.length - 1;
  else if (i < state.pageIndex) state.pageIndex -= 1;
  syncPageSelect();
  renderDeck();
  scheduleAutosave();
  if (state.pageIndex !== prevIndex) void syncAgentPageIndex();
  else void flushAutosave();
}

/** Commit (or cancel) an inline rename. */
function finishRename(i, nameEl, commit) {
  nameEl.contentEditable = "false";
  const next = nameEl.textContent.trim();
  const page = state.cfg.pages[i];
  if (commit && next && page && next !== page.name) {
    snapshotBeforeAction();
    page.name = next;
    scheduleAutosave();
  }
  syncPageSelect();
  $("#pageName").textContent = currentPage().name || pageLabel(state.pageIndex);
}

function startRename(nameEl) {
  nameEl.contentEditable = "true";
  nameEl.focus();
  const range = document.createRange();
  range.selectNodeContents(nameEl);
  const sel = window.getSelection();
  sel.removeAllRanges();
  sel.addRange(range);
}

function renderPageRail() {
  const rail = $("#pageRail");
  if (!rail || !Array.isArray(state.cfg.pages)) return;
  // Do not rebuild the tabs under the user's caret while a name is being edited.
  if (rail.querySelector('.nm[contenteditable="true"]')) return;
  rail.innerHTML = "";
  state.cfg.pages.forEach((p, i) => {
    const hardware = i < HARDWARE_PAGE_COUNT;
    const tab = document.createElement("div");
    tab.className = "pagetab";
    tab.setAttribute("role", "tab");
    tab.tabIndex = 0;
    tab.setAttribute("aria-selected", i === state.pageIndex ? "true" : "false");
    const led = pageLedColor(i);
    if (led) tab.style.setProperty("--led", led);
    tab.title = hardware
      ? t("pages.tab.hardware", { number: i + 1 })
      : t("pages.tab.extra");

    const dot = document.createElement("i");
    dot.className = "dot";
    const num = document.createElement("span");
    num.className = "num";
    num.textContent = String(i + 1);
    const nm = document.createElement("b");
    nm.className = "nm";
    nm.textContent = pageLabel(i);
    tab.append(dot, num, nm);

    const pencil = document.createElement("button");
    pencil.type = "button";
    pencil.className = "tab-icon-btn pencil";
    pencil.textContent = "✎";
    pencil.title = t("pages.rename");
    pencil.setAttribute("aria-label", t("pages.rename"));
    pencil.addEventListener("click", (e) => {
      e.stopPropagation();
      startRename(nm);
    });
    tab.appendChild(pencil);

    if (!hardware) {
      const del = document.createElement("button");
      del.type = "button";
      del.className = "tab-icon-btn del";
      del.textContent = "×";
      del.title = t("pages.delete");
      del.setAttribute("aria-label", t("pages.delete"));
      del.addEventListener("click", (e) => {
        e.stopPropagation();
        removePageAt(i);
      });
      tab.appendChild(del);
    }

    tab.addEventListener("click", () => {
      if (nm.isContentEditable) return;
      if (i !== state.pageIndex) selectPageIndex(i);
    });
    tab.addEventListener("keydown", (e) => {
      if (e.target !== tab) return;
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        if (i !== state.pageIndex) selectPageIndex(i);
      }
    });
    tab.addEventListener("dblclick", () => startRename(nm));
    nm.addEventListener("keydown", (e) => {
      e.stopPropagation();
      if (e.key === "Enter") {
        e.preventDefault();
        finishRename(i, nm, true);
      } else if (e.key === "Escape") {
        e.preventDefault();
        finishRename(i, nm, false);
      }
    });
    nm.addEventListener("blur", () => {
      if (nm.isContentEditable) finishRename(i, nm, true);
    });
    rail.appendChild(tab);
  });

  const hint = $("#pagesHint");
  if (hint) {
    hint.textContent =
      state.pageIndex < HARDWARE_PAGE_COUNT
        ? t("pages.hint.hardware", { number: state.pageIndex + 1 })
        : t("pages.hint.extra");
  }
}

/** Refresh the tab dots after a button's LED colour changed (cheap; no re-render). */
export function syncPageLedColors() {
  document.querySelectorAll("#pageRail .pagetab").forEach((tab, i) => {
    const led = pageLedColor(i);
    if (led) tab.style.setProperty("--led", led);
  });
}

/** Re-render the tabs (language change). */
export function refreshPageTabs() {
  renderPageRail();
}

/** Hidden #pageSelect (page switch) and "+ Page". */
export function wirePageSelect() {
  $("#pageSelect").addEventListener("change", () => {
    state.pageIndex = Number($("#pageSelect").value);
    // Respond immediately from the client's own state; the agent (and physical device) catch up
    // in the background. Never block the UI switch on this request's completion.
    void syncAgentPageIndex();
    renderDeck();
    renderPageRail();
    state.selectedControl = null;
    emit("inspector:sync"); // an open knob shows its role on the new page
    resetSelectionLabel();
    syncTestPressButton();
  });

  $("#btnAddPage").addEventListener("click", addPage);
}
