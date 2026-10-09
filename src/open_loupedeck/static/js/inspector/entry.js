/*
 * inspector/entry.js — DOM-free helpers for one key's config entry, as the inspector edits it: which
 * look fields are stored ("modified") or follow the action ("proposed"), resetting them, reading and
 * replacing the key's action, and dropping an entry that no longer holds anything.
 *
 * Stored-config contract (mirrors look_defaults.resolve_look): a look field is *modified* when one of
 * its keys is set in the entry, otherwise it is *proposed* by the action's default look.
 *   label -> text (or legacy label)     icon -> icon (or image)      mode -> mode (text|icon|both)
 *   bg    -> background (or both background_gradient_from/_to)
 *   fg    -> text_color (or both text_gradient_from/_to)
 */

export const MODES = ["text", "both", "icon"];
export const LOOK_FIELD_NAMES = ["label", "icon", "bg", "fg", "mode"];

/** Keys removed when a look field is reset to the proposed value. */
const FIELD_KEYS = {
  label: ["text", "label"],
  icon: ["icon", "image"],
  bg: ["background", "background_gradient_from", "background_gradient_to", "background_gradient_angle"],
  fg: ["text_color", "text_gradient_from", "text_gradient_to", "text_gradient_angle"],
  mode: ["mode"],
};

const filled = (v) => v != null && String(v).trim() !== "";

/** True when the entry stores the look field (it no longer follows the action). */
export function isFieldModified(entry, field) {
  const e = entry || {};
  switch (field) {
    case "label":
      return filled(e.text) || filled(e.label);
    case "icon":
      return filled(e.icon) || filled(e.image);
    case "bg":
      return filled(e.background) || (filled(e.background_gradient_from) && filled(e.background_gradient_to));
    case "fg":
      return filled(e.text_color) || (filled(e.text_gradient_from) && filled(e.text_gradient_to));
    case "mode":
      return MODES.includes(String(e.mode || "").trim().toLowerCase());
    default:
      return false;
  }
}

export function modifiedFields(entry) {
  return LOOK_FIELD_NAMES.filter((f) => isFieldModified(entry, f));
}

/** Remove the field's keys from `entry` (mutated) so it follows the action again. */
export function resetField(entry, field) {
  for (const k of FIELD_KEYS[field] || []) delete entry[k];
  return entry;
}

export function resetAllLook(entry) {
  for (const f of LOOK_FIELD_NAMES) resetField(entry, f);
  return entry;
}

/** The key's (first) action object, or null. */
export function entryAction(entry) {
  if (!entry) return null;
  if (Array.isArray(entry.actions) && entry.actions.length && entry.actions[0] && typeof entry.actions[0] === "object") {
    return entry.actions[0];
  }
  return entry.action && typeof entry.action === "object" ? entry.action : null;
}

/** Replace the key's (first) action in `entry` (mutated); null removes it. Extra chained actions are kept. */
export function setEntryAction(entry, action) {
  if (Array.isArray(entry.actions) && entry.actions.length) {
    if (action) entry.actions[0] = action;
    else entry.actions.shift();
    if (!entry.actions.length) delete entry.actions;
    return entry;
  }
  if (action) entry.action = action;
  else delete entry.action;
  return entry;
}

/** Null when nothing meaningful is left in the entry (so the key is removed from the config). */
export function pruneEntry(entry) {
  if (!entry || typeof entry !== "object") return null;
  for (const [k, v] of Object.entries(entry)) {
    if (v == null || (typeof v === "string" && v.trim() === "")) delete entry[k];
  }
  return Object.keys(entry).length ? entry : null;
}

/** Live-key info of a catalog spec: { offlineBg, offlineFg } or null. */
export function liveInfo(spec) {
  const live = spec && spec.default_look && spec.default_look.live;
  return live ? { offlineBg: live.offline_bg, offlineFg: live.offline_fg } : null;
}

/** Live keys whose source can be offline (the clock is always available). */
export function hasOfflineState(type) {
  return type !== "display.clock";
}

/** Live keys whose runtime honours the `offline_fallback` action param (see live_message.py). */
export const OFFLINE_FALLBACK_TYPES = new Set(["display.obs_scene"]);
export const OFFLINE_FALLBACKS = ["dash", "none", "last"];
