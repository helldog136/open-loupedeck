/*
 * deck.js — The deck picture (#deckRoot): Live / Live S chassis markup, key cells, server-rendered key
 * previews, media backgrounds, drag-and-drop key swap. Clicking a cell emits "control:open".
 */

import {
  BTNS_LIVE,
  BTNS_LIVE_S,
  DECK_MEDIA_EXT,
  KNOBS_LIVE,
  TOUCH_LIVE,
  TOUCH_LIVE_S,
  VIDEO_EXT,
} from "./constants.js";
import {
  currentPage,
  ensureDevice,
  ensurePages,
  getButtonEntry,
  isLiveSModel,
  knobPageLabelFromConfig,
  layoutMode,
  setButtonEntry,
  visualEntryForPreview,
} from "./model.js";
import { scheduleAutosave } from "./save.js";
import { emit, state } from "./state.js";
import { snapshotBeforeAction } from "./undo.js";
import {
  $,
  cssColorForLedPreview,
  escapeHtml,
  extOfPath,
  hasTactileGraphic,
  localFileUrl,
  mediaPathForEntry,
} from "./util.js";

/** Blob URLs for deck key previews (revoked on each re-render). */
const deckPreviewUrls = [];
/** Incremented each renderDeck; stale hydrateKeyPreviews completions are ignored. */
let deckPreviewGeneration = 0;

/** Media background controllers to stop on rerender. */
const deckMediaBgStops = [];

function revokeDeckPreviewUrls() {
  for (const u of deckPreviewUrls) URL.revokeObjectURL(u);
  deckPreviewUrls.length = 0;
}

function stopDeckMediaBackgrounds() {
  for (const stop of deckMediaBgStops.splice(0)) {
    try {
      stop();
    } catch {
      /* ignore */
    }
  }
}

function knobEncoderSummaryHtml(knobId) {
  const spec = state.cfg.knob_pages && state.cfg.knob_pages[knobId];
  const pages = spec && Array.isArray(spec.pages) ? spec.pages.filter((x) => x && typeof x === "object") : [];
  if (pages.length === 0) {
    return `<span class="knob-encoder-summary muted">No pages — click to configure</span>`;
  }
  const first = knobPageLabelFromConfig(pages[0]) || "(unnamed)";
  const extra = pages.length > 1 ? ` +${pages.length - 1} more` : "";
  return `<span class="knob-encoder-summary">${escapeHtml(first.slice(0, 28))}${escapeHtml(extra)}</span>`;
}

function knobEncoderCellHtml(knobId) {
  return `
    <div class="cell knob-encoder-cell knob-dial has-action" data-cid="${escapeHtml(knobId)}" title="${escapeHtml(
      knobId
    )} — dial pages">
      <div class="knob-dial-ring" aria-hidden="true"></div>
      <div class="knob-encoder-body">
        <span class="knob-encoder-id">${escapeHtml(knobId)}</span>
        ${knobEncoderSummaryHtml(knobId)}
      </div>
      <div class="cell-footer">
        <span class="cid">${escapeHtml(knobId)}</span>
        <span class="cell-act">dial pages</span>
      </div>
    </div>`;
}

function cellHtml(cid) {
  const e = getButtonEntry(cid);
  const err = typeof cid === "string" && cid.startsWith("touch_") && state.touchErrors && state.touchErrors[cid];
  const ledOnly =
    layoutMode() === "live_s" &&
    BTNS_LIVE_S.includes(cid) &&
    e &&
    e.button_color &&
    String(e.button_color).trim() &&
    !hasTactileGraphic(e);
  const has =
    e &&
    (e.action ||
      e.actions ||
      e.image ||
      e.icon ||
      e.text ||
      e.label ||
      e.background ||
      ledOnly);
  const label =
    (e &&
      Array.isArray(e.actions) &&
      e.actions.length > 0 &&
      e.actions[0] &&
      e.actions[0].type) ||
    (e && e.action && e.action.type) ||
    "";
  const pageTag =
    isLiveSModel() && BTNS_LIVE_S.includes(cid)
      ? `<span class="page-btn-tag" title="Switches touch page ${BTNS_LIVE_S.indexOf(cid) + 1}">P${
          BTNS_LIVE_S.indexOf(cid) + 1
        }</span>`
      : "";
  const showRaster = hasTactileGraphic(e) && !mediaPathForEntry(e);
  const swatch =
    layoutMode() === "live_s" && BTNS_LIVE_S.includes(cid) && e && e.button_color && String(e.button_color).trim()
      ? `<span class="btn-led-swatch" style="background-color:${escapeHtml(
          cssColorForLedPreview(e.button_color)
        )}" title="LED"></span>`
      : "";
  const swappable = typeof cid === "string" && cid.startsWith("touch_");
  return `
    <div class="cell ${has ? "has-action" : ""} ${err ? "error-outline" : ""}" data-cid="${cid}" ${
    swappable ? 'draggable="true"' : ""
  } title="${escapeHtml(err ? `${cid} — ${err}` : cid)}">
      ${
        showRaster
          ? `<img class="key-preview" data-cid="${escapeHtml(cid)}" alt="" hidden />`
          : ""
      }
      <div class="cell-footer">
        <span class="cid">${swatch}${escapeHtml(cid)}${pageTag}</span>
        ${label ? `<span class="cell-act">${escapeHtml(label)}</span>` : ""}
      </div>
    </div>`;
}

