/*
 * services/spotify.js — Services → Spotify: client id / redirect URI, connection status, connect /
 * disconnect, OAuth return query.
 */

import { state } from "../state.js";
import { $ } from "../util.js";

export function syncSpotifyFromCfg() {
  const sp = (state.cfg && state.cfg.spotify) || {};
  const cid = $("#spotifyClientId");
  const redir = $("#spotifyRedirectUri");
  if (cid) cid.value = sp.client_id || "";
  if (redir) {
    redir.value = sp.redirect_uri || `${window.location.origin}/api/spotify/callback`;
  }
}

export async function refreshSpotifyStatus() {
  const line = $("#spotifyStatusLine");
  try {
    const r = await fetch("/api/spotify/status");
    if (!r.ok) {
      if (line) line.textContent = "";
      return;
    }
    const j = await r.json();
    if (!line) return;
    if (!j.configured) {
      line.textContent =
        "No built-in Spotify app in this build: open Advanced and enter your own Client ID.";
    } else if (!j.connected) {
      line.textContent = "Configured — not connected. Click Connect with Spotify.";
    } else {
      line.textContent = j.user ? `Connected as ${j.user}.` : "Connected.";
    }
  } catch {
    if (line) line.textContent = "";
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
