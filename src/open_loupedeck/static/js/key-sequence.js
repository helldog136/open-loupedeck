/*
 * key-sequence.js — keyboard.play_sequence "record" widget: captures keystrokes in the browser into an
 * ordered steps list.
 */

/* ---------------------------------------------------------------------------------------------
 * keyboard.play_sequence: "record" widget (keys/key_sequence field).
 *
 * Recording is done entirely in the browser — a document-level keydown listener, installed once,
 * captures real keystrokes while at most one widget instance is "active". Replay (actually
 * sending the keys to the OS) is the agent's job (keyboard_replay.py); this only builds the
 * ordered `steps` list that gets saved as the action's params.
 * ------------------------------------------------------------------------------------------- */

let activeKeySequenceRecorder = null; // { wrapEl, hiddenEl, chipsEl, recordBtn, timeoutId }
let keySequenceGlobalListenerInstalled = false;

export function keySequenceStepsFromHidden(hiddenEl) {
  try {
    const v = JSON.parse((hiddenEl && hiddenEl.value) || "[]");
    return Array.isArray(v) ? v : [];
  } catch {
    return [];
  }
}

const KEY_DISPLAY_NAMES = {
  ctrl: "Ctrl",
  alt: "Alt",
  shift: "Shift",
  meta: "Win/⌘",
  tab: "Tab",
  enter: "Enter",
  escape: "Esc",
  esc: "Esc",
  " ": "Space",
  space: "Space",
  arrowup: "↑",
  arrowdown: "↓",
  arrowleft: "←",
  arrowright: "→",
  backspace: "⌫",
  delete: "Del",
};

function keyDisplayName(k) {
  const s = String(k);
  const lower = s.toLowerCase();
  if (KEY_DISPLAY_NAMES[lower]) return KEY_DISPLAY_NAMES[lower];
  return s.length === 1 ? s.toUpperCase() : s;
}

export function renderKeySequenceChips(chipsEl, hiddenEl) {
  if (!chipsEl) return;
  const steps = keySequenceStepsFromHidden(hiddenEl);
  chipsEl.innerHTML = "";
  if (steps.length === 0) {
    const empty = document.createElement("span");
    empty.className = "key-sequence-empty";
    empty.textContent = "No keys recorded yet";
    chipsEl.appendChild(empty);
    return;
  }
  steps.forEach((step, i) => {
    const chip = document.createElement("span");
    chip.className = "key-chip";
    const keys = (step && step.keys) || [];
    chip.appendChild(document.createTextNode(keys.map(keyDisplayName).join("+") || "?"));
    const rm = document.createElement("button");
    rm.type = "button";
    rm.className = "key-chip-remove";
    rm.textContent = "×";
    rm.title = "Remove this key";
    rm.addEventListener("click", () => {
      const cur = keySequenceStepsFromHidden(hiddenEl);
      cur.splice(i, 1);
      hiddenEl.value = JSON.stringify(cur);
      renderKeySequenceChips(chipsEl, hiddenEl);
      hiddenEl.dispatchEvent(new Event("input", { bubbles: true }));
    });
    chip.appendChild(rm);
    chipsEl.appendChild(chip);
  });
}

export function stopKeySequenceRecording() {
  const rec = activeKeySequenceRecorder;
  if (!rec) return;
  activeKeySequenceRecorder = null;
  if (rec.timeoutId) clearTimeout(rec.timeoutId);
  if (rec.wrapEl) rec.wrapEl.classList.remove("recording");
  if (rec.recordBtn) rec.recordBtn.textContent = "● Record";
}

// Safety net: recording left on by accident (e.g. the user wandered off without clicking Stop)
// must not keep intercepting every keystroke on the page forever.
const KEY_SEQUENCE_RECORD_TIMEOUT_MS = 60000;
const KEY_SEQUENCE_MAX_STEPS = 40;

