/*
 * util.js — Stateless helpers: $ (querySelector), HTML escaping, colour parsing, media/icon path
 * helpers.
 */

import { DECK_MEDIA_EXT, FONT_UPLOAD_EXT, SOUND_UPLOAD_EXT, VIDEO_EXT } from "./constants.js";

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

export function hasTactileGraphic(e) {
  if (!e) return false;
  const t = (e.text && String(e.text).trim()) || (e.label && String(e.label).trim());
  return !!(e.image || e.icon || t || e.background || e.background_gradient_from || mediaPathForEntry(e));
}

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

export function extOfPath(p) {
  const s = String(p || "").trim().toLowerCase();
  const base = s.split("?")[0].split("#")[0];
  const i = base.lastIndexOf(".");
  if (i < 0) return "";
  return base.slice(i);
}

export function mediaPathForEntry(entry) {
  if (!entry || typeof entry !== "object") return null;
  const pick = (raw) => {
    const s = raw && String(raw).trim();
    if (!s) return null;
    const ex = extOfPath(s);
    if (DECK_MEDIA_EXT.has(ex)) return s;
    return null;
  };
  const fromImg = pick(entry.image);
  if (fromImg) return fromImg;
  const ic = entry.icon && String(entry.icon).trim();
  if (ic && !isIconUri(ic)) {
    const fromIcon = pick(ic);
    if (fromIcon) return fromIcon;
  }
  const act0 =
    Array.isArray(entry.actions) &&
    entry.actions.length > 0 &&
    entry.actions[0] &&
    typeof entry.actions[0] === "object"
      ? entry.actions[0]
      : null;
  const act = entry.action && typeof entry.action === "object" ? entry.action : null;
  const overlay =
    act0 && act0.type === "overlay.show_media"
      ? act0
      : act && act.type === "overlay.show_media"
        ? act
        : null;
  if (overlay) {
    const p = (overlay.file || overlay.path) && String(overlay.file || overlay.path).trim();
    return pick(p);
  }
  return null;
}

export function localFileUrl(relPath) {
  return `/api/local-file?path=${encodeURIComponent(String(relPath || ""))}`;
}

function isIconUri(s) {
  const t = String(s || "").trim();
  return /^(si:|simpleicons:|heroicons:|lucide:|mdi:|https?:\/\/)/i.test(t);
}

export function splitIconAndImage(e) {
  let icon = (e && e.icon) || "";
  let image = (e && e.image) || "";
  if (!icon && image && isIconUri(image)) {
    icon = image;
    image = "";
  }
  return { icon, image };
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
