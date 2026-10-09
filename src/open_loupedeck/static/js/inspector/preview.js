/*
 * inspector/preview.js — Live key preview in the inspector (POST /api/preview_key), idle/press
 * animation playback, and the look-field listeners that refresh it.
 */

import {
  DESIGN_COLOR_PAIRS,
  draftVisualEntryFromForm,
  syncDesignAnimationFieldVisibility,
  syncGraphicLayoutVisibility,
} from "./look-fields.js";
import { hasRenderableVisual, isLiveSPhysicalButton, visualEntryForPreview } from "../model.js";
import { state } from "../state.js";
import { $, cssColorForLedPreview, escapeHtml, hasTactileGraphic, sanitizeButtonColorHex } from "../util.js";

let sidebarPreviewUrl = null;

export function wireButtonColorInputs() {
  const picker = $("#buttonColorPicker");
  const hex = $("#buttonColorHex");
  if (!picker || !hex) return;
  picker.addEventListener("input", () => {
    hex.value = picker.value;
    scheduleSidebarPreviewRefresh();
  });
  hex.addEventListener("input", () => {
    const s = sanitizeButtonColorHex(hex.value);
    if (s) picker.value = s;
    scheduleSidebarPreviewRefresh();
  });
}

// Pairs a native <input type="color"> swatch with a free-text hex field: either one can drive
// the other, and both changes refresh the live sidebar preview (design section: text/background
// solid colors and gradient endpoints).
function wireColorPairInputs(pickerId, hexId) {
  const picker = $(pickerId);
  const hex = $(hexId);
  if (!picker || !hex) return;
  picker.addEventListener("input", () => {
    hex.value = picker.value;
    scheduleSidebarPreviewRefresh();
  });
  hex.addEventListener("input", () => {
    const s = sanitizeButtonColorHex(hex.value);
    if (s) picker.value = s;
    scheduleSidebarPreviewRefresh();
  });
}

export function wireDesignFieldInputs() {
  for (const [pickerId, hexId] of DESIGN_COLOR_PAIRS) wireColorPairInputs(pickerId, hexId);

  const plainInputIds = ["#textGradientAngle", "#backgroundGradientAngle", "#idleAnimationSpeed"];
  for (const id of plainInputIds) {
    const el = $(id);
    if (el) el.addEventListener("input", () => scheduleSidebarPreviewRefresh());
  }

  const idleSel = $("#idleAnimation");
  if (idleSel) {
    idleSel.addEventListener("change", () => {
      syncDesignAnimationFieldVisibility();
      scheduleSidebarPreviewRefresh();
    });
  }
  const pressSel = $("#pressAnimation");
  if (pressSel) {
    pressSel.addEventListener("change", () => {
      syncDesignAnimationFieldVisibility();
      scheduleSidebarPreviewRefresh();
    });
  }
  const pressDirSel = $("#pressAnimationDirection");
  if (pressDirSel) pressDirSel.addEventListener("change", () => scheduleSidebarPreviewRefresh());

  const btnPreviewPress = $("#btnPreviewPress");
  if (btnPreviewPress) btnPreviewPress.addEventListener("click", () => void previewPressAnimation());
}

let sidebarPreviewDebounce = null;

export function scheduleSidebarPreviewRefresh() {
  if (!state.selectedControl) return;
  clearTimeout(sidebarPreviewDebounce);
  sidebarPreviewDebounce = setTimeout(() => {
    syncGraphicLayoutVisibility();
    const draft = draftVisualEntryFromForm();
    void updatePreviewFromEntry(draft, state.selectedControl);
    maybeStartSidebarAnimPreview(draft, state.selectedControl);
  }, 320);
}

function revokeSidebarPreview() {
  if (sidebarPreviewUrl) {
    URL.revokeObjectURL(sidebarPreviewUrl);
    sidebarPreviewUrl = null;
  }
}

