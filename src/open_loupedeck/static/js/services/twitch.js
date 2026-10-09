/*
 * services/twitch.js — Services → Twitch: account list (cfg.twitch), device-code connect, disconnect,
 * status.
 */

import { cancelPendingAutosave, runAutosave, scheduleAutosave } from "../save.js";
import { state } from "../state.js";
import { $, escapeAttr } from "../util.js";

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

async function refreshTwitchStatus() {
  try {
    const j = await (await fetch("/api/twitch/status")).json();
    document.querySelectorAll(".twitch-acct").forEach((fs) => {
      const row = (j.accounts || []).find((a) => a.index === Number(fs.dataset.ix));
      const line = fs.querySelector(".twitch-conn-line");
      if (!line || !row) return;
      line.textContent = row.connected
        ? `Connected${row.login ? ` as ${row.login}` : ""}.`
        : "Not connected — click Connect with Twitch.";
    });
  } catch {
    /* status is cosmetic */
  }
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
    if (line) line.textContent = `Approve on twitch.tv (code ${info.user_code}) — waiting…`;
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
          <legend>Account ${i + 1}</legend>
          <p class="hint small twitch-conn-line">…</p>
          <div class="row gap-row">
            <button type="button" class="btnTwitchConnect">Connect with Twitch</button>
            <button type="button" class="btnTwitchDisconnect">Disconnect</button>
            <button type="button" class="btnRemoveTwitchAccount">Remove</button>
          </div>
          <details class="adv-json">
            <summary>
              Advanced
              <span class="info-tip" tabindex="0" title="Only needed if the built-in Twitch app is suspended or you want your own. Create a free app at dev.twitch.tv/console (Client type: Public, OAuth Redirect URL: http://localhost), paste its Client ID below. See docs/configuration.md.">&#9432;</span>
            </summary>
            <p class="hint small">Want your own Twitch app? Create one at dev.twitch.tv/console with client type
              <em>Public</em> and redirect URL <code>http://localhost</code>, then paste its Client ID here.</p>            <label class="row">Label (to tell two logins apart)</label>
            <input class="full-width" data-tw="label" value="${escapeAttr(label)}" />
            <label class="row">Own app: Client ID (empty = built-in app)</label>
            <input class="full-width mono" data-tw="client_id" value="${escapeAttr(cid)}" spellcheck="false" />
            <label class="row">Client secret (stream-status keys only)</label>
            <input type="password" class="full-width mono" data-tw="client_secret" value="${escapeAttr(cs)}" />
            <label class="row">Access token (optional)</label>
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
