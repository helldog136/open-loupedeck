/*
 * pages.js — Page tabs: at least four pages (renamable, not deletable), extra pages, inline rename,
 * add/remove, and keeping the UI's page in sync with the agent's page_index (both directions). A tab's
 * dot and the hint show the button of the edited model whose global binding opens that page
 * (`agent.goto_page`), lit with its LED colour when it has one.
 */

import { postAgentPageIndex } from "./api.js";
import { renderDeck } from "./deck.js";
import { MIN_PAGES, clampPageIndex, controlLabel, ensurePages, pageButton, pageName } from "./model.js";
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

/** LED colour of the button that opens page `i` ("" when it has none, null without such a button). */
function pageLedColor(i) {
  const b = pageButton(i);
  if (!b) return null;
  return b.color ? cssColorForLedPreview(b.color) : "";
}

export function syncUiToAgentPage(agentIndex) {
  if (Date.now() < pageIndexPollMutedUntil) return;
  const target = clampPageIndex(agentIndex);
  const changed = target !== state.pageIndex;
  state.pageIndex = target;
  const sel = $("#pageSelect");
  if (sel) sel.value = String(state.pageIndex);
  if (changed) {
    renderDeck();
    renderPageRail();
    emit("inspector:sync");
  }
}

/** One-shot GET /api/status: adopt the agent's current page. */
export async function pullAgentPage() {
  try {
    const sr = await fetch("/api/status");
    ensurePages();
    if (sr.ok) {
      const sj = await sr.json();
      if (typeof sj.page_index === "number") syncUiToAgentPage(sj.page_index);
    }
  } catch {
    ensurePages();
  }
}

function addPage() {
  snapshotBeforeAction();
  ensurePages();
  state.cfg.pages.push({ name: t("pages.default_name", { number: state.cfg.pages.length + 1 }), controls: {} });
  state.pageIndex = state.cfg.pages.length - 1;
  syncPageSelect();
  renderDeck();
  emit("inspector:sync");
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
    o.textContent = pageName(i);
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
  if (i < MIN_PAGES || state.cfg.pages.length <= MIN_PAGES) return;
  snapshotBeforeAction(); // no confirmation: Undo brings the page back
  const prevIndex = state.pageIndex;
  state.cfg.pages.splice(i, 1);
  if (state.pageIndex >= state.cfg.pages.length) state.pageIndex = state.cfg.pages.length - 1;
  else if (i < state.pageIndex) state.pageIndex -= 1;
  syncPageSelect();
  renderDeck();
  scheduleAutosave();
  if (state.pageIndex !== prevIndex) {
    emit("inspector:sync");
    void syncAgentPageIndex();
  } else void flushAutosave();
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
  renderDeck(); // captions of the buttons that open this page
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

/** Roving focus between tabs (Left / Right / Home / End), like a tab list should. */
function moveTabFocus(from, key) {
  const tabs = Array.from(document.querySelectorAll("#pageRail .pagetab"));
  const i = tabs.indexOf(from);
  let j = i;
  if (key === "ArrowLeft") j = Math.max(0, i - 1);
  else if (key === "ArrowRight") j = Math.min(tabs.length - 1, i + 1);
  else if (key === "Home") j = 0;
  else if (key === "End") j = tabs.length - 1;
  if (tabs[j]) tabs[j].focus();
}

function renderPageRail() {
  const rail = $("#pageRail");
  if (!rail || !Array.isArray(state.cfg.pages)) return;
  // Do not rebuild the tabs under the user's caret while a name is being edited.
  if (rail.querySelector('.nm[contenteditable="true"]')) return;
  rail.innerHTML = "";
  state.cfg.pages.forEach((p, i) => {
    const kept = i < MIN_PAGES;
    const tab = document.createElement("div");
    tab.className = "pagetab";
    tab.setAttribute("role", "tab");
    tab.tabIndex = i === state.pageIndex ? 0 : -1;
    tab.setAttribute("aria-selected", i === state.pageIndex ? "true" : "false");
    const btn = pageButton(i);
    const led = pageLedColor(i);
    if (led) tab.style.setProperty("--led", led);
    tab.classList.toggle("has-button", !!btn);
    tab.title = btn ? t("pages.tab.button", { button: controlLabel(btn.cid) }) : t("pages.tab.extra");

    const dot = document.createElement("i");
    dot.className = "dot";
    const num = document.createElement("span");
    num.className = "num";
    num.textContent = String(i + 1);
    const nm = document.createElement("b");
    nm.className = "nm";
    nm.textContent = pageName(i);
    tab.append(dot, num, nm);

    const pencil = document.createElement("button");
    pencil.type = "button";
    pencil.className = "tab-icon-btn pencil";
    pencil.textContent = "✎";
    pencil.tabIndex = -1;
    pencil.title = t("pages.rename");
    pencil.setAttribute("aria-label", t("pages.rename"));
    pencil.addEventListener("click", (e) => {
      e.stopPropagation();
      startRename(nm);
    });
    tab.appendChild(pencil);

    if (!kept) {
      const del = document.createElement("button");
      del.type = "button";
      del.className = "tab-icon-btn del";
      del.textContent = "×";
      del.tabIndex = -1;
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
      } else if (e.key === "F2") {
        e.preventDefault();
        startRename(nm);
      } else if (e.key === "Delete" && !kept) {
        e.preventDefault();
        removePageAt(i);
      } else if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) {
        e.preventDefault();
        moveTabFocus(tab, e.key);
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
    const btn = pageButton(state.pageIndex);
    hint.textContent = btn ? t("pages.hint.button", { button: controlLabel(btn.cid) }) : t("pages.hint.extra");
  }
}

/** Refresh the tab dots after a button's LED colour or binding changed (cheap; no re-render). */
export function syncPageLedColors() {
  document.querySelectorAll("#pageRail .pagetab").forEach((tab, i) => {
    const led = pageLedColor(i);
    if (led) tab.style.setProperty("--led", led);
    else tab.style.removeProperty("--led");
    tab.classList.toggle("has-button", led !== null);
  });
}

/** Re-render the tabs (language change, model change, a binding changed). */
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
    emit("inspector:sync");
  });

  $("#btnAddPage").addEventListener("click", addPage);
}
