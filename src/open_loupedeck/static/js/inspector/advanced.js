/*
 * inspector/advanced.js — Step 3 "Advanced" (a collapsed <details>): idle / press animations,
 * gradients, font file and size, icon-and-label layout and image margin, the action as JSON, and the
 * "test press" button. Every field writes its existing config key directly (empty = key removed).
 */

import { postSimulatePress, uploadFileToAssets } from "../api.js";
import { controlCanSimulate } from "../model.js";
import { normalizeHex } from "../pickers/helpers.js";
import { el, hasFocus, nextId, svgIcon } from "./dom.js";
import { entryAction, setEntryAction } from "./entry.js";

const IDLE = ["none", "shake", "pulse", "gradient_rotate", "color_cycle"];
const PRESS = ["none", "flash", "invert", "zoom_text", "slide_reappear"];
const DIRECTIONS = ["left", "right", "up", "down"];

/**
 * `ctx`: { cid, kind, ui, entry(), edit(mutate, opts), onActionJson(action), playPress() }.
 * `ui.advOpen` keeps the <details> state across refreshes.
 */
export function createAdvancedStep(ctx) {
  const { cid, ui } = ctx;
  const id = nextId("insp-adv");
  const screen = ctx.kind === "touch" || ctx.kind === "strip";
  const syncers = [];

  const body = el("div", { class: "acc-body insp-adv-body" });
  const details = el(
    "details",
    { class: "acc insp-adv" },
    el("summary", {}, el("span", {}, el("b", { class: "insp-num", "aria-hidden": "true", text: "3" }), t("inspector.step3.title"))),
    body,
  );
  details.open = !!ui.advOpen;
  details.addEventListener("toggle", () => (ui.advOpen = details.open));

  function group(titleKey, ...kids) {
    const hid = nextId(id);
    const g = el("div", { class: "insp-group", role: "group", "aria-labelledby": hid }, el("h4", { id: hid, text: t(titleKey) }), ...kids);
    body.append(g);
    return g;
  }

  function field(labelKey, control, extraClass = "") {
    const fid = control.id || nextId(id);
    control.id = fid;
    return el("div", { class: `insp-field ${extraClass}`.trim() }, el("label", { for: fid, text: t(labelKey) }), control);
  }

  /** Text/number input bound to one entry key (empty = removed; invalid numbers are not saved). */
  function bindInput(input, key, { number = false, min = null, max = null } = {}) {
    input.addEventListener("input", () => {
      const raw = input.value.trim();
      let v = raw;
      if (number && raw) {
        const n = Number(raw);
        const bad = !Number.isFinite(n) || (min != null && n < min) || (max != null && n > max);
        input.classList.toggle("is-invalid", bad);
        if (bad) return;
        v = n;
      } else input.classList.remove("is-invalid");
      ctx.edit(
        (e) => {
          if (raw === "") delete e[key];
          else e[key] = v;
        },
        { typing: true },
      );
    });
    syncers.push((e) => {
      if (!hasFocus(input)) {
        input.value = e[key] != null ? String(e[key]) : "";
        input.classList.remove("is-invalid");
      }
    });
    return input;
  }

  function select(key, values, labelPrefix, defaultValue, onPick) {
    const s = el("select", {});
    for (const v of values) s.append(el("option", { value: v, text: t(`${labelPrefix}.${v}`) }));
    s.addEventListener("change", () => onPick(s.value));
    syncers.push((e) => (s.value = e[key] != null && values.includes(String(e[key])) ? String(e[key]) : defaultValue));
    return s;
  }

  /** Colour stop: a native colour well and a hex field bound to one key. */
  function colourStop(key, labelKey) {
    const hex = el("input", { type: "text", class: "mono insp-hex", placeholder: "#rrggbb", maxlength: "9", autocomplete: "off", spellcheck: "false" });
    const well = el("input", { type: "color", class: "insp-well", "aria-label": t(labelKey) });
    const fid = nextId(id);
    hex.id = fid;
    const commit = (v, typing) => {
      const h = normalizeHex(v);
      hex.classList.toggle("is-invalid", !!v.trim() && !h);
      if (v.trim() && !h) return;
      ctx.edit(
        (e) => {
          if (h) e[key] = h;
          else delete e[key];
        },
        { typing },
      );
    };
    hex.addEventListener("input", () => commit(hex.value, true));
    well.addEventListener("input", () => {
      hex.value = well.value;
      commit(well.value, true);
    });
    syncers.push((e) => {
      const v = e[key] ? String(e[key]) : "";
      if (!hasFocus(hex)) hex.value = v;
      well.value = normalizeHex(v) || "#808080";
    });
    return el("div", { class: "insp-field insp-stop" }, el("label", { for: fid, text: t(labelKey) }), el("span", { class: "insp-stop-row" }, well, hex));
  }

  if (screen) {
    // --- animations ----------------------------------------------------------------------------
    const speed = bindInput(el("input", { type: "number", min: "0.1", max: "10", step: "0.1", placeholder: "1" }), "idle_animation_speed", { number: true, min: 0.1, max: 10 });
    const speedField = field("inspector.adv.speed", speed);
    const idle = select("idle_animation", IDLE, "inspector.adv.idle", "none", (v) =>
      ctx.edit((e) => {
        if (v === "none") {
          delete e.idle_animation;
          delete e.idle_animation_speed;
        } else e.idle_animation = v;
      }),
    );
    const dir = select("press_animation_direction", DIRECTIONS, "inspector.adv.dir", "left", (v) =>
      ctx.edit((e) => {
        if (v === "left") delete e.press_animation_direction;
        else e.press_animation_direction = v;
      }),
    );
    const dirField = field("inspector.adv.direction", dir);
    const flashField = colourStop("press_flash_color", "inspector.adv.flash_color");
    const press = select("press_animation", PRESS, "inspector.adv.press", "none", (v) =>
      ctx.edit((e) => {
        if (v === "none") {
          for (const k of ["press_animation", "press_animation_direction", "press_flash_color"]) delete e[k];
        } else e.press_animation = v;
      }),
    );
    const btnPlay = el("button", { type: "button", class: "btn btn-sm" }, svgIcon("play"), t("inspector.adv.preview_press"));
    btnPlay.addEventListener("click", () => ctx.playPress());
    group(
      "inspector.adv.animations",
      el("div", { class: "insp-grid2" }, field("inspector.adv.idle", idle), speedField),
      el("div", { class: "insp-grid2" }, field("inspector.adv.press", press), dirField, flashField),
      btnPlay,
    );
    syncers.push((e) => {
      speedField.hidden = !e.idle_animation;
      const p = e.press_animation || "none";
      dirField.hidden = p !== "slide_reappear";
      flashField.hidden = p !== "flash";
      btnPlay.hidden = p === "none";
    });

    // --- gradients -----------------------------------------------------------------------------
    const gradient = (layer) => {
      const prefix = layer === "bg" ? "background_gradient" : "text_gradient";
      const angle = bindInput(el("input", { type: "number", min: "0", max: "360", placeholder: "0" }), `${prefix}_angle`, { number: true, min: 0, max: 360 });
      const clear = el("button", { type: "button", class: "btn btn-sm btn-ghost", text: t("inspector.adv.gradient.clear") });
      clear.addEventListener("click", () =>
        ctx.edit((e) => {
          for (const k of ["from", "to", "angle"]) delete e[`${prefix}_${k}`];
        }),
      );
      syncers.push((e) => (clear.hidden = !(e[`${prefix}_from`] || e[`${prefix}_to`])));
      return el(
        "div",
        { class: "insp-subgroup" },
        el("div", { class: "insp-subhead" }, el("span", { text: t(`inspector.adv.gradient.${layer}`) }), clear),
        el(
          "div",
          { class: "insp-grid3" },
          colourStop(`${prefix}_from`, "inspector.adv.gradient.from"),
          colourStop(`${prefix}_to`, "inspector.adv.gradient.to"),
          field("inspector.adv.gradient.angle", angle),
        ),
      );
    };
    group("inspector.adv.gradients", el("p", { class: "hint", text: t("inspector.adv.gradient.hint") }), gradient("bg"), gradient("fg"));

    // --- font ----------------------------------------------------------------------------------
    const fontFile = bindInput(el("input", { type: "text", class: "mono", placeholder: t("inspector.adv.font_file.placeholder"), autocomplete: "off", spellcheck: "false" }), "font_file");
    const fileIn = el("input", { type: "file", hidden: true, accept: ".ttf,.otf,.ttc,font/ttf,font/otf,application/font-sfnt" });
    const browse = el("button", { type: "button", class: "btn btn-sm", text: t("inspector.field.browse") });
    const fontErr = el("p", { class: "msg-error", role: "alert", hidden: true });
    browse.addEventListener("click", () => fileIn.click());
    fileIn.addEventListener("change", async () => {
      const f = fileIn.files && fileIn.files[0];
      fileIn.value = "";
      if (!f) return;
      try {
        const path = await uploadFileToAssets(f, "fonts");
        fontErr.hidden = true;
        ctx.edit((e) => (e.font_file = path));
      } catch (err) {
        fontErr.textContent = String(err.message || err);
        fontErr.hidden = false;
      }
    });
    const fontSize = bindInput(el("input", { type: "number", min: "8", max: "64", placeholder: t("inspector.adv.font_size.placeholder") }), "font_size", { number: true, min: 1, max: 200 });
    const fid = nextId(id);
    fontFile.id = fid;
    group(
      "inspector.adv.font",
      el("div", { class: "insp-field" }, el("label", { for: fid, text: t("inspector.adv.font_file") }), el("div", { class: "insp-browse" }, fontFile, browse, fileIn)),
      fontErr,
      field("inspector.adv.font_size", fontSize),
    );

    // --- layout ------------------------------------------------------------------------------
    const layout = select("graphic_text_layout", ["split", "overlay"], "inspector.adv.layout", "split", (v) =>
      ctx.edit((e) => {
        if (v === "split") delete e.graphic_text_layout;
        else e.graphic_text_layout = v;
      }),
    );
    const inset = bindInput(el("input", { type: "number", min: "0", max: "24", placeholder: t("inspector.adv.inset.placeholder") }), "graphic_inset", { number: true, min: 0, max: 24 });
    group("inspector.adv.layout_title", field("inspector.adv.layout.when_both", layout), field("inspector.adv.inset", inset));
  }

  // --- action JSON ----------------------------------------------------------------------------
  const json = el("textarea", { class: "mono insp-json", rows: "7", spellcheck: "false" });
  const jsonMsg = el("p", { class: "hint insp-json-msg", role: "status" });
  json.addEventListener("input", () => {
    const raw = json.value.trim();
    let action = null;
    let err = "";
    if (raw) {
      try {
        action = JSON.parse(raw);
        if (!action || typeof action !== "object" || Array.isArray(action)) err = t("inspector.adv.json.not_object");
        else if (!action.type) err = t("inspector.adv.json.need_type");
      } catch {
        err = t("inspector.adv.json.invalid");
      }
    }
    json.classList.toggle("is-invalid", !!err);
    jsonMsg.textContent = err || t("inspector.adv.json.hint");
    jsonMsg.classList.toggle("is-error", !!err);
    if (err) return;
    ctx.edit((e) => setEntryAction(e, action), { typing: true });
    ctx.onActionJson(action);
  });
  json.addEventListener("blur", () => {
    json.classList.remove("is-invalid");
    jsonMsg.classList.remove("is-error");
    jsonMsg.textContent = t("inspector.adv.json.hint");
    syncJson(ctx.entry(), true);
  });
  function syncJson(e, force = false) {
    if (hasFocus(json) && !force) return;
    const a = entryAction(e);
    json.value = a ? JSON.stringify(a, null, 2) : "";
  }
  jsonMsg.textContent = t("inspector.adv.json.hint");
  const jid = nextId(id);
  json.id = jid;
  group("inspector.adv.json", el("label", { class: "sr-only", for: jid, text: t("inspector.adv.json") }), json, jsonMsg);
  syncers.push((e) => syncJson(e));

  // --- test press -----------------------------------------------------------------------------
  const btnTest = el("button", { type: "button", class: "btn", id: "btnTestPress" }, svgIcon("play"), t("inspector.adv.test"));
  const testMsg = el("p", { class: "hint", role: "status" });
  const canTest = controlCanSimulate(cid);
  btnTest.disabled = !canTest;
  testMsg.textContent = canTest ? t("inspector.adv.test.hint") : t("inspector.adv.test.unavailable");
  btnTest.addEventListener("click", async () => {
    try {
      await postSimulatePress(cid, null);
      testMsg.textContent = t("inspector.adv.test.done");
    } catch (err) {
      testMsg.textContent = String(err.message || err);
    }
  });
  group("inspector.adv.test_title", btnTest, testMsg);

  return {
    root: details,
    sync() {
      const e = ctx.entry();
      for (const s of syncers) s(e);
    },
    destroy() {},
  };
}
