/*
 * inspector/dom.js — Small DOM pieces shared by the inspector steps: element builder (re-exported from
 * the pickers), unique ids, inline SVG icons, the "proposed / modified + reset" tag and the
 * segmented-control group.
 */

import { el, nextId } from "../pickers/common.js";

export { el, nextId };

const ICON_PATHS = {
  copy: "M9 9h11v11H9z M5 15H4V4h11v1",
  paste: "M9 4h6v3H9z M8 5H5v16h14V5h-3 M9 13h6 M9 17h4",
  trash: "M4 7h16 M10 11v6 M14 11v6 M6 7l1 13h10l1-13 M9 7V4h6v3",
  play: "M7 5l11 7-11 7z",
};

/** A 24x24 stroke icon (decorative: the button carries the accessible name). */
export function svgIcon(name) {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("class", "insp-svg");
  for (const d of (ICON_PATHS[name] || "").split(" M")) {
    const p = document.createElementNS(ns, "path");
    p.setAttribute("d", d.startsWith("M") ? d : `M${d}`);
    svg.append(p);
  }
  return svg;
}

/**
 * Fill `host` with the field's tag: "Proposed", or "Modified" + a reset link calling `onReset`.
 * `fieldLabel` names the field for the reset button's accessible name.
 */
export function paintTag(host, modified, fieldLabel, onReset) {
  host.textContent = "";
  host.className = modified ? "tag mod" : "tag proposed";
  host.append(document.createTextNode(t(modified ? "inspector.tag.modified" : "inspector.tag.proposed")));
  if (modified) {
    const b = el("button", {
      type: "button",
      class: "insp-reset",
      text: t("inspector.tag.reset"),
      "aria-label": t("inspector.tag.reset_label", { field: fieldLabel }),
    });
    b.addEventListener("click", onReset);
    host.append(b);
  }
}

/** Segmented control: `options` [[value, label]], `onPick(value)`. Returns { root, set(value) }. */
export function segmented(options, labelledBy, onPick) {
  const root = el("div", { class: "seg insp-seg", role: "group", "aria-labelledby": labelledBy });
  const buttons = options.map(([value, label]) => {
    const b = el("button", { type: "button", "data-value": value, "aria-pressed": "false", text: label });
    b.addEventListener("click", () => onPick(value));
    root.append(b);
    return b;
  });
  return {
    root,
    set(value) {
      for (const b of buttons) b.setAttribute("aria-pressed", b.dataset.value === value ? "true" : "false");
    },
  };
}

/** True while focus is inside `node` (used to avoid rewriting a field the user is typing in). */
export function hasFocus(node) {
  return !!(node && document.activeElement && node.contains(document.activeElement));
}
