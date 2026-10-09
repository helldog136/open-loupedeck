/*
 * pickers/action-picker.js — searchable, grouped action list (step 1 of the key inspector).
 *
 *   const p = createActionPicker(container, { catalog, value, onChange, lang });
 *   p.setValue(type)   p.focus()   p.destroy()
 *
 * `catalog` is the `actions` array of GET /api/action_catalog. `onChange(type, action)` fires only on user picks.
 * Labels arrive already translated from the server (`?lang=`); categories are slugs shown through `category.<slug>` when
 * translated (falling back to the slug). Re-feed the catalog with setCatalog() on language change. Recent picks (5) and
 * favourites live in localStorage; both are optional and silently skipped when storage is unavailable.
 */

import { actionKeywords, normalize, pushRecent, rankItems } from "./helpers.js";
import { el, loadJSON, nextId, onLanguageChange, renderIcon, saveJSON, tr } from "./common.js";

const KEY_RECENT = "olp.picker.actions.recent";
const KEY_FAV = "olp.picker.actions.favourites";
const RECENT_MAX = 5;

function slug(s) {
  return normalize(s).replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "");
}

export function createActionPicker(container, opts = {}) {
  const { onChange = () => {}, lang } = opts;
  let catalog = Array.isArray(opts.catalog) ? opts.catalog : [];
  let value = opts.value || "";
  let query = "";
  let activeIndex = -1;
  let recent = loadJSON(KEY_RECENT, []).filter((x) => typeof x === "string");
  let favourites = loadJSON(KEY_FAV, []).filter((x) => typeof x === "string");
  const id = nextId("pk-ap");

  const search = el("input", {
    type: "search",
    class: "pk-search",
    role: "combobox",
    "aria-expanded": "true",
    "aria-controls": `${id}-list`,
    "aria-autocomplete": "list",
    autocomplete: "off",
    spellcheck: "false",
  });
  const hint = el("kbd", { class: "pk-kbd", "aria-hidden": "true", text: "/" });
  const list = el("div", { class: "pk-list", role: "listbox", id: `${id}-list` });
  const root = el("div", { class: "pk-ap" }, el("div", { class: "pk-search-wrap" }, search, hint), list);
  container.append(root);

  const labelOf = (a) => (lang && a.labels && a.labels[lang]) || a.label || a.type;
  const categoryOf = (a) => tr(`category.${a.category}`, a.category || "");
  const lookOf = (a) => a.default_look || {};
  const byType = (type) => catalog.find((a) => a.type === type);
  const fieldsOf = (a) => ({
    label: `${labelOf(a)} ${a.label || ""}`,
    category: `${categoryOf(a)} ${a.category || ""}`,
    keywords: a._kw || (a._kw = actionKeywords(a)),
  });

  function applyI18n() {
    search.placeholder = tr("picker.action.search", "Search an action…");
    search.setAttribute("aria-label", tr("picker.action.search", "Search an action…"));
  }

  function rowFor(a, optionId) {
    const look = lookOf(a);
    const dot = el("span", { class: "pk-dot", "aria-hidden": "true" });
    dot.style.background = look.bg || "var(--surface-2)";
    dot.style.color = look.fg || "#fff";
    if (look.icon) renderIcon(dot, look.icon);
    const fav = favourites.includes(a.type);
    const main = el(
      "button",
      {
        type: "button",
        class: "pk-act",
        role: "option",
        id: optionId,
        tabindex: "-1",
        "data-type": a.type,
        "aria-selected": a.type === value ? "true" : "false",
      },
      dot,
      el("span", { class: "pk-act-text" }, el("span", { class: "pk-act-label", text: labelOf(a) }), el("span", { class: "pk-act-cat", text: categoryOf(a) })),
    );
    main.addEventListener("click", () => choose(a));
    const star = el("button", {
      type: "button",
      class: "pk-star",
      tabindex: "-1",
      "aria-pressed": fav ? "true" : "false",
      "aria-label": tr(fav ? "picker.action.unfavourite" : "picker.action.favourite", fav ? "Remove from favourites" : "Add to favourites"),
      title: tr(fav ? "picker.action.unfavourite" : "picker.action.favourite", fav ? "Remove from favourites" : "Add to favourites"),
      text: fav ? "★" : "☆",
    });
    star.addEventListener("click", (e) => {
      e.stopPropagation();
      toggleFavourite(a.type);
    });
    return el("div", { class: "pk-row" }, main, star);
  }

  function groups() {
    const q = query.trim();
    if (q) {
      const hits = rankItems(catalog, q, fieldsOf);
      return hits.length ? [{ name: tr("picker.action.results", "Results"), items: hits, flat: true }] : [];
    }
    const out = [];
    const favItems = favourites.map(byType).filter(Boolean);
    if (favItems.length) out.push({ name: tr("picker.action.favourites", "Favourites"), items: favItems, special: true });
    const recItems = recent.map(byType).filter(Boolean);
    if (recItems.length) out.push({ name: tr("picker.action.recent", "Recent"), items: recItems, special: true });
    const order = [];
    const map = new Map();
    for (const a of catalog) {
      const c = categoryOf(a);
      if (!map.has(c)) {
        map.set(c, []);
        order.push(c);
      }
      map.get(c).push(a);
    }
    for (const c of order) out.push({ name: c, items: map.get(c) });
    return out;
  }

  let optionIds = []; // [{ id, action }] in display order

  function render(keepScroll = true) {
    const top = keepScroll ? list.scrollTop : 0;
    list.textContent = "";
    optionIds = [];
    const gs = groups();
    if (!gs.length) {
      list.append(
        el("div", { class: "pk-empty" }, el("strong", { text: tr("picker.action.empty.title", "No action found") }), el("span", { text: tr("picker.action.empty.hint", "Try another word, or clear the search.") })),
      );
      search.removeAttribute("aria-activedescendant");
      activeIndex = -1;
      return;
    }
    let n = 0;
    for (const g of gs) {
      const sec = el("div", { class: "pk-group", role: "group" });
      if (!g.flat) {
        const nameId = `${id}-g${n}`;
        sec.append(el("div", { class: "pk-gname", id: nameId, text: g.name }));
        sec.setAttribute("aria-labelledby", nameId);
      }
      for (const a of g.items) {
        const oid = `${id}-o${n++}`;
        sec.append(rowFor(a, oid));
        optionIds.push({ id: oid, action: a });
      }
      list.append(sec);
    }
    // Active row: keep it if still there, otherwise the current value, otherwise the first match when searching.
    const cur = optionIds.findIndex((o) => o.action.type === value);
    if (activeIndex < 0 || activeIndex >= optionIds.length) activeIndex = query.trim() ? 0 : cur;
    if (query.trim() && activeIndex < 0) activeIndex = 0;
    paintActive(false);
    list.scrollTop = top;
  }

  function paintActive(scroll = true) {
    list.querySelectorAll(".pk-act.is-active").forEach((n) => n.classList.remove("is-active"));
    const o = optionIds[activeIndex];
    if (!o) return search.removeAttribute("aria-activedescendant");
    const node = document.getElementById(o.id);
    if (node) {
      node.classList.add("is-active");
      search.setAttribute("aria-activedescendant", o.id);
      if (scroll) node.scrollIntoView({ block: "nearest" });
    }
  }

  function choose(a) {
    value = a.type;
    recent = pushRecent(recent, a.type, RECENT_MAX);
    saveJSON(KEY_RECENT, recent);
    // Do not re-render the list (the Recent block would jump under the pointer): just move the selection mark.
    list.querySelectorAll(".pk-act").forEach((n) => n.setAttribute("aria-selected", n.dataset.type === value ? "true" : "false"));
    const idx = optionIds.findIndex((o) => o.action.type === a.type);
    if (idx >= 0) activeIndex = idx;
    paintActive(false);
    onChange(a.type, a);
  }

  function toggleFavourite(type) {
    favourites = favourites.includes(type) ? favourites.filter((x) => x !== type) : [...favourites, type];
    saveJSON(KEY_FAV, favourites);
    const activeType = optionIds[activeIndex]?.action.type;
    render();
    const idx = optionIds.findIndex((o) => o.action.type === activeType);
    if (idx >= 0) activeIndex = idx;
    paintActive(false);
  }

  function move(delta) {
    if (!optionIds.length) return;
    activeIndex = activeIndex < 0 ? (delta > 0 ? 0 : optionIds.length - 1) : (activeIndex + delta + optionIds.length) % optionIds.length;
    paintActive();
  }

  search.addEventListener("input", () => {
    query = search.value;
    activeIndex = -1;
    hint.hidden = !!query;
    render(false);
  });
  search.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") (e.preventDefault(), move(1));
    else if (e.key === "ArrowUp") (e.preventDefault(), move(-1));
    else if (e.key === "Enter") {
      const o = optionIds[activeIndex];
      if (o) (e.preventDefault(), choose(o.action));
    } else if (e.key === "Escape") {
      if (query) {
        e.preventDefault();
        e.stopPropagation();
        search.value = "";
        query = "";
        hint.hidden = false;
        activeIndex = -1;
        render(false);
      } else search.blur();
    }
  });

  const onDocKey = (e) => {
    if (e.key !== "/" || e.ctrlKey || e.metaKey || e.altKey) return;
    const t = e.target;
    const editing = t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName));
    if (editing || !root.isConnected || root.offsetParent === null) return;
    e.preventDefault();
    search.focus();
    search.select();
  };
  document.addEventListener("keydown", onDocKey);
  const offLang = onLanguageChange(() => {
    applyI18n();
    render();
  });

  applyI18n();
  render(false);
  requestAnimationFrame(() => {
    const sel = list.querySelector('.pk-act[aria-selected="true"]');
    if (sel) sel.scrollIntoView({ block: "nearest" });
  });

  return {
    setValue(v) {
      value = v || "";
      activeIndex = -1;
      render();
    },
    setCatalog(next) {
      catalog = Array.isArray(next) ? next : [];
      activeIndex = -1;
      render();
    },
    focus() {
      search.focus();
    },
    destroy() {
      document.removeEventListener("keydown", onDocKey);
      offLang();
      root.remove();
    },
  };
}