export async function updatePreviewFromEntry(e, cid, animOpts) {
  const prev = $("#preview");
  if (!prev) return;
  revokeSidebarPreview();
  if (!hasRenderableVisual(e)) {
    prev.innerHTML = "";
    return;
  }
  if (cid && isLiveSPhysicalButton(cid) && !hasTactileGraphic(e)) {
    const raw = ((e && e.button_color) || "").trim();
    const css = cssColorForLedPreview(raw || "#202028");
    prev.innerHTML = `<div class="preview led-preview" style="background-color:${escapeHtml(css)}"></div>`;
    return;
  }
  try {
    const body = {
      entry: visualEntryForPreview(e),
      control_id: cid || "touch_0",
    };
    if (animOpts && animOpts.animationFrame != null) body.animation_frame = animOpts.animationFrame;
    if (animOpts && animOpts.pressElapsedFrames != null) body.press_elapsed_frames = animOpts.pressElapsedFrames;
    const r = await fetch("/api/preview_key", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (r.status === 404) {
      prev.innerHTML = "";
      return;
    }
    if (!r.ok) {
      prev.innerHTML = `<p class="error">${escapeHtml(await r.text())}</p>`;
      return;
    }
    const blob = await r.blob();
    sidebarPreviewUrl = URL.createObjectURL(blob);
    prev.innerHTML = `<img class="preview" src="${sidebarPreviewUrl}" alt="Key preview (matches device)"/>`;
  } catch (err) {
    prev.innerHTML = `<p class="error">${escapeHtml(String(err))}</p>`;
  }
}

// Live idle-animation preview: while the open control has idle_animation set, keep re-fetching
// the preview with an advancing frame counter so the config UI actually shows the loop, not just
// a static snapshot (the "previewable" half of the project's text-on-key design rule).
let sidebarAnimPreviewTimer = null;
let sidebarAnimPreviewFrame = 0;

export function stopSidebarAnimPreview() {
  if (sidebarAnimPreviewTimer) {
    clearInterval(sidebarAnimPreviewTimer);
    sidebarAnimPreviewTimer = null;
  }
}

export function maybeStartSidebarAnimPreview(entry, cid) {
  stopSidebarAnimPreview();
  const idleType = (entry && entry.idle_animation) || "none";
  if (idleType === "none") return;
  sidebarAnimPreviewFrame = 0;
  sidebarAnimPreviewTimer = setInterval(() => {
    sidebarAnimPreviewFrame += 1;
    void updatePreviewFromEntry(entry, cid, { animationFrame: sidebarAnimPreviewFrame });
  }, 100);
}

// Must mirror button_render.py's PRESS_ANIMATION_DURATION_TICKS / _PRESS_ANIMATION_DURATION_OVERRIDES.
const PRESS_ANIMATION_DURATION_TICKS = 4;
const PRESS_ANIMATION_DURATION_OVERRIDES = { slide_reappear: 8 };

async function previewPressAnimation() {
  if (!state.selectedControl) return;
  const draft = draftVisualEntryFromForm();
  const pressType = draft.press_animation || "none";
  if (pressType === "none") return;
  stopSidebarAnimPreview();
  const duration = PRESS_ANIMATION_DURATION_OVERRIDES[pressType] || PRESS_ANIMATION_DURATION_TICKS;
  for (let f = 0; f < duration; f++) {
    await updatePreviewFromEntry(draft, state.selectedControl, { pressElapsedFrames: f });
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  await updatePreviewFromEntry(draft, state.selectedControl);
  maybeStartSidebarAnimPreview(draft, state.selectedControl);
}

/** Key editor: look fields refresh the live preview while typing. */
export function wireSidebarPreviewInputs() {
  for (const id of [
    "buttonText",
    "iconUri",
    "imagePath",
    "textColor",
    "backgroundColor",
    "fontSize",
    "fontFilePath",
    "graphicTextLayout",
  ]) {
    const el = document.getElementById(id);
    if (!el) continue;
    el.addEventListener(el.tagName === "SELECT" ? "change" : "input", scheduleSidebarPreviewRefresh);
  }
}
