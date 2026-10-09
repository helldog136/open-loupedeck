/*
 * inspector/page-button-view.js — Inspector for a Live S round button: it always opens its page, so
 * only the colour of its light (`button_color`) can be set, with the colour picker, a light preview
 * and a "modified + reset" tag.
 */

import { getButtonEntry } from "../model.js";
import { syncPageLedColors } from "../pages.js";
import { createColorPicker } from "../pickers/color-picker.js";
import { state } from "../state.js";
import { cssColorForLedPreview, sanitizeButtonColorHex } from "../util.js";
import { pageButtonNumber } from "./controls.js";
import { el, nextId, paintTag } from "./dom.js";
import { editEntry } from "./edit.js";
import { createHeader } from "./key-view.js";

/** Default light colours of the four page buttons (mirrors pages.js). */
const DEFAULT_LEDS = ["#3b6bff", "#ff8a2b", "#e040c8", "#2de0c0"];

export function createPageButtonView(host, cid) {
  const id = nextId("insp-led");
  const n = pageButtonNumber(cid);
  const view = el("div", { class: "insp-view", "data-control": cid });
  const header = createHeader(cid, () => refresh());
  const page = state.cfg.pages && state.cfg.pages[n - 1];
  const pageName = (page && page.name) || t("pages.default_name", { number: n });

  const tag = el("span", { class: "tag proposed" });
  const led = el("span", { class: "insp-led", "aria-hidden": "true" });
  const pickHost = el("div", { class: "insp-led-picker" });
  const section = el(
    "section",
    { class: "insp-step", "aria-labelledby": `${id}-h` },
    el("h3", { id: `${id}-h` }, el("b", { "aria-hidden": "true", text: "1" }), el("span", { text: t("inspector.page_button.led", { number: n }) })),
    el("p", { class: "hint", text: t("inspector.page_button.hint", { number: n, page: pageName }) }),
    el("div", { class: "insp-row-head" }, el("span", { class: "insp-led-wrap" }, led, el("span", { class: "insp-row-label", text: t("inspector.page_button.colour") })), tag),
    pickHost,
  );
  view.append(header.root, section);
  host.append(view);

  const stored = () => {
    const e = getButtonEntry(cid);
    return (e && e.button_color && String(e.button_color).trim()) || "";
  };
  const picker = createColorPicker(pickHost, {
    value: sanitizeButtonColorHex(stored()) || DEFAULT_LEDS[n - 1],
    onChange: (hex) => {
      editEntry(cid, (e) => (e.button_color = hex));
      refresh();
    },
  });

  function refresh() {
    const raw = stored();
    paintTag(tag, !!raw, t("inspector.page_button.colour"), () => {
      editEntry(cid, (e) => delete e.button_color);
      refresh();
    });
    const shown = raw ? cssColorForLedPreview(raw) : DEFAULT_LEDS[n - 1];
    led.style.setProperty("--led", shown);
    picker.setValue(sanitizeButtonColorHex(raw) || DEFAULT_LEDS[n - 1]);
    header.sync();
    syncPageLedColors();
  }
  refresh();

  return {
    cid,
    refresh,
    setCatalog() {},
    focus() {
      picker.focus();
    },
    destroy() {
      picker.destroy();
      view.remove();
    },
  };
}
