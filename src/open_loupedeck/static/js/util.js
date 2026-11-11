/*
 * util.js — Stateless helpers: $ (querySelector), HTML escaping, colour parsing, upload library
 * of a file.
 */

import { FONT_UPLOAD_EXT, SOUND_UPLOAD_EXT, VIDEO_EXT } from "./constants.js";

/** Target ``library`` for POST /api/upload from a chosen File (extension-based). */
export function uploadLibraryParamForFile(file) {
  if (!file || !file.name) return "images";
  const low = file.name.toLowerCase();
  const dot = low.lastIndexOf(".");
  const ext = dot >= 0 ? low.slice(dot) : "";
  if (VIDEO_EXT.has(ext)) return "videos";
  if (SOUND_UPLOAD_EXT.has(ext)) return "sounds";
  if (FONT_UPLOAD_EXT.has(ext)) return "fonts";
  return "images";
}

export const $ = (s) => document.querySelector(s);

/** Normalize to #rrggbb or return "". */
export function sanitizeButtonColorHex(s) {
  const t = String(s || "").trim();
  if (/^#[0-9A-Fa-f]{6}$/i.test(t)) return `#${t.slice(1).toLowerCase()}`;
  if (/^#[0-9A-Fa-f]{3}$/i.test(t)) {
    const r = t[1],
      g = t[2],
      b = t[3];
    return `#${r}${r}${g}${g}${b}${b}`.toLowerCase();
  }
  return "";
}

function normalizeHex6ForPicker(s) {
  const x = sanitizeButtonColorHex(s);
  return x || "#202028";
}

/** Safe CSS color for LED preview (hex or simple named color). */
export function cssColorForLedPreview(raw) {
  const s = String(raw || "").trim();
  if (!s) return "#555555";
  const h = sanitizeButtonColorHex(s);
  if (h) return h;
  if (/^[a-zA-Z][a-zA-Z0-9]*$/.test(s)) return s;
  return "#555555";
}

export function escapeAttr(s) {
  return escapeHtml(String(s || "")).replace(/\"/g, "&quot;");
}

export function deepCloneJson(v) {
  return v == null ? null : JSON.parse(JSON.stringify(v));
}

export function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}
