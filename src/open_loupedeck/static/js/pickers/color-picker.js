/*
 * pickers/color-picker.js — colour swatches by family, recent colours, custom hex, contrast hint.
 *
 *   const c = createColorPicker(container, { value, palette, onChange, against });
 *   c.setValue(hex)   c.setAgainst(hex)   c.focus()   c.destroy()
 *
 * `palette`: optional array of colours (shown first as "Suggested") or of families {id, name, tones[]}.
 * `against`: the colour this one is read against (text colour for a background picker and vice versa); when the
 * contrast ratio falls below 3 a warning is shown. onChange(hex) always receives "#rrggbb" and fires on user picks.
 * `contrastRatio` is re-exported for callers.
 */

import { LOW_CONTRAST, contrastRatio, normalizeHex } from "./helpers.js";
import { el, loadJSON, nextId, onLanguageChange, saveJSON, tr } from "./common.js";

export { contrastRatio };

const KEY_RECENT = "olp.picker.colors.recent";
const RECENT_MAX = 8;

/** Colours from the redesign mockup come first, then each family from dark to light. */
export const SUGGESTED = ["#1f6fe0", "#1fb8a4", "#22a35a", "#e5b000", "#e0501f", "#9146ff", "#4a4f8f", "#2a3345", "#ffffff", "#e8ecf4", "#ffb020", "#06220f", "#1a1000", "#000000"];

export const FAMILIES = [
  { id: "blue", tones: ["#12306b", "#1a4fa8", "#1f6fe0", "#4b8df0", "#7fb0f7", "#b5d1fb"] },
  { id: "teal", tones: ["#0c4a44", "#12766b", "#1fb8a4", "#3fd1bd", "#7ce3d4", "#b6f0e8"] },
  { id: "green", tones: ["#0f4a28", "#167a40", "#22a35a", "#3fc176", "#7bd9a0", "#b4eacb"] },
  { id: "yellow", tones: ["#7a5a00", "#b38700", "#e5b000", "#f2c633", "#f7d965", "#fbe9a3"] },
  { id: "orange", tones: ["#7a2a0c", "#b53c12", "#e0501f", "#f0743f", "#f79b72", "#fbc3ab"] },
  { id: "red", tones: ["#6e1420", "#a31f33", "#d63048", "#ea5568", "#f28b98", "#f8bfc6"] },
  { id: "violet", tones: ["#33266f", "#4a4f8f", "#6a42d6", "#9146ff", "#b583ff", "#d7bdff"] },
  { id: "slate", tones: ["#10151f", "#1b2230", "#2a3345", "#4a5568", "#8b95a8", "#cbd2de"] },
];

