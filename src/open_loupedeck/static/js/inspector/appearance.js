/*
 * inspector/appearance.js — Step 2 "Appearance": the big live preview (server-rendered, identical to
 * the device), the "proposed look / N custom settings" summary with Customize and Reset all, the
 * online/offline pair of live keys, the text-overflow warning with quick fixes, and the customisable
 * fields (content mode, label, icon, background, text colour, offline fallback), each tagged
 * "proposed" or "modified + reset". A field the user never touched is not stored and follows the action.
 */

import { createColorPicker } from "../pickers/color-picker.js";
import { renderIcon } from "../pickers/common.js";
import { parseIconValue } from "../pickers/helpers.js";
import { createIconGallery } from "../pickers/icon-gallery.js";
import { el, hasFocus, nextId, paintTag, segmented } from "./dom.js";
import {
  OFFLINE_FALLBACKS,
  OFFLINE_FALLBACK_TYPES,
  entryAction,
  hasOfflineState,
  isFieldModified,
  liveInfo,
  modifiedFields,
  resetAllLook,
  resetField,
} from "./entry.js";
import { createPreviewSlot, fetchResolvedLook, maybeStartIdleAnimation, playPressAnimation, stopSidebarAnimPreview } from "./preview.js";

/** Readable name of an icon value: "lucide:skip-forward" -> "skip forward", a file -> its name. */
function iconName(v) {
  const p = parseIconValue(v);
  const raw = p.slug || p.path || p.url || String(v);
  return String(raw).split(/[\\/]/).pop().replace(/\.[a-z0-9]+$/i, "").replace(/[-_]+/g, " ");
}

const BG_GRADIENT = ["background_gradient_from", "background_gradient_to", "background_gradient_angle"];
const FG_GRADIENT = ["text_gradient_from", "text_gradient_to", "text_gradient_angle"];

/**
 * `ctx`: { cid, ui, entry(), spec(), edit(mutate, opts), lang() }. `ui` survives refreshes of the same
 * key (Customize open, which picker is open).
 */
