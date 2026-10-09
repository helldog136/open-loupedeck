/*
 * pages.js — Page rail and page header: list/select/add/rename/remove/reorder pages, and keeping the
 * UI's page in sync with the agent's page_index (both directions).
 */

import { postAgentPageIndex } from "./api.js";
import { renderDeck } from "./deck.js";
import { syncCopyPasteButtons, syncTestPressButton } from "./inspector/panel.js";
import { closeKnobEncoderEditor } from "./knobs.js";
import { clampPageIndex, currentPage, ensurePages, isLiveSModel } from "./model.js";
import { scheduleAutosave } from "./save.js";
import { state } from "./state.js";
import { snapshotBeforeAction } from "./undo.js";
import { $ } from "./util.js";

/**
 * After we change the page ourselves (click a rail item, add/remove/reorder a page), ignore the
 * status poll's reported page_index for this long (ms). The poll can race a local change from
 * either direction — a response already in flight when we click, computed against the pre-click
 * server state, or (with a real device) a POST that takes a while to return because the agent
 * waits for the physical redraw — and blindly trusting it snaps the UI back to the old page for a
 * moment before a later poll corrects it forward again (a visible flicker). A flat cooldown is
 * simpler and more robust than trying to track exactly which in-flight request a given poll
 * result predates. Once it elapses, a poll reporting a different page again (e.g. a genuine
 * physical button press) is applied normally.
 */
const PAGE_INDEX_POLL_COOLDOWN_MS = 2000;
let pageIndexPollMutedUntil = 0;

function muteAgentPagePollBriefly() {
  pageIndexPollMutedUntil = Date.now() + PAGE_INDEX_POLL_COOLDOWN_MS;
}

export function syncUiToAgentPage(agentIndex) {
  if (Date.now() < pageIndexPollMutedUntil) return;
  const target = clampPageIndex(agentIndex);
  const changed = target !== state.pageIndex;
  state.pageIndex = target;
  const sel = $("#pageSelect");
  if (sel) sel.value = String(state.pageIndex);
  $("#pageName").textContent = currentPage().name || `Page ${state.pageIndex + 1}`;
  const pn = $("#pageNameInput");
  if (pn) pn.value = currentPage().name || "";
  if (changed) {
    renderDeck();
    renderPageRail();
    state.selectedControl = null;
    const sl = $("#selLabel");
    if (sl) sl.textContent = "Select a control";
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

export function updateLiveSPageChrome() {
  const hint = $(".page-rail-hint");
  if (hint) {
    hint.title = isLiveSModel()
      ? "On the device, circle + btn 1–3 only switch among page indices 0–3 (first four pages)."
      : "";
  }
  const nameIn = $("#pageNameInput");
  if (nameIn) nameIn.hidden = false;
}

function addPage() {
  snapshotBeforeAction();
  ensurePages();
  state.cfg.pages.push({ name: `Page ${state.cfg.pages.length + 1}`, buttons: {} });
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
    o.textContent = p.name || `Page ${i + 1}`;
    sel.appendChild(o);
  });
  sel.value = String(state.pageIndex);
  renderPageRail();
}

const PAGE_RAIL_HARDWARE_BADGES = ["①", "②", "③", "④"];

/** Clicking a rail item reuses the existing #pageSelect "change" wiring (page switch, agent sync, etc.). */
function selectPageIndex(i) {
  const sel = $("#pageSelect");
  if (!sel) return;
  sel.value = String(i);
  sel.dispatchEvent(new Event("change", { bubbles: true }));
}

/**
 * The agent (and the physical device) track their own `page_index` server-side; a background poll
 * (`refreshConnectionStatus`, every 1.5s) pulls it back into the client whenever they differ. Any
 * client-side operation that changes which numeric index the active page sits at (not just "switch
 * to a different page") must push that index to the agent too, or the next poll snaps the UI back
 * to the stale server-side page within ~1.5s.
 */
export function syncAgentPageIndex() {
  muteAgentPagePollBriefly();
  void postAgentPageIndex(state.pageIndex).catch((e) => {
    $("#saveError").textContent = String(e);
  });
}

function removePageAt(i) {
  ensurePages();
  if (state.cfg.pages.length <= 1) return;
  const name = state.cfg.pages[i].name || `Page ${i + 1}`;
  if (!confirm(`Remove page "${name}"?`)) return;
  snapshotBeforeAction();
  const prevIndex = state.pageIndex;
  state.cfg.pages.splice(i, 1);
  if (state.pageIndex >= state.cfg.pages.length) state.pageIndex = state.cfg.pages.length - 1;
  else if (i < state.pageIndex) state.pageIndex -= 1;
  syncPageSelect();
  renderDeck();
  scheduleAutosave();
  if (state.pageIndex !== prevIndex) syncAgentPageIndex();
}

