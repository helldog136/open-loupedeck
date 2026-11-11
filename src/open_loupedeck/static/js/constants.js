/*
 * constants.js — The file-extension sets used to classify uploads (control ids come from the device
 * model, see model.js).
 */

export const VIDEO_EXT = new Set([".mp4", ".webm", ".mov", ".m4v", ".ogv", ".avi", ".mkv"]);
export const SOUND_UPLOAD_EXT = new Set([".wav", ".mp3", ".ogg", ".flac", ".m4a", ".opus", ".aac"]);
export const FONT_UPLOAD_EXT = new Set([".ttf", ".otf", ".ttc"]);
