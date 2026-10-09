/*
 * services/twitch.js — Services → Twitch: account list (cfg.twitch), device-code connect, disconnect,
 * status.
 */

import { cancelPendingAutosave, runAutosave, scheduleAutosave } from "../save.js";
import { state } from "../state.js";
import { $, escapeAttr } from "../util.js";
import { setServiceState } from "./cards.js";

export function ensureTwitch() {
  const t = state.cfg && state.cfg.twitch;
  if (Array.isArray(t)) {
    state.cfg.twitch = t.filter((x) => x && typeof x === "object");
    return;
  }
  if (t && typeof t === "object") {
    state.cfg.twitch = [t];
    return;
  }
  state.cfg.twitch = [];
}

/** The UI shows one implicit account when none is configured; materialize it on first edit. */
function ensureTwitchAccount(ix) {
  ensureTwitch();
  while (state.cfg.twitch.length <= ix) state.cfg.twitch.push({});
}

let lastTwitchRows = null;

/** True when at least one account has something filled in (the header chip is shown from then on). */
function twitchInUse() {
  return (state.cfg.twitch || []).some((a) => a && Object.values(a).some((v) => String(v || "").trim()));
}

function showTwitchState(rows) {
  lastTwitchRows = rows;
  const main = $("#btnTwitchMain");
  const connected = (rows || []).filter((r) => r.connected);
  let mode;
  let text;
  if (!rows) {
    mode = "idle";
    text = t("status.unreachable");
  } else if (connected.length === 0) {
    mode = "bad";
    text = t("status.not_connected");
  } else {
    mode = "ok";
    text = connected.length === 1 && connected[0].login ? connected[0].login : t("svc.twitch.accounts", { count: connected.length });
  }
  if (main) {
    main.hidden = !!rows && rows.length > 0 && connected.length === rows.length;
    main.textContent = t(rows && rows.length > 1 ? "svc.twitch.connect_account" : "common.connect");
  }
  setServiceState("twitch", mode, text, !!rows && (connected.length > 0 || twitchInUse()));
}

/** Redraw from the last answer (language change). */
export function redrawTwitchState() {
  showTwitchState(lastTwitchRows);
}

export async function refreshTwitchStatus() {
  try {
    const j = await (await fetch("/api/twitch/status")).json();
    const rows = j.accounts || [];
    document.querySelectorAll(".twitch-acct").forEach((fs) => {
      const row = rows.find((a) => a.index === Number(fs.dataset.ix));
      const line = fs.querySelector(".twitch-conn-line");
      if (!line || !row) return;
      line.textContent = row.connected
        ? row.login
          ? t("svc.twitch.line.connected_as", { user: row.login })
          : t("status.connected")
        : t("svc.twitch.line.not_connected");
    });
    showTwitchState(rows);
  } catch {
    showTwitchState(null);
  }
}

/** The card's main button: connect the first account that is not connected yet. */
export function wireTwitchMainButton() {
  const main = $("#btnTwitchMain");
  if (!main) return;
  main.addEventListener("click", () => {
    const rows = lastTwitchRows || [];
    const target = rows.find((r) => !r.connected);
    const fieldsets = [...document.querySelectorAll(".twitch-acct")];
    const fs = fieldsets.find((f) => Number(f.dataset.ix) === (target ? target.index : 0)) || fieldsets[0];
    if (fs) void connectTwitchAccount(fs);
  });
}

async function connectTwitchAccount(fs) {
  const line = fs && fs.querySelector(".twitch-conn-line");
  const errEl = $("#twitchErrorLine");
  if (errEl) errEl.hidden = true;
  const index = Number(fs.dataset.ix);
  const post = (path) =>
    fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ index }),
    });
  try {
    // The server reads the account (client_id override, label) from the saved config.
    cancelPendingAutosave();
    await runAutosave();
    const r = await post("/api/twitch/device/start");
    if (!r.ok) throw new Error((await r.json()).detail || (await r.text()));
    const info = await r.json();
    if (line) line.textContent = t("svc.twitch.line.approve", { code: info.user_code });
    const deadline = Date.now() + info.expires_in * 1000;
    while (Date.now() < deadline) {
      await new Promise((res) => setTimeout(res, Math.max(2, info.interval) * 1000));
      const p = await (await post("/api/twitch/device/poll")).json();
      if (p.status === "connected") break;
      if (p.status !== "pending") throw new Error(p.detail || p.status);
    }
  } catch (e) {
    if (errEl) {
      errEl.hidden = false;
      errEl.textContent = String(e.message || e);
    }
  }
  void refreshTwitchStatus();
}

