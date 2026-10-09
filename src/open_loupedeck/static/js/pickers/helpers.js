/*
 * pickers/helpers.js — pure, DOM-free helpers shared by the action, icon and colour pickers:
 * accent-insensitive search and ranking, bilingual action keywords, icon URI parsing / preview URLs,
 * colour parsing, hex normalising and WCAG contrast. Nothing here touches the page, so it is easy to test.
 */

/* ------------------------------------------------------------------ text search */

/** Lower-case and strip diacritics ("Éclairage" -> "eclairage"). */
export function normalize(s) {
  return String(s ?? "")
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[’']/g, "'")
    .toLowerCase()
    .trim();
}

export function tokenize(s) {
  return normalize(s)
    .split(/[^a-z0-9]+/)
    .filter(Boolean);
}

/** Bilingual (EN/FR) synonym groups: if the haystack contains any word of a group, all of them match. */
const SYNONYMS = [
  ["mic", "micro", "microphone", "mute", "muet", "couper"],
  ["scene", "scenes", "scène", "obs", "stream"],
  ["light", "lights", "lumiere", "lampe", "ampoule", "eclairage", "bulb", "lamp", "prise", "plug"],
  ["volume", "son", "sound", "audio", "sonore", "speaker", "haut-parleur"],
  ["play", "pause", "lecture", "musique", "music", "spotify", "track", "morceau"],
  ["next", "suivant", "previous", "precedent", "prev", "skip"],
  ["page", "pages", "onglet", "deck", "navigation", "goto"],
  ["clock", "time", "horloge", "heure", "date", "temps"],
  ["twitch", "chat", "live", "direct", "clip", "marker", "raid", "follow"],
  ["home", "assistant", "ha", "maison", "domotique", "lumiere", "lampe", "light", "switch", "interrupteur", "volet", "entity", "entite"],
  ["keyboard", "clavier", "key", "touche", "shortcut", "raccourci", "hotkey"],
  ["http", "web", "request", "requete", "webhook", "url", "api"],
  ["shell", "command", "commande", "terminal", "script", "exec", "run"],
  ["overlay", "alert", "alerte", "superposition", "browser"],
  ["display", "affichage", "afficher", "show", "widget", "weather", "meteo", "battery", "batterie", "cpu"],
  ["record", "recording", "enregistrer", "enregistrement", "rec"],
  ["sound", "sons", "effect", "effet", "sfx", "jouer", "fichier"],
];

const SYN_INDEX = (() => {
  const idx = new Map();
  SYNONYMS.forEach((group, gi) => {
    for (const w of group) {
      const k = normalize(w);
      if (!idx.has(k)) idx.set(k, []);
      idx.get(k).push(gi);
    }
  });
  return idx;
})();

/** Extra searchable words for an action (type pieces + synonyms of every word already present). */
export function actionKeywords(action) {
  const base = tokenize(`${action.type || ""} ${action.label || ""} ${action.category || ""}`);
  const groups = new Set();
  for (const w of base) for (const g of SYN_INDEX.get(w) || []) groups.add(g);
  const out = new Set();
  for (const g of groups) for (const w of SYNONYMS[g]) out.add(normalize(w));
  for (const w of action.keywords || []) out.add(normalize(w));
  return [...out];
}

/**
 * Score one entry against a query (all query tokens must match, otherwise 0).
 * `fields`: { label, category, keywords[] } (any may be empty). Higher is better.
 */
export function scoreEntry(query, fields) {
  const qt = tokenize(query);
  if (!qt.length) return 1;
  const label = normalize(fields.label);
  const labelWords = tokenize(fields.label);
  const cat = normalize(fields.category);
  const catWords = tokenize(fields.category);
  const kws = (fields.keywords || []).map(normalize);
  let total = 0;
  for (const q of qt) {
    let best = 0;
    if (label === q) best = 120;
    else if (label.startsWith(q)) best = 100;
    else if (labelWords.some((w) => w.startsWith(q))) best = 70;
    else if (label.includes(q)) best = 40;
    if (best < 30 && (cat.startsWith(q) || catWords.some((w) => w.startsWith(q)))) best = Math.max(best, 30);
    if (best < 20 && kws.some((k) => k === q)) best = Math.max(best, 25);
    if (best < 20 && kws.some((k) => k.startsWith(q))) best = Math.max(best, 20);
    if (best < 10 && q.length >= 3 && kws.some((k) => k.includes(q))) best = Math.max(best, 10);
    if (!best) return 0;
    total += best;
  }
  return total;
}

/**
 * Rank items for a query. `getFields(item)` returns the scoreEntry fields. Stable: ties keep input order.
 * An empty query returns the items unchanged.
 */
export function rankItems(items, query, getFields) {
  if (!tokenize(query).length) return items.slice();
  return items
    .map((item, i) => ({ item, i, s: scoreEntry(query, getFields(item)) }))
    .filter((x) => x.s > 0)
    .sort((a, b) => b.s - a.s || a.i - b.i)
    .map((x) => x.item);
}

/** Add `value` at the front of a most-recent list (no duplicates, capped at `max`). */
export function pushRecent(list, value, max = 5) {
  if (!value) return list.slice(0, max);
  return [value, ...list.filter((v) => v !== value)].slice(0, max);
}

/* ------------------------------------------------------------------ icons */

// Keep in sync with icon_loader.py (_LUCIDE_VER, _MDI_VER, _HEROICONS_BASE): the browser previews the very
// same CDN files the server rasterises.
export const LUCIDE_VER = "0.446.0";
export const MDI_VER = "7.4.47";
export const HEROICONS_VER = "2.1.5";
const SLUG_SAFE = /^[a-zA-Z0-9._-]+$/;

/**
 * Classify an `icon` config value.
 * Returns { kind: "lucide"|"mdi"|"heroicons"|"si"|"url"|"file"|"empty", slug?, color?, url? }.
 * `url` is what the browser can load directly (null for "file": use previewUrl's `localBase`).
 */
export function parseIconValue(raw) {
  const s = String(raw ?? "").trim();
  if (!s) return { kind: "empty", url: null };
  const low = s.toLowerCase();
  const rest = (n) => s.slice(n).trim();
  if (low.startsWith("lucide:")) {
    const slug = rest(7);
    if (!SLUG_SAFE.test(slug)) return { kind: "invalid", url: null };
    return { kind: "lucide", slug, url: `https://cdn.jsdelivr.net/npm/lucide-static@${LUCIDE_VER}/icons/${slug}.svg` };
  }
  if (low.startsWith("mdi:")) {
    const slug = rest(4);
    if (!SLUG_SAFE.test(slug)) return { kind: "invalid", url: null };
    return { kind: "mdi", slug, url: `https://cdn.jsdelivr.net/npm/@mdi/svg@${MDI_VER}/svg/${slug}.svg` };
  }
  if (low.startsWith("heroicons:")) {
    let path = rest(10).replace(/^\/+/, "");
    if (!path || path.includes("..")) return { kind: "invalid", url: null };
    if (!path.endsWith(".svg")) path += ".svg";
    return { kind: "heroicons", slug: path.replace(/\.svg$/, ""), url: `https://cdn.jsdelivr.net/npm/heroicons@${HEROICONS_VER}/${path}` };
  }
  if (low.startsWith("si:") || low.startsWith("simpleicons:")) {
    const body = s.slice(s.indexOf(":") + 1).trim();
    const parts = body.split("/");
    const slug = parts[0];
    const color = parts.length > 1 ? parts[1].toLowerCase() : "ffffff";
    if (!SLUG_SAFE.test(slug) || parts.length > 2 || !/^[0-9a-f]{6}$/.test(color)) return { kind: "invalid", url: null };
    return { kind: "si", slug, color: parts.length > 1 ? color : null, url: `https://cdn.simpleicons.org/${encodeURIComponent(slug)}/${color}` };
  }
  if (low.startsWith("https://") || low.startsWith("http://")) return { kind: "url", url: s };
  return { kind: "file", url: null, path: s };
}

/** True when the value is something the server understands as an icon URI (not a local file). */
export function isIconUri(raw) {
  const k = parseIconValue(raw).kind;
  return k !== "empty" && k !== "invalid" && k !== "file";
}

/**
 * URL for a browser <img>/mask preview, or null. Local files go through the config server's
 * /api/local-file route (`localBase`, default "/api/local-file").
 */
export function previewUrl(raw, localBase = "/api/local-file") {
  const p = parseIconValue(raw);
  if (p.url) return p.url;
  if (p.kind === "file") return `${localBase}?path=${encodeURIComponent(p.path)}`;
  return null;
}

/** Monochrome sets are drawn in the text colour (mask); Simple Icons with colour and arbitrary files keep theirs. */
export function isTintable(raw) {
  const p = parseIconValue(raw);
  if (p.kind === "lucide" || p.kind === "mdi" || p.kind === "heroicons") return true;
  if (p.kind === "si") return !p.color;
  return false;
}

/** Short text for the offline placeholder tile. */
export function iconInitials(raw) {
  const p = parseIconValue(raw);
  const base = p.slug || p.path || p.url || "";
  const word = String(base).split(/[\\/]/).pop().replace(/\.[a-z0-9]+$/i, "");
  return word.replace(/[^a-zA-Z0-9]/g, "").slice(0, 2).toUpperCase() || "?";
}

/* ------------------------------------------------------------------ colours */

const NAMED = {
  black: "#000000", white: "#ffffff", red: "#ff0000", green: "#008000", blue: "#0000ff", yellow: "#ffff00",
  orange: "#ffa500", purple: "#800080", pink: "#ffc0cb", gray: "#808080", grey: "#808080", cyan: "#00ffff",
  magenta: "#ff00ff", lime: "#00ff00", navy: "#000080", teal: "#008080", maroon: "#800000", olive: "#808000",
  silver: "#c0c0c0", aqua: "#00ffff", fuchsia: "#ff00ff", gold: "#ffd700", brown: "#a52a2a", indigo: "#4b0082",
  violet: "#ee82ee", coral: "#ff7f50", crimson: "#dc143c", turquoise: "#40e0d0", salmon: "#fa8072", tomato: "#ff6347",
  transparent: null,
};

/** Hex ("#abc", "abc", "#aabbcc", "aabbcc") or a known CSS name -> "#rrggbb"; anything else -> null. */
export function normalizeHex(input) {
  let s = String(input ?? "").trim().toLowerCase();
  if (!s) return null;
  if (Object.prototype.hasOwnProperty.call(NAMED, s)) return NAMED[s];
  if (s[0] === "#") s = s.slice(1);
  if (/^[0-9a-f]{3}$/.test(s)) s = s.replace(/./g, (c) => c + c);
  if (/^[0-9a-f]{6}$/.test(s)) return "#" + s;
  return null;
}

/** -> [r,g,b] (0-255) or null. */
export function parseColor(input) {
  const h = normalizeHex(input);
  if (!h) return null;
  return [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
}

export function relativeLuminance(input) {
  const rgb = parseColor(input);
  if (!rgb) return null;
  const [r, g, b] = rgb.map((v) => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** WCAG contrast ratio (1..21) of two colours, or null when either cannot be parsed. */
export function contrastRatio(a, b) {
  const la = relativeLuminance(a);
  const lb = relativeLuminance(b);
  if (la == null || lb == null) return null;
  const [hi, lo] = la >= lb ? [la, lb] : [lb, la];
  return (hi + 0.05) / (lo + 0.05);
}

/** Black or white, whichever reads better on `bg`. */
export function readableOn(bg) {
  const cw = contrastRatio("#ffffff", bg);
  const cb = contrastRatio("#000000", bg);
  if (cw == null) return "#ffffff";
  return cw >= cb ? "#ffffff" : "#000000";
}

export const LOW_CONTRAST = 3;
