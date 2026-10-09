/*
 * inspector/look-fields.js — Key look form I/O (text, graphic, colours, font, gradients, animations,
 * Live S LED colour): read the form into an entry, fill it from an entry. No preview, no saving.
 */

import { BTNS_LIVE_S } from "../constants.js";
import { isLiveSPageSwitchButton, isLiveSPhysicalButton } from "../model.js";
import { state } from "../state.js";
import { $, sanitizeButtonColorHex, splitIconAndImage } from "../util.js";

export function syncLiveSButtonColorBlock(cid, e) {
  const block = $("#liveSButtonColorBlock");
  const picker = $("#buttonColorPicker");
  const hex = $("#buttonColorHex");
  const lab = $("#liveSButtonColorLabel");
  if (!block || !picker || !hex) return;
  if (!isLiveSPhysicalButton(cid)) {
    block.hidden = true;
    return;
  }
  block.hidden = false;
  if (lab && isLiveSPageSwitchButton(cid)) {
    const n = BTNS_LIVE_S.indexOf(cid) + 1;
    lab.textContent = `Page ${n} button — LED color`;
  } else if (lab) {
    lab.textContent = "Physical button LED (Live S)";
  }
  const raw = (e && e.button_color && String(e.button_color).trim()) || "";
  if (!raw) {
    picker.value = "#202028";
    hex.value = "#202028";
    return;
  }
  const hexOk = sanitizeButtonColorHex(raw);
  if (hexOk) {
    picker.value = hexOk;
    hex.value = hexOk;
  } else {
    hex.value = raw;
    picker.value = "#808080";
  }
}

export const DESIGN_COLOR_PAIRS = [
  ["#textColorPicker", "#textColor"],
  ["#backgroundColorPicker", "#backgroundColor"],
  ["#textGradientFromPicker", "#textGradientFrom"],
  ["#textGradientToPicker", "#textGradientTo"],
  ["#backgroundGradientFromPicker", "#backgroundGradientFrom"],
  ["#backgroundGradientToPicker", "#backgroundGradientTo"],
  ["#pressFlashColorPicker", "#pressFlashColor"],
];

export function syncDesignAnimationFieldVisibility() {
  const idleType = ($("#idleAnimation") && $("#idleAnimation").value) || "none";
  const speedRow = $("#idleAnimationSpeedRow");
  if (speedRow) speedRow.hidden = idleType === "none";

  const pressType = ($("#pressAnimation") && $("#pressAnimation").value) || "none";
  const dirRow = $("#pressAnimationDirectionRow");
  if (dirRow) dirRow.hidden = pressType !== "slide_reappear";
  const flashRow = $("#pressFlashColorRow");
  if (flashRow) flashRow.hidden = pressType !== "flash";
}

// Reads the gradient/idle/press fields from the form into `target` (mutated and returned).
// Shared by draftVisualEntryFromForm() (live preview) and saveAction() (persisted config).
export function readDesignFieldsFromForm(target) {
  const tgFrom = ($("#textGradientFrom") && $("#textGradientFrom").value.trim()) || "";
  const tgTo = ($("#textGradientTo") && $("#textGradientTo").value.trim()) || "";
  if (tgFrom && tgTo) {
    target.text_gradient_from = tgFrom;
    target.text_gradient_to = tgTo;
    const angle = ($("#textGradientAngle") && $("#textGradientAngle").value.trim()) || "";
    if (angle) target.text_gradient_angle = Number(angle);
  }

  const bgFrom = ($("#backgroundGradientFrom") && $("#backgroundGradientFrom").value.trim()) || "";
  const bgTo = ($("#backgroundGradientTo") && $("#backgroundGradientTo").value.trim()) || "";
  if (bgFrom && bgTo) {
    target.background_gradient_from = bgFrom;
    target.background_gradient_to = bgTo;
    const angle = ($("#backgroundGradientAngle") && $("#backgroundGradientAngle").value.trim()) || "";
    if (angle) target.background_gradient_angle = Number(angle);
  }

  const idleType = ($("#idleAnimation") && $("#idleAnimation").value) || "none";
  if (idleType !== "none") {
    target.idle_animation = idleType;
    const speed = ($("#idleAnimationSpeed") && $("#idleAnimationSpeed").value.trim()) || "";
    if (speed) target.idle_animation_speed = Number(speed);
  }

  const pressType = ($("#pressAnimation") && $("#pressAnimation").value) || "none";
  if (pressType !== "none") {
    target.press_animation = pressType;
    if (pressType === "slide_reappear") {
      const dir = ($("#pressAnimationDirection") && $("#pressAnimationDirection").value) || "left";
      if (dir !== "left") target.press_animation_direction = dir;
    }
    if (pressType === "flash") {
      const col = ($("#pressFlashColor") && $("#pressFlashColor").value.trim()) || "";
      if (col) target.press_flash_color = col;
    }
  }
  return target;
}

