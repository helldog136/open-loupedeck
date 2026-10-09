/*
 * pickers/common.js — small DOM utilities shared by the pickers: translated-or-fallback text, element builder,
 * guarded localStorage, and the icon preview tile (CDN image, falling back to a text tile when offline).
 */

import { isTintable, previewUrl, iconInitials } from "./helpers.js";

/** t(key) but returns `fallback` when the key has no translation (t() returns the key itself then). */
export function tr(key, fallback, vars) {
  try {
    const f = globalThis.t;
    if (typeof f !== "function") return fallback ?? key;
    const v = f(key, vars);
    return v === key && fallback !== undefined ? fallback : v;
  } catch {
    return fallback ?? key;
  }
}

export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? "" : String(v));
  }
  for (const c of children.flat()) {
    if (c == null || c === false) continue;
    node.append(c.nodeType ? c : document.createTextNode(String(c)));
  }
  return node;
}

export function loadJSON(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    if (raw == null) return fallback;
    const v = JSON.parse(raw);
    return v ?? fallback;
  } catch {
    return fallback;
  }
}

export function saveJSON(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* private mode / blocked storage: pickers keep working without persistence */
  }
}

/** Re-translate a subtree after (re)rendering, and whenever the app language changes. */
export function onLanguageChange(handler) {
  document.addEventListener("i18n:change", handler);
  return () => document.removeEventListener("i18n:change", handler);
}

let uid = 0;
export function nextId(prefix) {
  uid += 1;
  return `${prefix}-${uid}`;
}

const probeCache = new Map(); // url -> "ok" | "fail"

/**
 * Fill `host` (a sized box) with a preview of an icon value. Monochrome icons are painted through a CSS mask in
 * `currentColor`; coloured ones use an <img>. If the image cannot be loaded (offline, bad slug) the host shows a
 * text placeholder (two letters) instead.
 */
export function renderIcon(host, value, { title = "" } = {}) {
  host.textContent = "";
  host.classList.add("pk-ico");
  const url = previewUrl(value);
  const fallback = () => {
    host.textContent = "";
    host.classList.add("is-missing");
    host.append(el("span", { class: "pk-ico-txt", text: iconInitials(value) }));
  };
  host.classList.remove("is-missing");
  if (title) host.title = title;
  if (!url) return fallback();
  const show = () => {
    if (isTintable(value)) {
      const m = el("span", { class: "pk-ico-mask" });
      m.style.setProperty("--pk-mask", `url("${url}")`);
      host.append(m);
    } else {
      host.append(el("img", { src: url, alt: "", loading: "lazy", draggable: "false" }));
    }
  };
  const state = probeCache.get(url);
  if (state === "fail") return fallback();
  if (state === "ok") return show();
  // Probe first, so a failing CDN never leaves a blank tile.
  const probe = new Image();
  probe.onload = () => {
    probeCache.set(url, "ok");
    if (host.isConnected !== false) {
      host.textContent = "";
      show();
    }
  };
  probe.onerror = () => {
    probeCache.set(url, "fail");
    fallback();
  };
  fallback();
  host.classList.remove("is-missing"); // placeholder text shows while probing, without the "missing" tint
  probe.src = url;
}
