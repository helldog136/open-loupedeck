/*
 * pickers/icon-gallery.js — icon chooser (step 2 of the key inspector).
 *
 *   const g = createIconGallery(container, { value, onChange });
 *   g.setValue(v)   g.focus()   g.destroy()
 *
 * Four tabs: "Common" (curated Lucide icons from icons.json, searchable, category chips), "Brand" (Simple Icons
 * slug -> `si:<slug>`), "WoW" (World of Warcraft icon *names* from wow-icons.json, grouped and searchable, plus a
 * free field for any other name or Wowhead icon link -> `wow:<name>`; images are Blizzard's and only ever loaded
 * from the CDN) and "Other…" (any icon URI the server understands: `heroicons:24/solid/heart`, `mdi:home`,
 * `https://….svg`, or an uploaded image via POST /api/upload). The value is exactly what the config's `icon`
 * field stores (`lucide:play`, `si:obsstudio`, `wow:inv_misc_rune_01`, `library/images/ab12_logo.png`).
 * onChange(value) fires on user picks.
 */

import { WOW_NAME, isIconUri, normalizeHex, parseIconValue, rankItems } from "./helpers.js";
import { el, nextId, onLanguageChange, renderIcon, tr } from "./common.js";

const ICONS_URL = new URL("./icons.json", import.meta.url).href;
const WOW_URL = new URL("./wow-icons.json", import.meta.url).href;
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

// Names only (no images): the WoW tab previews them from Wowhead's CDN, like the other tabs do with theirs.
let wowPromise = null;
function loadWow() {
  if (!wowPromise) {
    wowPromise = fetch(WOW_URL)
      .then((r) => (r.ok ? r.json() : null))
      .catch(() => null);
  }
  return wowPromise;
}