function startKeySequenceRecording(wrapEl, hiddenEl, chipsEl, recordBtn) {
  stopKeySequenceRecording(); // only one recorder active at a time
  ensureKeySequenceGlobalListener();
  wrapEl.classList.add("recording");
  recordBtn.textContent = "■ Stop";
  activeKeySequenceRecorder = {
    wrapEl,
    hiddenEl,
    chipsEl,
    recordBtn,
    timeoutId: setTimeout(stopKeySequenceRecording, KEY_SEQUENCE_RECORD_TIMEOUT_MS),
  };
}

function ensureKeySequenceGlobalListener() {
  if (keySequenceGlobalListenerInstalled) return;
  keySequenceGlobalListenerInstalled = true;
  // Capture phase: must win the race against other document-level keydown handlers (e.g. the
  // Ctrl+Z undo/redo listener) so recording "Ctrl+Z" as a macro step doesn't also trigger undo.
  document.addEventListener(
    "keydown",
    (ev) => {
      const rec = activeKeySequenceRecorder;
      if (!rec) return;
      ev.preventDefault();
      ev.stopPropagation();
      if (ev.repeat) return; // holding a key down must not spam duplicate steps
      if (["Control", "Alt", "Shift", "Meta"].includes(ev.key)) return; // wait for the real key
      const mods = [];
      if (ev.ctrlKey) mods.push("ctrl");
      if (ev.altKey) mods.push("alt");
      if (ev.metaKey) mods.push("meta");
      // A single printable character already encodes shift in its value (e.g. Shift+a -> "A");
      // only named keys (Tab, arrows, F-keys, ...) need shift tracked as a separate modifier.
      if (ev.shiftKey && String(ev.key).length > 1) mods.push("shift");
      const cur = keySequenceStepsFromHidden(rec.hiddenEl);
      cur.push({ keys: [...mods, ev.key] });
      rec.hiddenEl.value = JSON.stringify(cur);
      renderKeySequenceChips(rec.chipsEl, rec.hiddenEl);
      rec.hiddenEl.dispatchEvent(new Event("input", { bubbles: true }));
      if (cur.length >= KEY_SEQUENCE_MAX_STEPS) stopKeySequenceRecording();
    },
    true,
  );
}

export function renderKeySequenceField(wrap, f, idPrefix) {
  const fieldWrap = document.createElement("div");
  fieldWrap.className = "key-sequence-field";

  const hidden = document.createElement("input");
  hidden.type = "hidden";
  hidden.dataset.param = f.name;
  hidden.setAttribute("data-param", String(f.name));
  hidden.id = `${idPrefix}_${String(f.name).replace(/[^a-zA-Z0-9_]/g, "_")}`;
  hidden.value = "[]";

  const chips = document.createElement("div");
  chips.className = "key-sequence-chips";

  const controls = document.createElement("div");
  controls.className = "key-sequence-controls";
  const recordBtn = document.createElement("button");
  recordBtn.type = "button";
  recordBtn.className = "btn-record";
  recordBtn.textContent = "● Record";
  const clearBtn = document.createElement("button");
  clearBtn.type = "button";
  clearBtn.className = "btn-clear-seq";
  clearBtn.textContent = "Clear";

  recordBtn.addEventListener("click", () => {
    if (activeKeySequenceRecorder && activeKeySequenceRecorder.hiddenEl === hidden) {
      stopKeySequenceRecording();
    } else {
      startKeySequenceRecording(fieldWrap, hidden, chips, recordBtn);
    }
  });
  clearBtn.addEventListener("click", () => {
    if (activeKeySequenceRecorder && activeKeySequenceRecorder.hiddenEl === hidden) stopKeySequenceRecording();
    hidden.value = "[]";
    renderKeySequenceChips(chips, hidden);
    hidden.dispatchEvent(new Event("input", { bubbles: true }));
  });
  controls.appendChild(recordBtn);
  controls.appendChild(clearBtn);

  const hint = document.createElement("p");
  hint.className = "hint key-sequence-hint";
  hint.textContent = "Click Record, then press the keys in this window, in order. Click Stop when done.";

  fieldWrap.appendChild(hidden);
  fieldWrap.appendChild(chips);
  fieldWrap.appendChild(controls);
  fieldWrap.appendChild(hint);
  wrap.appendChild(fieldWrap);
  renderKeySequenceChips(chips, hidden);
}
