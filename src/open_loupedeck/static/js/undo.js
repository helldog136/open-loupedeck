/*
 * undo.js — Session-only undo/redo of { cfg, pageIndex } snapshots (Ctrl+Z / Ctrl+Shift+Z). Restoring
 * a snapshot emits "config:replaced"; main.js re-syncs the views.
 */

import { emit, state } from "./state.js";
import { $ } from "./util.js";

// --- Undo/redo: client-side, session-only (cleared on page reload). ------------------------

const UNDO_STACK_MAX = 50;
const undoStack = [];
const redoStack = [];
/** True while a keystroke-driven edit session is "open" (since the field was focused) — batches
 * an entire typing burst into a single undo step instead of one per keystroke. Reset on focusout. */
let undoSnapshotPendingForFocus = false;
/** True while applying an undo/redo snapshot, so that doing so does not itself get pushed. */
let applyingUndoRedo = false;

/** Header "Undo" button: enabled only when there is something to undo. */
export function syncUndoButton() {
  const btn = $("#btnUndo");
  if (btn) btn.disabled = undoStack.length === 0;
}

function pushUndoSnapshot() {
  if (applyingUndoRedo) return;
  try {
    undoStack.push(JSON.stringify({ cfg: state.cfg, pageIndex: state.pageIndex }));
  } catch {
    return;
  }
  if (undoStack.length > UNDO_STACK_MAX) undoStack.shift();
  redoStack.length = 0;
  syncUndoButton();
}

/** Use for discrete one-shot actions (click a button, drop a drag) — always pushes. */
export function snapshotBeforeAction() {
  pushUndoSnapshot();
  undoSnapshotPendingForFocus = false;
}

/** Use inside keystroke-driven "input"/"change" handlers — pushes once per focus session. */
export function snapshotBeforeEditOnce() {
  if (undoSnapshotPendingForFocus) return;
  pushUndoSnapshot();
  undoSnapshotPendingForFocus = true;
}

export function applyCfgSnapshot(json) {
  const prevPageIndex = state.pageIndex;
  applyingUndoRedo = true;
  try {
    const parsed = JSON.parse(json);
    state.cfg = parsed.cfg;
    state.pageIndex = parsed.pageIndex;
  } finally {
    applyingUndoRedo = false;
  }
  emit("config:replaced", prevPageIndex);
}

function currentUndoSnapshot() {
  return JSON.stringify({ cfg: state.cfg, pageIndex: state.pageIndex });
}

export function undo() {
  if (undoStack.length === 0) return;
  const current = currentUndoSnapshot();
  const snapshot = undoStack.pop();
  redoStack.push(current);
  applyCfgSnapshot(snapshot);
  syncUndoButton();
}

export function redo() {
  if (redoStack.length === 0) return;
  const current = currentUndoSnapshot();
  const snapshot = redoStack.pop();
  undoStack.push(current);
  applyCfgSnapshot(snapshot);
  syncUndoButton();
}

export function wireUndoRedoKeyboard() {
  const btn = $("#btnUndo");
  if (btn) btn.addEventListener("click", undo);
  syncUndoButton();
  document.addEventListener("keydown", (e) => {
    if (!(e.ctrlKey || e.metaKey) || e.key.toLowerCase() !== "z") return;
    e.preventDefault();
    if (e.shiftKey) redo();
    else undo();
  });
  // Any field losing focus ends the current keystroke-batching session.
  document.addEventListener(
    "focusout",
    () => {
      undoSnapshotPendingForFocus = false;
    },
    true,
  );
}