export function createIconGallery(container, opts = {}) {
  const { onChange = () => {} } = opts;
  let value = opts.value || "";
  let tab = /^wow:/i.test(value) ? "wow" : "common";
  let cat = "all";
  let query = "";
  let icons = [];
  let wowData = null;
  const id = nextId("pk-ig");

  const current = el("div", { class: "pk-current" });
  const tabs = el("div", { class: "seg pk-tabs", role: "tablist" });
  const body = el("div", { class: "pk-ig-body" });
  const root = el("div", { class: "pk-ig" }, current, tabs, body);
  container.append(root);

  const TABS = [
    ["common", "picker.icon.tab.common", "Common"],
    ["brand", "picker.icon.tab.brand", "Brand"],
    ["wow", "picker.icon.tab.wow", "WoW"],
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
      if (/^wow:/i.test(q)) {
        wowDraft = q.replace(/^wow:/i, "");
        tab = "wow";
        query = "";
        paintTabs();
        return paintBody();
      }
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

  /* ---------------------------------------------------------------- WoW */

  let wowDraft = "";
  let wowCat = "misc";
  let wowQuery = "";
  const WOW_SEARCH_MAX = 96;

  /** A bare name, `wow:<name>` or a Wowhead icon URL -> `wow:<name>` (or "" when it is not a valid name). */
  function wowValue(input) {
    let s = String(input || "").trim();
    const fromUrl = s.match(/\/icons\/(?:tiny|small|medium|large)\/([A-Za-z0-9_]+)\.(?:jpg|png)/i);
    if (fromUrl) s = fromUrl[1];
    s = s.replace(/^wow:/i, "").trim().toLowerCase();
    return WOW_NAME.test(s) && s.length <= 96 ? `wow:${s}` : "";
  }

  /** Load a tile's image only when it scrolls into view, so opening a category never floods the CDN. */
  function lazyIcon(host, v) {
    if (typeof IntersectionObserver !== "function") return renderIcon(host, v);
    const io = new IntersectionObserver((entries) => {
      if (!entries.some((e) => e.isIntersecting)) return;
      io.disconnect();
      renderIcon(host, v);
    });
    io.observe(host);
  }

  function wowTile(name) {
    const v = `wow:${name}`;
    const b = el("button", { type: "button", class: "pk-ic", "data-value": v, "aria-pressed": v === value ? "true" : "false", title: name, "aria-label": name });
    lazyIcon(b, v);
    b.addEventListener("click", () => choose(v));
    return b;
  }

  function paintWow() {
    const data = wowData || { categories: [], keywords: {} };
    const catLabel = (cid) => tr(`picker.icon.wow.cat.${cid}`, cid);
    const searchLabel = tr("picker.icon.wow.search", "Search WoW icons (hearthstone, fireball, mount…)");
    const search = el("input", { type: "search", class: "pk-search", autocomplete: "off", spellcheck: "false", value: wowQuery, "aria-label": searchLabel, placeholder: searchLabel });
    const chips = el("div", { class: "chips pk-chips", role: "group", "aria-label": tr("picker.icon.categories", "Categories") });
    for (const c of data.categories) {
      const b = el("button", { type: "button", "aria-pressed": wowCat === c.id ? "true" : "false", text: catLabel(c.id) });
      b.addEventListener("click", () => {
        wowCat = c.id;
        wowQuery = search.value = "";
        chips.querySelectorAll("button").forEach((n) => n.setAttribute("aria-pressed", n === b ? "true" : "false"));
        fill();
      });
      chips.append(b);
    }
    const grid = el("div", { class: "pk-grid", role: "group", "aria-label": tr("picker.icon.tab.wow", "WoW") });
    const count = el("div", { class: "hint pk-count", "aria-live": "polite" });

    const input = el("input", { type: "text", class: "pk-input mono", value: wowDraft, placeholder: "inv_misc_rune_01", autocomplete: "off", spellcheck: "false", "aria-label": tr("picker.icon.wow.paste", "Icon name or Wowhead icon link") });
    const preview = el("span", { class: "pk-ic-big" });
    const use = el("button", { type: "button", class: "btn btn-primary btn-sm", text: tr("picker.icon.use", "Use this icon") });
    const hint = el("p", { class: "hint", text: tr("picker.icon.wow.hint", "Icons are Blizzard's: they are downloaded when needed and kept on this PC, never bundled. To use any other icon, paste its name: the file name in a Wowhead icon link (…/icons/large/inv_misc_rune_01.jpg gives inv_misc_rune_01).") });
    let previewed = null;
    const sync = () => {
      const v = wowValue(input.value);
      use.disabled = !v;
      if (v === previewed) return;
      previewed = v;
      preview.className = "pk-ic-big";
      if (v) renderIcon(preview, v);
      else {
        preview.textContent = "";
        preview.classList.add("is-empty");
      }
    };
    input.addEventListener("input", () => {
      wowDraft = input.value;
      sync();
    });
    const go = () => {
      const v = wowValue(input.value);
      if (v) choose(v);
    };
    use.addEventListener("click", go);
    input.addEventListener("keydown", (e) => e.key === "Enter" && (e.preventDefault(), go()));

    function fill() {
      grid.textContent = "";
      let names;
      let capped = false;
      if (wowQuery.trim()) {
        const all = data.categories.flatMap((c) => c.icons.map((name) => ({ name, cat: c.id })));
        names = rankItems(all, wowQuery, (i) => ({ label: i.name.replace(/_/g, " "), category: catLabel(i.cat), keywords: data.keywords[i.name] || [] })).map((i) => i.name);
        if (names.length > WOW_SEARCH_MAX) {
          names = names.slice(0, WOW_SEARCH_MAX);
          capped = true;
        }
      } else {
        names = (data.categories.find((c) => c.id === wowCat) || { icons: [] }).icons;
      }
      for (const n of names) grid.append(wowTile(n));
      const note = capped ? ` — ${tr("picker.icon.wow.capped", "refine your search to see more")}` : "";
      count.textContent = names.length ? tr("picker.icon.count", `${names.length} icons`, { count: names.length }) + note : "";
      if (!names.length) {
        grid.append(el("div", { class: "pk-empty" }, el("strong", { text: tr("picker.icon.empty.title", "No icon found") }), el("span", { text: tr("picker.icon.wow.empty", "Paste the icon name below instead.") })));
      }
    }
    search.addEventListener("input", () => {
      wowQuery = search.value;
      fill();
    });
    search.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        const first = grid.querySelector(".pk-ic");
        if (first) (e.preventDefault(), first.click());
      } else if (e.key === "Escape" && wowQuery) {
        e.stopPropagation();
        search.value = wowQuery = "";
        fill();
      }
    });
    body.append(search, chips, grid, count, el("div", { class: "pk-gname", text: tr("picker.icon.wow.other", "Any other icon") }), el("div", { class: "pk-form-row" }, preview, input, use), hint);
    sync();
    fill();
  }

  function paintBody() {
    body.textContent = "";
    body.setAttribute("role", "tabpanel");
    if (tab === "wow") paintWow();
    else if (tab === "brand") paintBrand();
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
  loadWow().then((data) => {
    wowData = data && Array.isArray(data.categories) ? data : null;
    if (tab === "wow" && root.isConnected) paintBody();
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
