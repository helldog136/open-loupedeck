/*
 * onboarding.js — First launch: a welcome card inside the deck area (starter packs + "Start blank") while
 * the config has no configured key, then a dismissible "next steps" checklist (connect the services the
 * chosen pack uses). Packs come from GET /api/packs and are applied client-side as ONE undo step;
 * only empty keys / knob roles are filled. Persistence: cfg.onboarding_done (dismissed) and
 * cfg.onboarding_pack (which pack was applied, so the checklist knows what to ask for).
 */

import { control, ensurePages, entryActions, kindOf } from "./model.js";
import { scheduleAutosave } from "./save.js";
import { getServiceState } from "./services/cards.js";
import { goToService } from "./shell.js";
import { emit, on, state } from "./state.js";
import { snapshotBeforeAction } from "./undo.js";
import { $ } from "./util.js";

const BLANK_ID = "blank";

/** @type {{key: string, packs: object[]} | null} */
let packCache = null;
let renderToken = 0;

function lang() {
  return (window.i18n && window.i18n.lang) || "";
}

/** Packs are fitted server-side to the edited model (keys outside its grid are dropped). */
function cacheKey() {
  return `${lang()}|${state.model ? state.model.id : ""}`;
}

const hasAction = (e) => entryActions(e).length > 0;

/**
 * True when the user configured something: an action on any page, or a global binding other than the
 * default "buttons open their page" ones every new config starts with.
 */
export function hasConfiguredKey(cfg = state.cfg) {
  for (const p of cfg.pages || []) {
    if (Object.values((p && p.controls) || {}).some((e) => hasAction(e) || (e && e.rotate))) return true;
  }
  return Object.values(cfg.global || {}).some((e) => {
    const acts = entryActions(e);
    return acts.some((a) => a.type !== "agent.goto_page") || !!(e && e.rotate);
  });
}

async function loadPacks() {
  const key = cacheKey();
  if (packCache && packCache.key === key) return packCache.packs;
  const q = new URLSearchParams();
  if (lang()) q.set("lang", lang());
  if (state.model) q.set("model", state.model.id);
  const r = await fetch(`/api/packs?${q}`);
  if (!r.ok) throw new Error(`packs: HTTP ${r.status}`);
  const j = await r.json();
  packCache = { key, packs: j.packs || [] };
  return packCache.packs;
}

/**
 * Fill what is empty from `pack` (pages already fitted to the edited model, keyed by control id);
 * ONE undo snapshot. Only a key without an action / a knob without a role is filled. Emits
 * config:replaced to re-sync every view.
 */
export function applyPack(pack) {
  snapshotBeforeAction();
  ensurePages();
  (pack.pages || []).forEach((src, i) => {
    const page = state.cfg.pages[i];
    if (!page) return;
    for (const [cid, entry] of Object.entries(src.controls || {})) {
      if (!control(cid)) continue;
      const cur = page.controls[cid];
      const empty = kindOf(cid) === "knob" ? !cur : !hasAction(cur);
      if (empty) page.controls[cid] = JSON.parse(JSON.stringify(entry));
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
  if (packCache && packCache.key === cacheKey()) show();
  else loadPacks().then(show, () => {});
}

export function wireOnboarding() {
  on("status:updated", updateChecklist);
  document.addEventListener("i18n:change", () => {
    packCache = null;
    renderOnboarding();
  });
}
