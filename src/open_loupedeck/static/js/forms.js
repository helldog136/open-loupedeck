/*
 * forms.js — Generic "smart" field wiring (validate on input, commit on blur) and the shared
 * validators.
 */

import { cancelPendingAutosave, runAutosave, scheduleAutosave } from "./save.js";
import { snapshotBeforeEditOnce } from "./undo.js";

/** Generic field validators, shared by Services fields and (later) the button editor. */
export const FIELD_VALIDATORS = {
  hexColor: (v) => /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.test(v.trim()),
  port: (v) => {
    const n = Number(v.trim());
    return Number.isInteger(n) && n >= 1 && n <= 65535;
  },
  nonEmpty: (v) => v.trim().length > 0,
};

/**
 * Wire an input/select/textarea for "smart" autosave: validate on every keystroke, never persist
 * an invalid value (red outline instead), commit on blur immediately, commit on valid input after
 * the normal debounce. `validate` returns true/false or an error string; `onCommit(value)` applies
 * the value to `cfg` (the caller still triggers scheduleAutosave()/runAutosave()).
 */
export function wireSmartField(el, { validate, onCommit, optional = true }) {
  if (!el) return;
  const check = (raw) => {
    if (optional && raw.trim() === "") return true;
    const res = validate(raw);
    return res === undefined ? true : res;
  };
  const applyValidity = (raw) => {
    const res = check(raw);
    const ok = res === true;
    el.classList.toggle("field-invalid", !ok);
    el.title = ok ? "" : typeof res === "string" ? res : "Invalid value";
    return ok;
  };
  el.addEventListener("input", () => {
    const raw = el.value;
    if (applyValidity(raw)) {
      snapshotBeforeEditOnce();
      onCommit(raw);
      scheduleAutosave();
    } else {
      cancelPendingAutosave();
    }
  });
  el.addEventListener("blur", () => {
    const raw = el.value;
    if (applyValidity(raw)) {
      onCommit(raw);
      cancelPendingAutosave();
      void runAutosave();
    }
  });
}
