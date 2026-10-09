/*
 * onboarding.js — First launch: a welcome card inside the deck area (starter packs + "Start blank") while
 * the config has no configured key, then a dismissible "next steps" checklist (connect the services the
 * chosen pack uses). Packs come from GET /api/packs and are applied client-side as ONE undo step;
 * only empty keys / knob roles are filled. Persistence: cfg.onboarding_done (dismissed) and
 * cfg.onboarding_pack (which pack was applied, so the checklist knows what to ask for).
 */

import { ensurePages, layoutMode } from "./model.js";
import { scheduleAutosave } from "./save.js";
import { getServiceState } from "./services/cards.js";
import { goToService } from "./shell.js";
import { emit, on, state } from "./state.js";
import { snapshotBeforeAction } from "./undo.js";
import { $ } from "./util.js";

const BLANK_ID = "blank";
/** Touch keys of the original Live (4x3); the Live S grid has 15. */
const LIVE_KEY_COUNT = 12;

/** @type {{lang: string, packs: object[]} | null} */
let packCache = null;
let renderToken = 0;

function lang() {
  return (window.i18n && window.i18n.lang) || "";
}

function hasAction(e) {
  return !!e && typeof e === "object" && (!!(e.action && e.action.type) || (Array.isArray(e.actions) && e.actions.length > 0));
}

/** True when any touch key (any page) or global control has an action. */
export function hasConfiguredKey(cfg = state.cfg) {
  for (const p of cfg.pages || []) {
    for (const [cid, e] of Object.entries((p && p.buttons) || {})) {
      if (cid.startsWith("touch_") && hasAction(e)) return true;
    }
  }
  return Object.values(cfg.global_buttons || {}).some(hasAction);
}

async function loadPacks() {
  const code = lang();
  if (packCache && packCache.lang === code) return packCache.packs;
  const r = await fetch(`/api/packs${code ? `?lang=${encodeURIComponent(code)}` : ""}`);
  if (!r.ok) throw new Error(`packs: HTTP ${r.status}`);
  const j = await r.json();
  packCache = { lang: code, packs: j.packs || [] };
  return packCache.packs;
}

/** Fill what is empty from `pack`; ONE undo snapshot. Emits config:replaced to re-sync every view. */
export function applyPack(pack) {
  snapshotBeforeAction();
  ensurePages();
  const maxKeys = layoutMode() === "live" ? LIVE_KEY_COUNT : 15;
  (pack.pages || []).forEach((src, i) => {
    const page = state.cfg.pages[i];
    if (!page) return;
    if (!page.buttons || typeof page.buttons !== "object") page.buttons = {};
    for (const [idx, entry] of Object.entries(src.keys || {})) {
      if (Number(idx) >= maxKeys) continue;
      const cid = `touch_${idx}`;
      if (!hasAction(page.buttons[cid])) page.buttons[cid] = JSON.parse(JSON.stringify(entry));
    }
    const knobs = src.knobs || {};
    if (Object.keys(knobs).length) {
      if (!page.knobs || typeof page.knobs !== "object") page.knobs = {};
      for (const [kid, role] of Object.entries(knobs)) {
        if (!page.knobs[kid]) page.knobs[kid] = JSON.parse(JSON.stringify(role));
      }
    }
  });
  state.cfg.onboarding_pack = pack.id;
  emit("config:replaced", state.pageIndex);
}

function startBlank() {
  state.cfg.onboarding_done = true;
  scheduleAutosave();
  renderOnboarding();
}

function dismissChecklist() {
  state.cfg.onboarding_done = true;
  scheduleAutosave();
  renderOnboarding();
}

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}

function packCard(pack) {
  const card = el("article", "ob-pack");
  card.dataset.pack = pack.id;
  card.append(el("h3", "ob-pack-name", pack.name), el("p", "ob-pack-desc", pack.description));
  const prev = el("div", "ob-pack-preview");
  for (const item of pack.preview || []) {
    const chip = el("span", "ob-chip", item.label);
    if (item.bg) chip.style.background = item.bg;
    if (item.fg) chip.style.color = item.fg;
    prev.append(chip);
  }
  card.append(prev);
  const btn = el("button", "btn btn-primary ob-use", t("onboarding.pack.use"));
  btn.type = "button";
  btn.addEventListener("click", () => applyPack(pack));
  card.append(btn);
  return card;
}

