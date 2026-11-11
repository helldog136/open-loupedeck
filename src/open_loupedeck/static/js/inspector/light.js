/*
 * inspector/light.js — The "Light" step of a control with an LED output: the colour of its light
 * (`button_color`), with the colour picker, a light preview and a "modified + reset" tag. Without a
 * colour the device shows the model's default LED colour.
 */

import { defaultLedHex } from "../model.js";
import { syncPageLedColors } from "../pages.js";
import { createColorPicker } from "../pickers/color-picker.js";
import { cssColorForLedPreview, sanitizeButtonColorHex } from "../util.js";
import { el, nextId, paintTag } from "./dom.js";

/** `ctx`: { cid, entry(), edit(mutate) , number }. Returns { root, sync(), destroy() }. */
export function createLightStep(ctx, number) {
  const { cid } = ctx;
  const id = nextId("insp-led");
  const tag = el("span", { class: "tag proposed" });
  const led = el("span", { class: "insp-led", "aria-hidden": "true" });
  const pickHost = el("div", { class: "insp-led-picker" });
  const root = el(
    "section",
    { class: "insp-step insp-step-light", "aria-labelledby": `${id}-h` },
    el("h3", { id: `${id}-h` }, el("b", { "aria-hidden": "true", text: String(number) }), el("span", { text: t("inspector.light.title") })),
    el("p", { class: "hint", text: t("inspector.light.hint") }),
    el(
      "div",
      { class: "insp-row-head" },
      el("span", { class: "insp-led-wrap" }, led, el("span", { class: "insp-row-label", text: t("inspector.light.colour") })),
      tag,
    ),
    pickHost,
  );

  const stored = () => {
    const e = ctx.entry();
    return (e && e.button_color && String(e.button_color).trim()) || "";
  };
  const fallback = defaultLedHex(cid);
  const picker = createColorPicker(pickHost, {
    value: sanitizeButtonColorHex(stored()) || fallback,
    onChange: (hex) => ctx.edit((e) => (e.button_color = hex)),
  });

  function sync() {
    const raw = stored();
    paintTag(tag, !!raw, t("inspector.light.colour"), () => ctx.edit((e) => delete e.button_color), {
      asDefault: true,
    });
    led.style.setProperty("--led", raw ? cssColorForLedPreview(raw) : fallback);
    picker.setValue(sanitizeButtonColorHex(raw) || fallback);
    syncPageLedColors();
  }
  sync();
  return {
    root,
    sync,
    destroy() {
      picker.destroy();
    },
  };
}