/** cid currently being dragged, or null when no drag is in progress. */
let draggingCid = null;

function swapButtonEntries(cidA, cidB) {
  if (!cidA || !cidB || cidA === cidB) return;
  snapshotBeforeAction();
  const entryA = getButtonEntry(cidA);
  const entryB = getButtonEntry(cidB);
  setButtonEntry(cidA, entryB);
  setButtonEntry(cidB, entryA);
  renderDeck();
  scheduleAutosave();
  if (state.selectedControl === cidA || state.selectedControl === cidB) {
    emit("control:open", state.selectedControl);
  }
}

function bindCells() {
  document.querySelectorAll(".cell").forEach((el) => {
    el.addEventListener("click", () => {
      if (draggingCid) return; // a drop already fired the swap; ignore the trailing click
      emit("control:open", el.dataset.cid);
    });

    el.addEventListener("dragstart", (e) => {
      const cid = el.dataset.cid;
      if (!cid || !cid.startsWith("touch_")) {
        e.preventDefault();
        return;
      }
      draggingCid = cid;
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", cid);
      el.classList.add("dragging");
    });

    el.addEventListener("dragend", () => {
      draggingCid = null;
      el.classList.remove("dragging");
      document.querySelectorAll(".cell.drag-over").forEach((c) => c.classList.remove("drag-over"));
    });

    el.addEventListener("dragover", (e) => {
      const cid = el.dataset.cid;
      if (!draggingCid || !cid || !cid.startsWith("touch_") || cid === draggingCid) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      el.classList.add("drag-over");
    });

    el.addEventListener("dragleave", () => {
      el.classList.remove("drag-over");
    });

    el.addEventListener("drop", (e) => {
      const cid = el.dataset.cid;
      el.classList.remove("drag-over");
      if (!draggingCid || !cid || !cid.startsWith("touch_") || cid === draggingCid) return;
      e.preventDefault();
      const source = draggingCid;
      draggingCid = null;
      swapButtonEntries(source, cid);
    });
  });
}

async function hydrateKeyPreviews(expectedGen) {
  const imgs = document.querySelectorAll("img.key-preview");
  await Promise.all(
    Array.from(imgs).map(async (img) => {
      if (expectedGen !== deckPreviewGeneration) return;
      const cid = img.dataset.cid;
      const e = getButtonEntry(cid);
      if (!hasTactileGraphic(e)) {
        img.removeAttribute("src");
        img.hidden = true;
        return;
      }
      try {
        const r = await fetch("/api/preview_key", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            entry: visualEntryForPreview(e),
            control_id: cid,
          }),
        });
        if (expectedGen !== deckPreviewGeneration) return;
        if (!r.ok) {
          img.hidden = true;
          return;
        }
        const blob = await r.blob();
        if (expectedGen !== deckPreviewGeneration) return;
        const url = URL.createObjectURL(blob);
        deckPreviewUrls.push(url);
        img.src = url;
        img.hidden = false;
      } catch {
        if (expectedGen === deckPreviewGeneration) img.hidden = true;
      }
    })
  );
}