async function renderWelcome(box) {
  const token = ++renderToken;
  const card = el("section", "ob-welcome card");
  card.id = "obWelcome";
  card.append(el("h2", "ob-title", t("onboarding.welcome.title")), el("p", "ob-lead", t("onboarding.welcome.lead")));
  const grid = el("div", "ob-packs");
  card.append(grid);
  const blank = el("button", "btn ob-blank", t("onboarding.welcome.blank"));
  blank.type = "button";
  blank.id = "obStartBlank";
  blank.addEventListener("click", startBlank);
  const foot = el("div", "ob-foot");
  foot.append(blank);
  card.append(foot);
  box.replaceChildren(card);
  try {
    const packs = await loadPacks();
    if (token !== renderToken) return;
    for (const p of packs) if (p.id !== BLANK_ID) grid.append(packCard(p));
  } catch (e) {
    console.warn("starter packs unavailable", e);
  }
}

function stepsFor(packId) {
  const pack = packCache && packCache.packs.find((p) => p.id === packId);
  return pack ? pack.services || [] : [];
}

function renderChecklist(box, services) {
  const card = el("section", "ob-next card");
  card.id = "obChecklist";
  const head = el("div", "ob-next-head");
  head.append(el("h2", "ob-title", t("onboarding.next.title")));
  const close = el("button", "btn btn-sm ob-dismiss", t("onboarding.next.dismiss"));
  close.type = "button";
  close.id = "obDismiss";
  close.addEventListener("click", dismissChecklist);
  head.append(close);
  card.append(head, el("p", "ob-lead", t("onboarding.next.lead")));
  const list = el("ul", "ob-steps");
  for (const svc of services) {
    const li = el("li", "ob-step");
    li.dataset.svc = svc;
    li.append(el("span", "ob-check"), el("span", "ob-step-label", t(`onboarding.step.${svc}`)));
    const go = el("button", "btn btn-sm ob-go", t("onboarding.step.go"));
    go.type = "button";
    go.addEventListener("click", () => goToService(svc));
    li.append(go);
    list.append(li);
  }
  card.append(list, el("p", "ob-alldone", t("onboarding.next.done")));
  box.replaceChildren(card);
  updateChecklist();
}

/** Mark each step done when its service pill is OK (cheap: no rebuild, called after every status poll). */
function updateChecklist() {
  const card = $("#obChecklist");
  if (!card) return;
  let all = true;
  card.querySelectorAll(".ob-step").forEach((li) => {
    const st = getServiceState(li.dataset.svc);
    const ok = !!st && st.mode === "ok";
    li.classList.toggle("done", ok);
    if (!ok) all = false;
  });
  card.classList.toggle("all-done", all);
}

/** Show the right thing for the current config: welcome card, checklist, or nothing. */
export function renderOnboarding() {
  const box = $("#onboardingMount");
  const deck = $("#deckRoot");
  if (!box || !state.cfg || !state.cfg.pages) return;
  const done = state.cfg.onboarding_done === true;
  const configured = hasConfiguredKey();
  const welcome = !done && !configured;
  if (deck) deck.hidden = welcome;
  box.hidden = true;
  if (welcome) {
    box.hidden = false;
    void renderWelcome(box);
    return;
  }
  renderToken++;
  box.replaceChildren();
  const pack = !done && configured ? state.cfg.onboarding_pack : "";
  if (!pack) return;
  const show = () => {
    const services = stepsFor(pack);
    if (!services.length || state.cfg.onboarding_done === true) return;
    box.hidden = false;
    renderChecklist(box, services);
  };
  if (packCache && packCache.lang === lang()) show();
  else loadPacks().then(show, () => {});
}

export function wireOnboarding() {
  on("status:updated", updateChecklist);
  document.addEventListener("i18n:change", () => {
    packCache = null;
    renderOnboarding();
  });
}
