/*
 * constants.js — Device control ids per model and the file-extension sets used to classify
 * media/uploads.
 */

export const TOUCH_LIVE = Array.from({ length: 12 }, (_, i) => `touch_${i}`);
export const TOUCH_LIVE_S = Array.from({ length: 15 }, (_, i) => `touch_${i}`);
export const BTNS_LIVE = [...Array.from({ length: 7 }, (_, i) => `btn_${i + 1}`), "btn_circle"];
export const BTNS_LIVE_S = ["btn_circle", "btn_1", "btn_2", "btn_3"];
/** Loupedeck Live S: any number of touch pages; btn_circle + btn_1–btn_3 switch indices 0–3 on device (LED color only in UI). */
export const KNOBS_LIVE = ["knobTL", "knobCL", "knobBL", "knobTR", "knobCR", "knobBR"];
export const VIDEO_EXT = new Set([".mp4", ".webm", ".mov", ".m4v", ".ogv", ".avi", ".mkv"]);
export const SOUND_UPLOAD_EXT = new Set([".wav", ".mp3", ".ogg", ".flac", ".m4a", ".opus", ".aac"]);
export const FONT_UPLOAD_EXT = new Set([".ttf", ".otf", ".ttc"]);
/** GIF, static images, and video — key graphic or deck background */
export const DECK_MEDIA_EXT = new Set([
  ".gif",
  ".png",
  ".jpg",
  ".jpeg",
  ".webp",
  ...VIDEO_EXT,
]);
