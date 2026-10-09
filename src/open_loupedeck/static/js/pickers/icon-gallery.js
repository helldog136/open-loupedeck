/*
 * pickers/icon-gallery.js — icon chooser (step 2 of the key inspector).
 *
 *   const g = createIconGallery(container, { value, onChange });
 *   g.setValue(v)   g.focus()   g.destroy()
 *
 * Three tabs: "Common" (curated Lucide icons from icons.json, searchable, category chips), "Brand" (Simple Icons
 * slug -> `si:<slug>`) and "Other…" (any icon URI the server understands: `heroicons:24/solid/heart`, `mdi:home`,
 * `https://….svg`, or an uploaded image via POST /api/upload). The value is exactly what the config's `icon`
 * field stores (`lucide:play`, `si:obsstudio`, `library/images/ab12_logo.png`). onChange(value) fires on user picks.
 */

import { isIconUri, normalizeHex, parseIconValue, rankItems } from "./helpers.js";
import { el, nextId, onLanguageChange, renderIcon, tr } from "./common.js";

const ICONS_URL = new URL("./icons.json", import.meta.url).href;
const CATEGORIES = ["media", "audio", "stream", "home", "comm", "arrows", "system", "status", "fun", "shapes"];
const BRANDS = ["obsstudio", "twitch", "youtube", "spotify", "discord", "github", "homeassistant", "steam", "x", "tiktok", "elgato", "philipshue", "netflix", "vlc", "reddit", "kick", "instagram", "facebook", "whatsapp", "telegram"];

let iconsPromise = null;
function loadIcons() {
  if (!iconsPromise) {
    iconsPromise = fetch(ICONS_URL)
      .then((r) => (r.ok ? r.json() : []))
      .catch(() => []);
  }
  return iconsPromise;
}