export function renderTwitchAccounts() {
  ensureTwitch();
  const mount = $("#twitchAccountsMount");
  if (!mount) return;
  const rows = state.cfg.twitch && state.cfg.twitch.length ? state.cfg.twitch : [{}];
  mount.innerHTML = rows
    .map((acct, i) => {
      const a = acct && typeof acct === "object" ? acct : {};
      const cid = a.client_id || "";
      const cs = a.client_secret || "";
      const tok = a.access_token || "";
      const label = a.label || "";
      return `
        <fieldset class="twitch-acct" data-ix="${i}">
          <legend>${escapeAttr(t("svc.twitch.account", { number: i + 1 }))}</legend>
          <p class="hint twitch-conn-line">…</p>
          <div class="row gap-row">
            <button type="button" class="btn btn-sm btnTwitchConnect">${t("common.connect")}</button>
            <button type="button" class="btn btn-sm btnTwitchDisconnect">${t("common.disconnect")}</button>
            <button type="button" class="btn btn-sm btn-ghost btnRemoveTwitchAccount">${t("svc.twitch.remove")}</button>
          </div>
          <details class="adv-json">
            <summary>${t("svc.twitch.advanced")}</summary>
            <p class="hint">${t("svc.twitch.own_app_help")}</p>
            <label class="row">${t("svc.twitch.label")}</label>
            <input class="full-width" data-tw="label" value="${escapeAttr(label)}" />
            <label class="row">${t("svc.twitch.client_id")}</label>
            <input class="full-width mono" data-tw="client_id" value="${escapeAttr(cid)}" spellcheck="false" />
            <label class="row">${t("svc.twitch.client_secret")}</label>
            <input type="password" class="full-width mono" data-tw="client_secret" value="${escapeAttr(cs)}" />
            <label class="row">${t("svc.twitch.access_token")}</label>
            <input type="password" class="full-width mono" data-tw="access_token" value="${escapeAttr(tok)}" />
          </details>
        </fieldset>`;
    })
    .join("");

  mount.querySelectorAll("input[data-tw]").forEach((el) => {
    el.addEventListener("input", () => {
      const fs = el.closest(".twitch-acct");
      if (!fs) return;
      const ix = Number(fs.dataset.ix);
      const key = el.dataset.tw;
      if (!Number.isFinite(ix)) return;
      ensureTwitchAccount(ix);
      state.cfg.twitch[ix][key] = el.value;
      scheduleAutosave();
    });
  });
  mount.querySelectorAll(".btnTwitchConnect").forEach((btn) => {
    btn.addEventListener("click", () => void connectTwitchAccount(btn.closest(".twitch-acct")));
  });
  mount.querySelectorAll(".btnTwitchDisconnect").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const fs = btn.closest(".twitch-acct");
      await fetch("/api/twitch/disconnect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ index: Number(fs.dataset.ix) }),
      });
      void refreshTwitchStatus();
    });
  });
  void refreshTwitchStatus();
  mount.querySelectorAll(".btnRemoveTwitchAccount").forEach((btn) => {
    btn.addEventListener("click", () => {
      const fs = btn.closest(".twitch-acct");
      if (!fs) return;
      const ix = Number(fs.dataset.ix);
      if (!Number.isFinite(ix)) return;
      state.cfg.twitch.splice(ix, 1);
      renderTwitchAccounts();
      scheduleAutosave();
    });
  });
}

/** Services → Twitch: add an account. */
export function wireTwitchAddButton() {
  const btnAddTwitch = $("#btnAddTwitchAccount");
  if (btnAddTwitch) {
    btnAddTwitch.addEventListener("click", () => {
      ensureTwitch();
      if (!state.cfg.twitch.length) state.cfg.twitch.push({}); // the implicit first account
      state.cfg.twitch.push({});
      renderTwitchAccounts();
      scheduleAutosave();
    });
  }
}
