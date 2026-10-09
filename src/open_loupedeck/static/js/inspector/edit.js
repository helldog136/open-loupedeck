/*
 * inspector/edit.js — The one way the inspector changes a key: snapshot for Undo, mutate a copy of the
 * entry, write it back (or remove it when empty), redraw the deck, autosave, and redraw the device a
 * moment later. No Apply button: every change goes through here.
 */

import { refreshSkin } from "../api.js";
import { renderDeck } from "../deck.js";
import { getButtonEntry, setButtonEntry } from "../model.js";
import { flushAutosave, scheduleAutosave } from "../save.js";
import { snapshotBeforeAction, snapshotBeforeEditOnce } from "../undo.js";
import { deepCloneJson } from "../util.js";
import { pruneEntry } from "./entry.js";

let deviceTimer = null;

/** Push the saved config to the device shortly after the last change (debounced). */
export function scheduleDeviceRefresh(delay = 700) {
  clearTimeout(deviceTimer);
  deviceTimer = setTimeout(async () => {
    deviceTimer = null;
    try {
      if (await flushAutosave()) await refreshSkin();
    } catch {
      /* the save status line already reports save errors */
    }
  }, delay);
}

/**
 * Change the entry of `cid`: `mutate(entry)` edits a copy (an empty object for an empty key).
 * `typing: true` batches a burst of keystrokes into one Undo step (until the field loses focus).
 * Returns the stored entry (null when the key ended up empty).
 */
export function editEntry(cid, mutate, { typing = false } = {}) {
  if (!cid) return null;
  if (typing) snapshotBeforeEditOnce();
  else snapshotBeforeAction();
  const cur = getButtonEntry(cid);
  const draft = cur ? deepCloneJson(cur) : {};
  mutate(draft);
  setButtonEntry(cid, pruneEntry(draft));
  renderDeck();
  scheduleAutosave();
  scheduleDeviceRefresh();
  return getButtonEntry(cid);
}