function hydrateMediaBackgrounds(expectedGen) {
  stopDeckMediaBackgrounds();
  const cells = document.querySelectorAll(".cell");
  for (const cell of Array.from(cells)) {
    if (expectedGen !== deckPreviewGeneration) return;
    const cid = cell.dataset && cell.dataset.cid;
    if (!cid || typeof cid !== "string") continue;
    const mediaBgCell =
      cid.startsWith("touch_") ||
      cid === "strip_left" ||
      cid === "strip_right" ||
      cid.startsWith("btn_");
    if (!mediaBgCell) continue;
    const e = getButtonEntry(cid);
    const rel = mediaPathForEntry(e);
    if (!rel) continue;
    const url = localFileUrl(rel);
    const ex = extOfPath(rel);
    if (VIDEO_EXT.has(ex)) {
      const v = document.createElement("video");
      v.className = "media-bg";
      v.muted = true;
      v.loop = true;
      v.autoplay = true;
      v.playsInline = true;
      v.preload = "auto";
      v.src = url;
      v.playbackRate = 2.0;
      cell.prepend(v);
      const stop = () => {
        try {
          v.pause();
        } catch {
          /* ignore */
        }
        try {
          v.removeAttribute("src");
          v.load();
        } catch {
          /* ignore */
        }
        try {
          v.remove();
        } catch {
          /* ignore */
        }
      };
      deckMediaBgStops.push(stop);
      continue;
    }
    if (DECK_MEDIA_EXT.has(ex)) {
      const im = document.createElement("img");
      im.className = "media-bg";
      im.src = url;
      im.alt = "";
      im.draggable = false;
      cell.prepend(im);
      deckMediaBgStops.push(() => {
        try {
          im.remove();
        } catch {
          /* ignore */
        }
      });
    }
  }
}

export function renderDeck() {
  deckPreviewGeneration += 1;
  const previewGen = deckPreviewGeneration;
  ensurePages();
  ensureDevice();
  $("#pageName").textContent = currentPage().name || `Page ${state.pageIndex + 1}`;
  const pn = $("#pageNameInput");
  if (pn) pn.value = currentPage().name || "";

  const mode = layoutMode();
  const root = $("#deckRoot");
  if (!root) return;

  if (mode === "live_s") {
    const np = state.cfg.pages && state.cfg.pages.length ? state.cfg.pages.length : 1;
    root.innerHTML = `
      <div class="deck-chassis deck-chassis--live-s">
        <p class="deck-subtitle">Live S · ${np} touch page${np === 1 ? "" : "s"} · <span class="deck-subtitle-hint">Circle + btn 1–3 → indices 0–3 only</span></p>
        <div class="live-s-wrap">
          <div class="live-s-left deck-side-rail">
            <span class="deck-region-label">Encoders</span>
            ${["knobTL", "knobCL"]
              .map(
                (k) =>
                  `<div class="knob-block"><span class="knob-block-label">${escapeHtml(k)}</span>${knobEncoderCellHtml(k)}</div>`
              )
              .join("")}
            <div class="knob-block knob-block--btn">
              <span class="knob-block-label">Page</span>
              ${cellHtml("btn_circle")}
            </div>
          </div>
          <div class="live-s-center">
            <span class="deck-region-label">Touch screen</span>
            <div class="touch-screen">
              <div class="touch-grid touch-grid-5">${TOUCH_LIVE_S.map((c) => cellHtml(c)).join("")}</div>
            </div>
          </div>
          <div class="live-s-right deck-side-rail deck-side-rail--btns">
            <span class="deck-region-label">Keys</span>
            ${["btn_1", "btn_2", "btn_3"].map((c) => cellHtml(c)).join("")}
          </div>
        </div>
      </div>`;
  } else {
    root.innerHTML = `
      <div class="deck-chassis deck-chassis--live">
        <p class="deck-subtitle">Loupedeck Live · strips · 4×3 touch · row + circle</p>
        <div class="deck-grid">
          <div class="strip strip--side">
            <span class="deck-region-label">Left</span>
            <div id="stripLeft" class="strip-touch">${cellHtml("strip_left")}</div>
            <div class="knob-col">${KNOBS_LIVE.slice(0, 3).map((k) => `<div class="knob-slot"><span class="knob-block-label">${k}</span>${knobEncoderCellHtml(k)}</div>`).join("")}</div>
          </div>
          <div class="center-block">
            <span class="deck-region-label">Touch screen</span>
            <div class="touch-screen touch-screen--live">
              <div class="touch-grid touch-grid-4">${TOUCH_LIVE.map((c) => cellHtml(c)).join("")}</div>
            </div>
            <span class="deck-region-label deck-region-label--row">Hardware buttons</span>
            <div class="row-btns">${BTNS_LIVE.map((c) => cellHtml(c)).join("")}</div>
          </div>
          <div class="strip strip--side">
            <span class="deck-region-label">Right</span>
            <div id="stripRight" class="strip-touch">${cellHtml("strip_right")}</div>
            <div class="knob-col">${KNOBS_LIVE.slice(3, 6).map((k) => `<div class="knob-slot"><span class="knob-block-label">${k}</span>${knobEncoderCellHtml(k)}</div>`).join("")}</div>
          </div>
        </div>
      </div>`;
  }
  bindCells();
  revokeDeckPreviewUrls();
  stopDeckMediaBackgrounds();
  void hydrateKeyPreviews(previewGen);
  void hydrateMediaBackgrounds(previewGen);
}
