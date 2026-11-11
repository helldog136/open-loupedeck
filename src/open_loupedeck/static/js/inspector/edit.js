/*
 * inspector/edit.js — The one way the inspector changes a binding: snapshot for Undo, mutate a copy of
 * the entry in the scope being edited (this page or every page, model.js editScope), write it back (or
 * remove it when empty), redraw the deck and the page tabs, autosave, and redraw the device a moment
 * later. No Apply button: every change goes through here.
 */

import { refreshSkin } from "../api.js";
import { renderDeck } from "../deck.js";
import { getEntry, setEntry } from "../model.js";
import { refreshPageTabs } from "../pages.js";
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

/** After any binding change: deck, page tabs (a button may open a page), autosave, device. */
export function afterBindingChange() {
  renderDeck();
  refreshPageTabs();
  scheduleAutosave();
  scheduleDeviceRefresh();
}

/**
 * Change the entry of `cid` in its edited scope: `mutate(entry)` edits a copy (an empty object when
 * there is none). `typing: true` batches a burst of keystrokes into one Undo step (until the field
 * loses focus). `scope` forces "page" / "global". Returns the stored entry (null when it ended empty).
 */
export function editEntry(cid, mutate, { typing = false, scope } = {}) {
  if (!cid) return null;
  if (typing) snapshotBeforeEditOnce();
  else snapshotBeforeAction();
  const cur = getEntry(cid, scope);
  const draft = cur ? deepCloneJson(cur) : {};
  mutate(draft);
  setEntry(cid, pruneEntry(draft), scope);
  afterBindingChange();
  return getEntry(cid, scope);
}