export function createIconGallery(container, opts = {}) {
  const { onChange = () => {} } = opts;
  let value = opts.value || "";
  let tab = "common";
  let cat = "all";
  let query = "";
  let icons = [];
  const id = nextId("pk-ig");

  const current = el("div", { class: "pk-current" });
  const tabs = el("div", { class: "seg pk-tabs", role: "tablist" });
  const body = el("div", { class: "pk-ig-body" });
  const root = el("div", { class: "pk-ig" }, current, tabs, body);
  container.append(root);

  const TABS = [
    ["common", "picker.icon.tab.common", "Common"],
    ["brand", "picker.icon.tab.brand", "Brand"],
    ["other", "picker.icon.tab.other", "Other…"],
  ];

  function choose(v) {
    value = v;
    paintCurrent();
    body.querySelectorAll(".pk-ic").forEach((n) => n.setAttribute("aria-pressed", n.dataset.value === value ? "true" : "false"));
    onChange(v);
  }

  function paintCurrent() {
    current.textContent = "";
    const tile = el("span", { class: "pk-ic-big" });
    if (value) renderIcon(tile, value);
    else tile.classList.add("is-empty");
    const clear = el("button", { type: "button", class: "btn-link pk-clear", text: tr("picker.icon.clear", "No icon") });
    clear.hidden = !value;
    clear.addEventListener("click", () => choose(""));
    current.append(
      tile,
      el(
        "span",
        { class: "pk-current-text" },
        el("span", { class: "pk-current-label", text: tr("picker.icon.current", "Current icon") }),
        el("code", { class: "pk-current-value mono", text: value || tr("picker.icon.none", "none") }),
      ),
      clear,
    );
  }

  function paintTabs() {
    tabs.textContent = "";
    for (const [key, i18n, fb] of TABS) {
      const b = el("button", { type: "button", role: "tab", "aria-selected": tab === key ? "true" : "false", text: tr(i18n, fb) });
      b.addEventListener("click", () => {
        tab = key;
        paintTabs();
        paintBody();
      });
      tabs.append(b);
    }
  }

  /* ---------------------------------------------------------------- Common */

  function tile(name) {
    const v = `lucide:${name}`;
    const b = el("button", { type: "button", class: "pk-ic", "data-value": v, "aria-pressed": v === value ? "true" : "false", title: name, "aria-label": name });
    renderIcon(b, v);
    b.addEventListener("click", () => choose(v));
    return b;
  }

  function paintCommon() {
    const search = el("input", { type: "search", class: "pk-search", autocomplete: "off", spellcheck: "false", value: query, "aria-label": tr("picker.icon.search", "Search icons (play, mic, light…)"), placeholder: tr("picker.icon.search", "Search icons (play, mic, light…)") });
    const chips = el("div", { class: "chips pk-chips", role: "group", "aria-label": tr("picker.icon.categories", "Categories") });
    const mk = (key, label) => {
      const b = el("button", { type: "button", "aria-pressed": cat === key ? "true" : "false", text: label });
      b.addEventListener("click", () => {
        cat = key;
        chips.querySelectorAll("button").forEach((n) => n.setAttribute("aria-pressed", n === b ? "true" : "false"));
        fill();
      });
      chips.append(b);
    };
    mk("all", tr("picker.icon.cat.all", "All"));
    for (const c of CATEGORIES) mk(c, tr(`picker.icon.cat.${c}`, c));
    const grid = el("div", { class: "pk-grid", role: "group", "aria-label": tr("picker.icon.tab.common", "Common") });
    const count = el("div", { class: "hint pk-count", "aria-live": "polite" });
    body.append(search, chips, grid, count);

    function fill() {
      grid.textContent = "";
      let items = icons.filter((i) => cat === "all" || i.cat === cat);
      if (query.trim()) {
        // A pasted URI (si:obs, mdi:home, https://…) is handled by the other tabs.
        items = rankItems(items, query, (i) => ({ label: i.name.replace(/-/g, " "), category: "", keywords: i.keywords }));
      }
      for (const i of items) grid.append(tile(i.name));
      count.textContent = items.length ? tr("picker.icon.count", `${items.length} icons`, { count: items.length }) : "";
      if (!items.length) {
        grid.append(el("div", { class: "pk-empty" }, el("strong", { text: tr("picker.icon.empty.title", "No icon found") }), el("span", { text: tr("picker.icon.empty.hint", "Try the Brand or Other… tab.") })));
      }
    }
    search.addEventListener("input", () => {
      query = search.value;
      const q = query.trim();
      if (isIconUri(q) && /^[a-z]+:/i.test(q)) {
        // Typed a URI: hand it over to the right tab.
        brandDraft = /^(si|simpleicons):/i.test(q) ? q.replace(/^[a-z]+:/i, "") : brandDraft;
        otherDraft = /^(si|simpleicons):/i.test(q) ? otherDraft : q;
        tab = /^(si|simpleicons):/i.test(q) ? "brand" : "other";
        query = "";
        paintTabs();
        return paintBody();
      }
      fill();
    });
    search.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        const first = grid.querySelector(".pk-ic");
        if (first) (e.preventDefault(), first.click());
      } else if (e.key === "ArrowDown") {
        const first = grid.querySelector(".pk-ic");
        if (first) (e.preventDefault(), first.focus());
      } else if (e.key === "Escape" && query) {
        e.stopPropagation();
        search.value = query = "";
        fill();
      }
    });
    grid.addEventListener("keydown", (e) => {
      const keys = { ArrowRight: 1, ArrowLeft: -1, ArrowDown: "down", ArrowUp: "up" };
      if (!(e.key in keys)) return;
      const all = [...grid.querySelectorAll(".pk-ic")];
      const i = all.indexOf(document.activeElement);
      if (i < 0) return;
      e.preventDefault();
      let step = keys[e.key];
      if (typeof step === "string") {
        const per = Math.max(1, Math.round(grid.clientWidth / (all[0].offsetWidth + 6)));
        step = step === "down" ? per : -per;
      }
      const next = all[Math.min(all.length - 1, Math.max(0, i + step))];
      next?.focus();
    });
    fill();
  }

  /* ---------------------------------------------------------------- Brand */

  let brandDraft = "";
  let brandColor = "";

  function brandValue() {
    const slug = brandDraft.trim().replace(/^(si|simpleicons):/i, "").toLowerCase();
    if (!slug) return "";
    const col = brandColor.trim() ? normalizeHex(brandColor) : null;
    const v = `si:${slug}${col ? `/${col.slice(1)}` : ""}`;
    return parseIconValue(v).kind === "si" ? v : "";
  }

  function paintBrand() {
    const input = el("input", { type: "text", class: "pk-input mono", value: brandDraft, placeholder: "obsstudio", autocomplete: "off", spellcheck: "false", "aria-label": tr("picker.icon.brand.slug", "Brand name (Simple Icons slug)") });
    const colour = el("input", { type: "text", class: "pk-input mono pk-short", value: brandColor, placeholder: "#rrggbb", autocomplete: "off", spellcheck: "false", "aria-label": tr("picker.icon.brand.colour", "Brand colour (optional)") });
    const preview = el("span", { class: "pk-ic-big" });
    const use = el("button", { type: "button", class: "btn btn-primary btn-sm", text: tr("picker.icon.use", "Use this icon") });
    const hint = el("p", { class: "hint", text: tr("picker.icon.brand.hint", "Type the brand name as on simpleicons.org (lowercase, no spaces): obsstudio, twitch, homeassistant… Leave the colour empty to use the key's text colour.") });
    const sugg = el("div", { class: "chips pk-chips" });
    for (const s of BRANDS) {
      const b = el("button", { type: "button", text: s });
      b.addEventListener("click", () => {
        brandDraft = input.value = s;
        sync();
        choose(brandValue());
      });
      sugg.append(b);
    }
    const sync = () => {
      const v = brandValue();
      use.disabled = !v;
      preview.className = "pk-ic-big";
      if (v) renderIcon(preview, v);
      else {
        preview.textContent = "";
        preview.classList.add("is-empty");
      }
    };
    input.addEventListener("input", () => {
      brandDraft = input.value;
      sync();
    });
    colour.addEventListener("input", () => {
      brandColor = colour.value;
      colour.classList.toggle("is-invalid", !!colour.value.trim() && !normalizeHex(colour.value));
      sync();
    });
    const go = () => {
      const v = brandValue();
      if (v) choose(v);
    };
    use.addEventListener("click", go);
    input.addEventListener("keydown", (e) => e.key === "Enter" && (e.preventDefault(), go()));
    body.append(
      el("div", { class: "pk-form-row" }, preview, input, colour, use),
      hint,
      el("div", { class: "pk-gname", text: tr("picker.icon.brand.popular", "Popular") }),
      sugg,
    );
    sync();
  }

  /* ---------------------------------------------------------------- Other */

  let otherDraft = "";
  let otherError = "";

  function paintOther() {
    const input = el("input", { type: "text", class: "pk-input mono", value: otherDraft, placeholder: "heroicons:24/solid/heart", autocomplete: "off", spellcheck: "false", "aria-label": tr("picker.icon.other.uri", "Icon address") });
    const preview = el("span", { class: "pk-ic-big" });
    const use = el("button", { type: "button", class: "btn btn-primary btn-sm", text: tr("picker.icon.use", "Use this icon") });
    const err = el("div", { class: "msg-error", role: "alert", hidden: !otherError, text: otherError });
    const file = el("input", { type: "file", accept: "image/*,.svg", hidden: true });
    const upload = el("button", { type: "button", class: "btn btn-secondary btn-sm", text: tr("picker.icon.other.upload", "Upload an image…") });
    const hint = el("p", { class: "hint", text: tr("picker.icon.other.hint", "Paste an address: heroicons:24/solid/heart, mdi:home, lucide:bell, or a link to an .svg / image. Or upload your own image.") });
    const sync = () => {
      const v = input.value.trim();
      const ok = v && parseIconValue(v).kind !== "invalid" && parseIconValue(v).kind !== "file";
      use.disabled = !ok;
      preview.className = "pk-ic-big";
      if (ok) renderIcon(preview, v);
      else {
        preview.textContent = "";
        preview.classList.add("is-empty");
      }
    };
    input.addEventListener("input", () => {
      otherDraft = input.value;
      otherError = "";
      err.hidden = true;
      sync();
    });
    const go = () => {
      const v = input.value.trim();
      if (v && !use.disabled) choose(v);
    };
    use.addEventListener("click", go);
    input.addEventListener("keydown", (e) => e.key === "Enter" && (e.preventDefault(), go()));
    upload.addEventListener("click", () => file.click());
    file.addEventListener("change", async () => {
      const f = file.files && file.files[0];
      if (!f) return;
      upload.disabled = true;
      upload.textContent = tr("picker.icon.other.uploading", "Uploading…");
      try {
        const fd = new FormData();
        fd.append("file", f);
        const r = await fetch("/api/upload?library=images", { method: "POST", body: fd });
        const data = await r.json().catch(() => ({}));
        if (!r.ok || !data.path) throw new Error(data.detail || `HTTP ${r.status}`);
        otherDraft = data.path;
        input.value = data.path;
        otherError = "";
        err.hidden = true;
        sync();
        choose(data.path);
      } catch (e) {
        otherError = tr("picker.icon.other.error", "Upload failed: {message}", { message: e.message });
        err.textContent = otherError;
        err.hidden = false;
      } finally {
        upload.disabled = false;
        upload.textContent = tr("picker.icon.other.upload", "Upload an image…");
        file.value = "";
      }
    });
    body.append(el("div", { class: "pk-form-row" }, preview, input, use), el("div", { class: "pk-form-row" }, upload, file), err, hint);
    sync();
  }

  function paintBody() {
    body.textContent = "";
    body.setAttribute("role", "tabpanel");
    if (tab === "brand") paintBrand();
    else if (tab === "other") paintOther();
    else paintCommon();
  }

  const offLang = onLanguageChange(() => {
    paintCurrent();
    paintTabs();
    paintBody();
  });

  paintCurrent();
  paintTabs();
  paintBody();
  loadIcons().then((list) => {
    icons = Array.isArray(list) ? list : [];
    if (tab === "common" && root.isConnected) paintBody();
  });

  return {
    setValue(v) {
      value = v || "";
      paintCurrent();
      body.querySelectorAll(".pk-ic").forEach((n) => n.setAttribute("aria-pressed", n.dataset.value === value ? "true" : "false"));
    },
    focus() {
      (body.querySelector("input") || tabs.querySelector("button"))?.focus();
    },
    destroy() {
      offLang();
      root.remove();
    },
  };
}