export function createAppearanceStep(ctx) {
  const { cid, ui } = ctx;
  const id = nextId("insp-look");
  let look = null;
  let renderTimer = null;
  let renderSeq = 0;

  const root = el("section", { class: "insp-step insp-step-look", "aria-labelledby": `${id}-h` });
  const heading = el("h3", { id: `${id}-h` }, el("b", { "aria-hidden": "true", text: "2" }), el("span", { text: t("inspector.step2.title") }));
  const empty = el(
    "div",
    { class: "insp-empty" },
    el("strong", { text: t("inspector.step2.empty.title") }),
    el("span", { text: t("inspector.step2.empty.hint") }),
  );

  // --- summary row: big preview + text ---------------------------------------------------------
  const bigImg = el("img", { alt: t("inspector.look.preview_alt"), hidden: true });
  const bigEmpty = el("span", { class: "insp-big-empty", "aria-hidden": "true" });
  const big = el("figure", { class: "insp-big" }, bigImg, bigEmpty);
  if (ctx.kind === "strip") big.classList.add("is-strip");
  const sumTitle = el("strong", { class: "insp-look-title" });
  const sumSub = el("span", { class: "insp-look-sub" });
  const btnCustomize = el("button", { type: "button", class: "btn-link", "aria-expanded": "false", "aria-controls": `${id}-custom` });
  const btnResetAll = el("button", { type: "button", class: "btn-link", text: t("inspector.look.reset_all") });
  const sep = el("span", { class: "insp-sep", "aria-hidden": "true", text: "·" });
  const summary = el(
    "div",
    { class: "insp-look" },
    big,
    el("div", { class: "insp-look-text" }, sumTitle, sumSub, el("div", { class: "insp-look-actions" }, btnCustomize, sep, btnResetAll)),
  );

  // --- live pair -------------------------------------------------------------------------------
  const onImg = el("img", { alt: "" });
  const offImg = el("img", { alt: "" });
  const onCap = el("figcaption", { text: t("inspector.live.online") });
  const offCap = el("figcaption", { text: t("inspector.live.offline") });
  const pair = el(
    "div",
    { class: "insp-pair", hidden: true },
    el("figure", {}, onImg, onCap),
    el("figure", {}, offImg, offCap),
    el("span", { class: "hint", text: t("inspector.live.hint") }),
  );

  // --- overflow warning --------------------------------------------------------------------------
  const btnFixIcon = el("button", { type: "button", class: "btn btn-sm", text: t("inspector.overflow.icon") });
  const btnFixShorten = el("button", { type: "button", class: "btn btn-sm", text: t("inspector.overflow.shorten") });
  const warn = el(
    "div",
    { class: "msg-warn insp-warn", role: "status", hidden: true },
    el("span", { text: t("inspector.overflow") }),
    el("span", { class: "insp-warn-fixes" }, btnFixIcon, btnFixShorten),
  );

  // --- customisable fields ---------------------------------------------------------------------
  const custom = el("div", { class: "insp-custom", id: `${id}-custom`, hidden: true });
  const rows = {};

  function row(field, labelKey, ...controls) {
    const lid = `${id}-${field}-l`;
    const tag = el("span", { class: "tag proposed" });
    const node = el(
      "div",
      { class: "insp-row", "data-field": field },
      el("div", { class: "insp-row-head" }, el("span", { class: "insp-row-label", id: lid, text: t(labelKey) }), tag),
      ...controls,
    );
    rows[field] = { node, tag, label: t(labelKey), lid };
    custom.append(node);
    return lid;
  }

  // content mode
  const modeSeg = segmented(
    [
      ["text", t("inspector.mode.text")],
      ["both", t("inspector.mode.both")],
      ["icon", t("inspector.mode.icon")],
    ],
    `${id}-mode-l`,
    (v) => ctx.edit((e) => (e.mode = v)),
  );
  row("mode", "inspector.field.mode", modeSeg.root);

  // label
  const labelInput = el("input", { type: "text", id: `${id}-label`, autocomplete: "off", spellcheck: "false" });
  row("label", "inspector.field.label", labelInput);
  labelInput.setAttribute("aria-labelledby", `${id}-label-l`);
  labelInput.addEventListener("input", () => {
    const v = labelInput.value.trim();
    ctx.edit(
      (e) => {
        delete e.label;
        if (v) e.text = v;
        else delete e.text;
      },
      { typing: true },
    );
  });

  // icon / background / text colour: a summary line + an inline picker opened on demand
  const pops = {};
  function pickRow(field, labelKey) {
    const tile = el("span", { class: "insp-tile", "aria-hidden": "true" });
    const value = el("code", { class: "insp-value mono" });
    const toggle = el("button", { type: "button", class: "btn btn-sm", "aria-expanded": "false", "aria-controls": `${id}-${field}-pop`, text: t("inspector.field.change") });
    const pop = el("div", { class: "insp-pop", id: `${id}-${field}-pop`, hidden: true });
    const lid = row(field, labelKey, el("div", { class: "insp-pick" }, tile, value, toggle), pop);
    toggle.setAttribute("aria-describedby", lid);
    toggle.addEventListener("click", () => setPop(ui.pop === field ? null : field, true));
    pop.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape") {
        ev.stopPropagation();
        setPop(null);
        toggle.focus();
      }
    });
    pops[field] = { tile, value, toggle, pop, picker: null };
  }
  pickRow("icon", "inspector.field.icon");
  pickRow("bg", "inspector.field.bg");
  pickRow("fg", "inspector.field.fg");

  function ensurePicker(field) {
    const p = pops[field];
    if (p.picker) return p.picker;
    if (field === "icon") {
      p.picker = createIconGallery(p.pop, {
        value: (look && look.icon) || "",
        onChange: (v) =>
          ctx.edit((e) => {
            if (v) {
              e.icon = v;
              delete e.image;
            } else resetField(e, "icon");
          }),
      });
    } else {
      const isBg = field === "bg";
      p.picker = createColorPicker(p.pop, {
        value: look ? (isBg ? look.bg : look.fg) : "",
        against: look ? (isBg ? look.fg : look.bg) : "",
        onChange: (hex) =>
          ctx.edit((e) => {
            // A plain colour replaces a gradient on the same layer (otherwise it would stay hidden).
            for (const k of isBg ? BG_GRADIENT : FG_GRADIENT) delete e[k];
            e[isBg ? "background" : "text_color"] = hex;
          }),
      });
    }
    return p.picker;
  }

  function setPop(field, focus = false) {
    ui.pop = field;
    for (const [f, p] of Object.entries(pops)) {
      const open = f === field;
      p.pop.hidden = !open;
      p.toggle.setAttribute("aria-expanded", open ? "true" : "false");
      p.toggle.textContent = t(open ? "inspector.field.done" : "inspector.field.change");
      if (open) {
        const picker = ensurePicker(f);
        if (focus && picker.focus) requestAnimationFrame(() => picker.focus());
      }
    }
  }

  // offline fallback (live keys whose runtime honours it)
  const fbSeg = segmented(
    OFFLINE_FALLBACKS.map((v) => [v, t(`inspector.live.fallback.${v}`)]),
    `${id}-fallback-l`,
    (v) =>
      ctx.edit((e) => {
        const a = entryAction(e);
        if (a) a.offline_fallback = v;
      }),
  );
  row("fallback", "inspector.live.fallback", fbSeg.root);

  root.append(heading, empty, summary, pair, warn, custom);

  // --- behaviour -------------------------------------------------------------------------------
  btnCustomize.addEventListener("click", () => {
    ui.customOpen = !ui.customOpen;
    paintCustomize();
    if (ui.customOpen) {
      const first = custom.querySelector("button, input");
      if (first) first.focus();
    }
  });
  btnResetAll.addEventListener("click", () => ctx.edit((e) => resetAllLook(e)));
  btnFixIcon.addEventListener("click", () => ctx.edit((e) => (e.mode = "icon")));
  btnFixShorten.addEventListener("click", () => focusLabel());

  function focusLabel() {
    ui.customOpen = true;
    paintCustomize();
    if (look && !labelInput.value) labelInput.value = look.label || "";
    labelInput.focus();
    labelInput.select();
  }

  function paintCustomize() {
    custom.hidden = !ui.customOpen;
    btnCustomize.setAttribute("aria-expanded", ui.customOpen ? "true" : "false");
    btnCustomize.textContent = t(ui.customOpen ? "inspector.look.close" : "inspector.look.customize");
  }

  const main = createPreviewSlot(bigImg, {
    onResult: ({ overflow, empty: none }) => {
      bigEmpty.hidden = !none;
      warn.hidden = !overflow;
    },
  });
  const online = createPreviewSlot(onImg);
  const offline = createPreviewSlot(offImg);

  function applyLook(l) {
    look = l;
    modeSeg.set(l.mode || "");
    labelInput.placeholder = l.label || t("inspector.field.label_placeholder");
    const icon = l.icon || "";
    if (icon) renderIcon(pops.icon.tile, icon);
    else pops.icon.tile.textContent = "";
    pops.icon.tile.classList.toggle("is-empty", !icon);
    pops.icon.value.textContent = icon ? iconName(icon) : t("inspector.field.no_icon");
    pops.icon.value.title = icon;
    for (const f of ["bg", "fg"]) {
      const v = l[f] || "";
      pops[f].tile.style.background = v || "transparent";
      pops[f].tile.classList.toggle("is-empty", !v);
      pops[f].value.textContent = v || t("inspector.field.default_colour");
    }
    if (pops.icon.picker) pops.icon.picker.setValue(icon);
    if (pops.bg.picker) {
      pops.bg.picker.setValue(l.bg || "");
      pops.bg.picker.setAgainst(l.fg || "");
    }
    if (pops.fg.picker) {
      pops.fg.picker.setValue(l.fg || "");
      pops.fg.picker.setAgainst(l.bg || "");
    }
    btnFixIcon.hidden = !icon;
  }

  async function render() {
    const my = ++renderSeq;
    const e = ctx.entry();
    const lookP = fetchResolvedLook(e, ctx.lang()).catch(() => null);
    const jobs = [main.show(e, cid)];
    const l = await lookP;
    if (my !== renderSeq) return;
    if (l) applyLook(l);
    if (!pair.hidden) {
      // A sample value (the proposed label, e.g. "Scene") shows how a live value will look.
      const sample = (l && l.label) || "";
      jobs.push(online.show(e, cid, { liveValue: sample }), offline.show(e, cid, { offline: true, liveValue: sample }));
    }
    await Promise.all(jobs);
    if (my !== renderSeq) return;
    maybeStartIdleAnimation(main, e, cid);
  }

  function scheduleRender(delay = 120) {
    clearTimeout(renderTimer);
    renderTimer = setTimeout(() => void render(), delay);
  }

  function sync() {
    const e = ctx.entry();
    const a = entryAction(e);
    const spec = ctx.spec();
    const type = (a && a.type) || "";
    const mods = modifiedFields(e);
    const active = !!a || mods.length > 0;
    root.classList.toggle("is-dim", !active);
    empty.hidden = active;
    for (const n of [summary, custom]) n.hidden = !active;
    if (!active) {
      warn.hidden = true;
      pair.hidden = true;
      stopSidebarAnimPreview();
      return;
    }
    paintCustomize();

    const live = liveInfo(spec);
    pair.hidden = !(live && hasOfflineState(type));
    rows.label.node.hidden = !!live; // a live key's text comes from its source
    rows.fallback.node.hidden = !(live && OFFLINE_FALLBACK_TYPES.has(type));

    if (mods.length) {
      sumTitle.textContent = t("inspector.look.custom", { count: mods.length });
      sumSub.textContent = a ? t("inspector.look.rest_follows") : "";
    } else {
      sumTitle.textContent = t("inspector.look.proposed_title");
      sumSub.textContent = spec ? t("inspector.look.proposed_for", { action: spec.label || type }) : "";
    }
    btnResetAll.hidden = sep.hidden = mods.length === 0;

    for (const f of ["mode", "label", "icon", "bg", "fg"]) {
      const r = rows[f];
      paintTag(r.tag, isFieldModified(e, f), r.label, () => ctx.edit((x) => resetField(x, f)));
    }
    const fb = a && a.offline_fallback ? String(a.offline_fallback) : "";
    paintTag(rows.fallback.tag, !!fb, rows.fallback.label, () =>
      ctx.edit((x) => {
        const xa = entryAction(x);
        if (xa) delete xa.offline_fallback;
      }),
    );
    fbSeg.set(fb || "dash");
    if (!hasFocus(labelInput)) labelInput.value = isFieldModified(e, "label") ? String(e.text || e.label || "") : "";
    setPop(ui.pop || null);
    scheduleRender();
  }

  return {
    root,
    sync,
    focusLabel,
    playPress: () => void playPressAnimation(main, ctx.entry(), cid),
    destroy() {
      clearTimeout(renderTimer);
      renderSeq += 1;
      stopSidebarAnimPreview();
      main.dispose();
      online.dispose();
      offline.dispose();
      for (const p of Object.values(pops)) if (p.picker) p.picker.destroy();
    },
  };
}