// Populates the design-section form fields from a stored/loaded button entry (mirror of
// readDesignFieldsFromForm). Pass {} to reset to defaults (e.g. Live S page-switch buttons).
export function populateDesignFieldsFromEntry(e) {
  const ent = e || {};
  const setVal = (id, v) => {
    const el = $(id);
    if (el) el.value = v;
  };
  setVal("#textGradientFrom", ent.text_gradient_from || "");
  setVal("#textGradientTo", ent.text_gradient_to || "");
  setVal("#textGradientAngle", ent.text_gradient_angle != null ? String(ent.text_gradient_angle) : "");
  setVal("#backgroundGradientFrom", ent.background_gradient_from || "");
  setVal("#backgroundGradientTo", ent.background_gradient_to || "");
  setVal(
    "#backgroundGradientAngle",
    ent.background_gradient_angle != null ? String(ent.background_gradient_angle) : "",
  );
  setVal("#idleAnimation", ent.idle_animation || "none");
  setVal("#idleAnimationSpeed", ent.idle_animation_speed != null ? String(ent.idle_animation_speed) : "");
  setVal("#pressAnimation", ent.press_animation || "none");
  setVal("#pressAnimationDirection", ent.press_animation_direction || "left");
  setVal("#pressFlashColor", ent.press_flash_color || "");
  for (const [pickerId, hexId] of DESIGN_COLOR_PAIRS) {
    const hex = $(hexId);
    const picker = $(pickerId);
    if (!hex || !picker) continue;
    const s = sanitizeButtonColorHex(hex.value);
    picker.value = s || "#808080";
  }
  syncDesignAnimationFieldVisibility();
}

export function draftVisualEntryFromForm() {
  if (state.selectedControl && isLiveSPageSwitchButton(state.selectedControl)) {
    const e = {};
    const raw = ($("#buttonColorHex") && $("#buttonColorHex").value.trim()) || "";
    if (raw) {
      const bc = sanitizeButtonColorHex(raw);
      e.button_color = bc || raw;
    }
    return e;
  }
  const e = {};
  const txt = ($("#buttonText") && $("#buttonText").value.trim()) || "";
  if (txt) e.text = txt;
  const icon = ($("#iconUri") && $("#iconUri").value.trim()) || "";
  const img = ($("#imagePath") && $("#imagePath").value.trim()) || "";
  if (icon) e.icon = icon;
  if (img) e.image = img;
  const tc = $("#textColor") && $("#textColor").value.trim();
  if (tc) e.text_color = tc;
  const bg = $("#backgroundColor") && $("#backgroundColor").value.trim();
  if (bg) e.background = bg;
  const fs = $("#fontSize") && $("#fontSize").value.trim();
  if (fs) e.font_size = Number(fs);
  const ff = ($("#fontFilePath") && $("#fontFilePath").value.trim()) || "";
  if (ff) e.font_file = ff;
  const hasG = !!(icon || img);
  const hasT = !!txt;
  if (hasG && hasT) {
    const lo = $("#graphicTextLayout");
    e.graphic_text_layout = (lo && lo.value) || "split";
  }
  if (state.selectedControl && isLiveSPhysicalButton(state.selectedControl) && !isLiveSPageSwitchButton(state.selectedControl)) {
    const hx = $("#buttonColorHex");
    const raw = hx && hx.value.trim();
    if (raw) {
      const bc = sanitizeButtonColorHex(raw);
      e.button_color = bc || raw;
    }
  }
  readDesignFieldsFromForm(e);
  return e;
}

export function syncGraphicLayoutVisibility() {
  const block = $("#graphicLayoutBlock");
  if (!block) return;
  const icon = ($("#iconUri") && $("#iconUri").value.trim()) || "";
  const img = ($("#imagePath") && $("#imagePath").value.trim()) || "";
  const txt = ($("#buttonText") && $("#buttonText").value.trim()) || "";
  block.hidden = !(txt && (icon || img));
}

/** Fill the text/graphic/colour/font/design fields of the key editor from a stored entry. */
export function fillLookFieldsFromEntry(e) {
  const { icon, image } = splitIconAndImage(e);
  $("#iconUri").value = icon;
  $("#imagePath").value = image;
  $("#buttonText").value = e.text || e.label || "";
  $("#textColor").value = e.text_color || "";
  $("#backgroundColor").value = e.background || "";
  $("#fontSize").value = e.font_size != null && e.font_size !== "" ? String(e.font_size) : "";
  const ffp = $("#fontFilePath");
  if (ffp) ffp.value = e.font_file != null && e.font_file !== "" ? String(e.font_file) : "";
  const gl = $("#graphicTextLayout");
  if (gl) {
    const v = String(e.graphic_text_layout || "split").toLowerCase();
    const overlayish = ["overlay", "overlap", "on_graphic", "stacked_on_graphic", "center"];
    gl.value = overlayish.includes(v) ? "overlay" : "split";
  }
  populateDesignFieldsFromEntry(e);
}
