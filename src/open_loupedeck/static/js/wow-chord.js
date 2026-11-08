/*
 * wow-chord.js — custom field of the `wow.keybind` action: the `key` parameter is exactly ONE key chord
 * (`ctrl+shift+f13`). A text field (so F13–F24, which most keyboards lack, can be typed), a "Record" button that
 * captures the next chord pressed in this window, and an inline validation message. The rules mirror
 * keyboard_replay.parse_chord (the server re-validates when the key is pressed).
 */

import { registerFieldRenderer } from "./action-fields.js";

const MODIFIERS = { ctrl: "ctrl", control: "ctrl", shift: "shift", alt: "alt" };
const MOD_ORDER = ["ctrl", "alt", "shift"];
const NAMED = new Set([
  "tab", "enter", "return", "esc", "escape", "space", "backspace", "delete", "insert", "up", "down", "left", "right",
  "home", "end", "pageup", "page_up", "pagedown", "page_down", "capslock", "caps_lock", "numlock", "num_lock",
  "printscreen", "print_screen", "menu", "pause",
]);
const FOREIGN_MODIFIERS = new Set(["meta", "win", "cmd", "super", "altgr", "alt_gr"]);

/** "" when the chord is valid (or empty), else the i18n key of the problem. */
export function chordProblem(text) {
  const raw = String(text || "").trim().toLowerCase();
  if (!raw) return "";
  const parts = raw.split("+").map((p) => p.trim());
  if (parts.some((p) => !p)) return "inspector.chord.error.malformed";
  const mods = new Set();
  const others = [];
  for (const p of parts) {
    if (MODIFIERS[p]) {
      if (mods.has(MODIFIERS[p])) return "inspector.chord.error.malformed";
      mods.add(MODIFIERS[p]);
    } else others.push(p);
  }
  if (!others.length) return "inspector.chord.error.no_key";
  if (others.length > 1) return "inspector.chord.error.several";
  const k = others[0];
  if (FOREIGN_MODIFIERS.has(k)) return "inspector.chord.error.unsupported";
  if (/^f\d+$/.test(k)) return Number(k.slice(1)) >= 1 && Number(k.slice(1)) <= 24 ? "" : "inspector.chord.error.unknown";
  if (k.length === 1) return /^[a-z0-9]$/.test(k) ? "" : "inspector.chord.error.unknown";
  return NAMED.has(k) ? "" : "inspector.chord.error.unknown";
}

const KEY_ALIASES = { " ": "space", arrowup: "up", arrowdown: "down", arrowleft: "left", arrowright: "right", pageup: "pageup", pagedown: "pagedown" };

/** Chord string for a keydown event, or "" while only modifiers are held. */
export function chordFromEvent(ev) {
  const k = String(ev.key || "").toLowerCase();
  if (["control", "shift", "alt", "meta", "altgraph"].includes(k)) return "";
  const main = KEY_ALIASES[k] || k;
  const mods = [];
  if (ev.ctrlKey) mods.push("ctrl");
  if (ev.altKey) mods.push("alt");
  if (ev.shiftKey) mods.push("shift");
  return [...mods, main].join("+");
}

function renderChordField(container, wrap, f, idPrefix) {
  const fid = `${idPrefix}_${String(f.name).replace(/[^a-zA-Z0-9_]/g, "_")}`;
  const lab = document.createElement("label");
  lab.className = "field-label";
  lab.htmlFor = fid;
  lab.textContent = f.optional ? `${f.label || f.name} ${t("inspector.field.optional")}` : f.label || f.name;

  const row = document.createElement("div");
  row.className = "path-with-browse";
  const input = document.createElement("input");
  input.type = "text";
  input.id = fid;
  input.className = "mono path-input";
  input.dataset.param = f.name;
  input.setAttribute("data-param", String(f.name));
  input.autocomplete = "off";
  input.spellcheck = false;
  if (f.placeholder) input.placeholder = f.placeholder;
  const rec = document.createElement("button");
  rec.type = "button";
  rec.className = "btn-record";
  rec.textContent = t("inspector.chord.record");
  row.append(input, rec);

  const problem = document.createElement("p");
  problem.className = "hint field-help msg-error";
  problem.setAttribute("role", "alert");
  problem.hidden = true;

  const check = () => {
    const key = chordProblem(input.value);
    problem.hidden = !key;
    problem.textContent = key ? t(key) : "";
    input.classList.toggle("is-invalid", !!key);
  };
  input.addEventListener("input", check);

  let listener = null;
  let timer = 0;
  const stop = () => {
    if (listener) document.removeEventListener("keydown", listener, true);
    listener = null;
    clearTimeout(timer);
    rec.textContent = t("inspector.chord.record");
  };
  rec.addEventListener("click", () => {
    if (listener) return stop();
    rec.textContent = t("inspector.chord.press");
    listener = (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      if (ev.repeat) return;
      const chord = chordFromEvent(ev);
      if (!chord) return; // only modifiers so far
      stop();
      input.value = chord;
      input.dispatchEvent(new Event("input", { bubbles: true }));
    };
    // Capture phase: the recorded chord (e.g. Ctrl+Z) must not also trigger the page's own shortcuts.
    document.addEventListener("keydown", listener, true);
    timer = setTimeout(stop, 15000);
  });

  wrap.append(lab, row, problem);
  if (f.help) {
    const help = document.createElement("p");
    help.className = "hint field-help";
    help.textContent = f.help;
    wrap.appendChild(help);
  }
  container.appendChild(wrap);
  // Fill happens after render (fillActionFieldsInContainer sets .value without an event).
  setTimeout(check, 0);
}

registerFieldRenderer("wow.keybind", "key", renderChordField);