/** Index of the page currently being dragged in the rail, or null. */
let draggingPageIndex = null;

function reorderPage(fromIndex, toIndex) {
  ensurePages();
  snapshotBeforeAction();
  const prevIndex = state.pageIndex;
  const activePage = state.cfg.pages[state.pageIndex];
  const [moved] = state.cfg.pages.splice(fromIndex, 1);
  state.cfg.pages.splice(toIndex, 0, moved);
  state.pageIndex = state.cfg.pages.indexOf(activePage);
  syncPageSelect();
  renderDeck();
  scheduleAutosave();
  if (state.pageIndex !== prevIndex) syncAgentPageIndex();
}

function wirePageRailDrag(item, index) {
  item.addEventListener("dragstart", (e) => {
    draggingPageIndex = index;
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", String(index));
    item.classList.add("dragging");
  });
  item.addEventListener("dragend", () => {
    draggingPageIndex = null;
    item.classList.remove("dragging");
    document.querySelectorAll(".page-rail-item.drag-over").forEach((el) => el.classList.remove("drag-over"));
  });
  item.addEventListener("dragover", (e) => {
    if (draggingPageIndex === null || draggingPageIndex === index) return;
    e.preventDefault();
    item.classList.add("drag-over");
  });
  item.addEventListener("dragleave", () => item.classList.remove("drag-over"));
  item.addEventListener("drop", (e) => {
    item.classList.remove("drag-over");
    if (draggingPageIndex === null || draggingPageIndex === index) return;
    e.preventDefault();
    reorderPage(draggingPageIndex, index);
    draggingPageIndex = null;
  });
}

function renderPageRail() {
  const rail = $("#pageRail");
  if (!rail) return;
  rail.innerHTML = "";
  state.cfg.pages.forEach((p, i) => {
    const item = document.createElement("div");
    item.className = "page-rail-item" + (i === state.pageIndex ? " active" : "");
    item.draggable = true;
    const badgeHtml =
      i < 4
        ? `<span class="page-rail-badge" title="Reachable via the physical ${
            i === 0 ? "Circle" : `btn_${i}`
          } button">${PAGE_RAIL_HARDWARE_BADGES[i]}</span>`
        : `<span class="page-rail-badge page-rail-badge-muted" title="Not reachable by the physical page buttons — use agent.goto_page">&middot;</span>`;
    item.innerHTML = `${badgeHtml}<span class="page-rail-name"></span><button type="button" class="page-rail-delete" title="Remove page" aria-label="Remove page">✕</button>`;
    item.querySelector(".page-rail-name").textContent = p.name || `Page ${i + 1}`;
    item.addEventListener("click", (e) => {
      if (e.target.closest(".page-rail-delete")) return;
      selectPageIndex(i);
    });
    item.querySelector(".page-rail-delete").addEventListener("click", (e) => {
      e.stopPropagation();
      removePageAt(i);
    });
    wirePageRailDrag(item, i);
    rail.appendChild(item);
  });
}

/** Page rail: the hidden #pageSelect (page switch) and "+ Add page". */
export function wirePageSelect() {
  $("#pageSelect").addEventListener("change", () => {
    state.pageIndex = Number($("#pageSelect").value);
    muteAgentPagePollBriefly();
    // Respond immediately from the client's own state; the agent (and physical device) catch up
    // in the background. Never block the UI switch on this request's completion.
    void (async () => {
      try {
        await postAgentPageIndex(state.pageIndex);
      } catch (e) {
        $("#saveError").textContent = String(e);
      }
    })();
    renderDeck();
    renderPageRail();
    state.selectedControl = null;
    closeKnobEncoderEditor();
    const sl = $("#selLabel");
    if (sl) sl.textContent = "Select a control";
    syncTestPressButton();
  });

  $("#btnAddPage").addEventListener("click", addPage);
}

/** Page header: rename the current page. */
export function wirePageNameInput() {
  $("#pageNameInput").addEventListener("input", () => {
    currentPage().name = $("#pageNameInput").value;
    $("#pageName").textContent = currentPage().name || `Page ${state.pageIndex + 1}`;
    syncPageSelect();
    scheduleAutosave();
  });
}
