/*
 * services/spotify.js — Services → Spotify: client id / redirect URI, connection status (card pill,
 * Connect / Disconnect button), connect / disconnect, OAuth return query.
 */

import { state } from "../state.js";
import { $ } from "../util.js";
import { setServiceState } from "./cards.js";

export function syncSpotifyFromCfg() {
  const sp = (state.cfg && state.cfg.spotify) || {};
  const cid = $("#spotifyClientId");
  const redir = $("#spotifyRedirectUri");
  if (cid) cid.value = sp.client_id || "";
  if (redir) {
    redir.value = sp.redirect_uri || `${window.location.origin}/api/spotify/callback`;
  }
}

let lastSpotify = null;

/** Update the card's pill, its Connect / Disconnect button and the status line. */
function showSpotifyState(j) {
  lastSpotify = j;
  const line = $("#spotifyStatusLine");
  const connectBtn = $("#btnSpotifyConnect");
  const disconnectBtn = $("#btnSpotifyDisconnect");
  const hasOwnApp = !!(state.cfg && state.cfg.spotify && state.cfg.spotify.client_id);
  let text;
  let mode;
  if (!j) {
    mode = "idle";
    text = t("status.unreachable");
  } else if (!j.configured) {
    mode = "idle";
    text = t("svc.spotify.state.no_app");
  } else if (!j.connected) {
    mode = "bad";
    text = t("status.not_connected");
  } else {
    mode = "ok";
    text = t("status.connected");
  }
  if (line) {
    if (!j) line.textContent = "";
    else if (!j.configured) line.textContent = t("svc.spotify.line.no_app");
    else if (!j.connected) line.textContent = t("svc.spotify.line.not_connected");
    else line.textContent = j.user ? t("svc.spotify.line.connected_as", { user: j.user }) : t("status.connected");
  }
  if (connectBtn) connectBtn.hidden = !!(j && j.connected);
  if (disconnectBtn) disconnectBtn.hidden = !(j && j.connected);
  // The header chip only appears once Spotify is in use (connected, or a Client ID was entered).
  setServiceState("spotify", mode, text, !!(j && (j.connected || hasOwnApp)));
}

/** Redraw from the last answer (language change). */
export function redrawSpotifyState() {
  showSpotifyState(lastSpotify);
}

export async function refreshSpotifyStatus() {
  try {
    const r = await fetch("/api/spotify/status");
    if (!r.ok) {
      showSpotifyState(null);
      return;
    }
    showSpotifyState(await r.json());
  } catch {
    showSpotifyState(null);
  }
}

async function saveSpotifySettings() {
  const errEl = $("#spotifyErrorLine");
  if (errEl) {
    errEl.hidden = true;
    errEl.textContent = "";
  }
  try {
    const r = await fetch("/api/spotify/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        client_id: ($("#spotifyClientId") && $("#spotifyClientId").value.trim()) || "",
        redirect_uri: ($("#spotifyRedirectUri") && $("#spotifyRedirectUri").value.trim()) || "",
      }),
    });
    if (!r.ok) throw new Error(await r.text());
    const j = await r.json();
    if (!state.cfg.spotify) state.cfg.spotify = {};
    Object.assign(state.cfg.spotify, j.spotify || {});
    await refreshSpotifyStatus();
  } catch (e) {
    if (errEl) {
      errEl.hidden = false;
      errEl.textContent = String(e);
    }
  }
}

export function handleSpotifyReturnQuery() {
  const params = new URLSearchParams(window.location.search);
  const errEl = $("#spotifyErrorLine");
  if (params.get("spotify") === "connected") {
    const next = window.location.pathname + (window.location.hash || "");
    history.replaceState({}, "", next);
    void refreshSpotifyStatus();
  }
  const err = params.get("spotify_error");
  if (err) {
    const next = window.location.pathname + (window.location.hash || "");
    history.replaceState({}, "", next);
    if (errEl) {
      errEl.hidden = false;
      errEl.textContent = err;
    }
  }
}

/** Services → Spotify: save, connect, disconnect. */
export function wireSpotifyButtons() {
  const btnSpotifySave = $("#btnSpotifySave");
  if (btnSpotifySave) btnSpotifySave.addEventListener("click", () => void saveSpotifySettings());
  const btnSpotifyConnect = $("#btnSpotifyConnect");
  if (btnSpotifyConnect) {
    btnSpotifyConnect.addEventListener("click", () => {
      window.location.href = "/api/spotify/login";
    });
  }
  const btnSpotifyDisconnect = $("#btnSpotifyDisconnect");
  if (btnSpotifyDisconnect) {
    btnSpotifyDisconnect.addEventListener("click", () => {
      void (async () => {
        try {
          const r = await fetch("/api/spotify/disconnect", { method: "POST" });
          if (!r.ok) throw new Error(await r.text());
          await refreshSpotifyStatus();
        } catch (e) {
          const errEl = $("#spotifyErrorLine");
          if (errEl) {
            errEl.hidden = false;
            errEl.textContent = String(e);
          }
        }
      })();
    });
  }
}