export function createColorPicker(container, opts = {}) {
  const { onChange = () => {} } = opts;
  let value = normalizeHex(opts.value) || "";
  let against = opts.against || "";
  let recent = loadJSON(KEY_RECENT, []).filter((c) => typeof c === "string" && normalizeHex(c));
  let customOpen = false;
  const id = nextId("pk-cp");

  let suggested = SUGGESTED;
  let families = FAMILIES;
  if (Array.isArray(opts.palette) && opts.palette.length) {
    if (typeof opts.palette[0] === "string") suggested = opts.palette.map((c) => normalizeHex(c)).filter(Boolean);
    else families = opts.palette.map((f) => ({ id: f.id, name: f.name, tones: (f.tones || []).map((c) => normalizeHex(c)).filter(Boolean) }));
  }

  const root = el("div", { class: "pk-cp" });
  container.append(root);

  function swatch(color, label) {
    const hex = normalizeHex(color);
    const b = el("button", { type: "button", class: "sw", "data-color": hex, "aria-pressed": hex === value ? "true" : "false", "aria-label": label ? `${label} ${hex}` : hex, title: hex });
    b.style.background = hex;
    b.addEventListener("click", () => choose(hex));
    return b;
  }

  function choose(hex, { remember = true } = {}) {
    value = hex;
    if (remember) {
      recent = [hex, ...recent.filter((c) => c !== hex)].slice(0, RECENT_MAX);
      saveJSON(KEY_RECENT, recent);
    }
    root.querySelectorAll(".sw").forEach((n) => n.setAttribute("aria-pressed", n.dataset.color === value ? "true" : "false"));
    syncCustom();
    paintWarn();
    onChange(hex);
  }

  const warn = el("div", { class: "pk-warn msg-warn", role: "status", hidden: true });
  let hexInput = null;
  let native = null;
  let preview = null;

  function paintWarn() {
    const ratio = value && against ? contrastRatio(value, against) : null;
    if (ratio != null && ratio < LOW_CONTRAST) {
      warn.hidden = false;
      warn.textContent = tr("picker.color.lowContrast", "Low contrast with {other} ({ratio}:1). The text may be hard to read.", { other: normalizeHex(against), ratio: ratio.toFixed(1) });
    } else {
      warn.hidden = true;
      warn.textContent = "";
    }
  }

  function syncCustom() {
    if (!hexInput) return;
    if (document.activeElement !== hexInput) hexInput.value = value || "";
    hexInput.classList.remove("is-invalid");
    if (native && value) native.value = value;
    if (preview && value) preview.style.background = value;
  }

  function paint() {
    root.textContent = "";
    const section = (title, ...kids) => el("div", { class: "pk-section" }, title ? el("div", { class: "pk-gname", text: title }) : null, ...kids);

    root.append(section(tr("picker.color.suggested", "Suggested"), el("div", { class: "swatches" }, suggested.map((c) => swatch(c)))));
    const recents = recent.slice(0, RECENT_MAX);
    if (recents.length) root.append(section(tr("picker.color.recent", "Recently used"), el("div", { class: "swatches" }, recents.map((c) => swatch(c)))));

    const fam = el("div", { class: "pk-families" });
    for (const f of families) {
      const name = f.name || tr(`picker.color.family.${f.id}`, f.id);
      fam.append(el("div", { class: "pk-family", role: "group", "aria-label": name }, el("span", { class: "pk-fname", text: name }), el("div", { class: "swatches" }, f.tones.map((c) => swatch(c, name)))));
    }
    root.append(section(tr("picker.color.palette", "Palette"), fam));

    const toggle = el("button", { type: "button", class: "btn btn-secondary btn-sm pk-custom-btn", "aria-expanded": customOpen ? "true" : "false", "aria-controls": `${id}-custom`, text: tr("picker.color.custom", "Custom…") });
    const panel = el("div", { class: "pk-custom", id: `${id}-custom`, hidden: !customOpen });
    preview = el("span", { class: "pk-cprev" });
    hexInput = el("input", { type: "text", class: "pk-input mono pk-short", placeholder: "#rrggbb", maxlength: "9", autocomplete: "off", spellcheck: "false", "aria-label": tr("picker.color.hex", "Hex colour") });
    native = el("input", { type: "color", class: "pk-native", "aria-label": tr("picker.color.pick", "Pick a colour") });
    panel.append(preview, hexInput, native);
    toggle.addEventListener("click", () => {
      customOpen = !customOpen;
      panel.hidden = !customOpen;
      toggle.setAttribute("aria-expanded", String(customOpen));
      if (customOpen) hexInput.focus();
    });
    hexInput.addEventListener("input", () => {
      const hex = normalizeHex(hexInput.value);
      hexInput.classList.toggle("is-invalid", !!hexInput.value.trim() && !hex);
      if (hex) {
        value = hex;
        native.value = hex;
        preview.style.background = hex;
        root.querySelectorAll(".sw").forEach((n) => n.setAttribute("aria-pressed", n.dataset.color === hex ? "true" : "false"));
        paintWarn();
        onChange(hex);
      }
    });
    hexInput.addEventListener("change", () => {
      const hex = normalizeHex(hexInput.value);
      if (hex) {
        hexInput.value = hex;
        choose(hex);
      }
    });
    hexInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") hexInput.dispatchEvent(new Event("change"));
    });
    native.addEventListener("input", () => {
      hexInput.value = native.value;
      hexInput.dispatchEvent(new Event("input"));
    });
    native.addEventListener("change", () => choose(native.value));
    root.append(section("", toggle, panel), warn);
    hexInput.value = value || "";
    native.value = value || "#000000";
    if (value) preview.style.background = value;
    paintWarn();
  }

  const offLang = onLanguageChange(paint);
  paint();

  return {
    setValue(v) {
      value = normalizeHex(v) || "";
      root.querySelectorAll(".sw").forEach((n) => n.setAttribute("aria-pressed", n.dataset.color === value ? "true" : "false"));
      syncCustom();
      paintWarn();
    },
    setAgainst(c) {
      against = c || "";
      paintWarn();
    },
    focus() {
      (root.querySelector('.sw[aria-pressed="true"]') || root.querySelector(".sw"))?.focus();
    },
    destroy() {
      offLang();
      root.remove();
    },
  };
}
