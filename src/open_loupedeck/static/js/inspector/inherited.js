/*
 * inspector/inherited.js — What a control does when this page only inherits the binding for every page:
 * a summary card under the scope bar with the inherited action's name and its look (the key as the
 * device draws it, the LED colour of a button, the role of a knob), and the way out ("Override on this
 * page" in the bar above). Read-only: nothing here edits the shared binding.
 */

import { globalEntry } from "../model.js";
import { cssColorForLedPreview } from "../util.js";
import { capabilities } from "./controls.js";
import { el } from "./dom.js";
import { createPreviewSlot } from "./preview.js";

/**
 * `describe(entry)` -> short name of the binding. Returns { root, destroy() }; the picture is drawn
 * asynchronously (keys) and the card stays useful without it.
 */
export function createInheritedSummary(cid, { describe = () => "" } = {}) {
  const entry = globalEntry(cid) || {};
  const caps = capabilities(cid);
  const name = String(describe(entry) || "").trim() || t("inspector.scope.something");
  const picture = el("figure", { class: "insp-big insp-inherit-pic" });
  let slot = null;
  if (caps.image) {
    const img = el("img", { alt: t("inspector.inherited.preview_alt"), hidden: true });
    picture.append(el("span", { class: "insp-big-empty", "aria-hidden": "true" }), img);
    slot = createPreviewSlot(img, { onEmpty: () => {}, onResult: (r) => picture.classList.toggle("is-ready", !r.empty) });
    void slot.show(entry, cid);
  } else if (caps.led) {
    const raw = entry.button_color && String(entry.button_color).trim();
    const led = el("span", { class: "insp-led", "aria-hidden": "true" });
    if (raw) led.style.setProperty("--led", cssColorForLedPreview(raw));
    picture.append(led);
    picture.classList.add("is-round");
  } else {
    picture.hidden = true;
  }
  const root = el(
    "section",
    { class: "insp-inherited", "aria-label": t("inspector.inherited.title") },
    el(
      "div",
      { class: "insp-look" },
      picture,
      el(
        "div",
        { class: "insp-look-text" },
        el("span", { class: "insp-inherit-tag", text: t("inspector.inherited.title") }),
        el("strong", { class: "insp-look-title", text: name }),
        el("span", { text: t("inspector.inherited.cta") }),
      ),
    ),
  );
  return {
    root,
    destroy() {
      if (slot) slot.dispose();
      root.remove();
    },
  };
}
