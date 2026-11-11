/*
 * status.js — Header status chips (device / OBS / Home Assistant, plus Spotify / Twitch once set up) and
 * the 1.5 s /api/status poll, which also feeds the connected device (the edited model may change), the
 * agent's current page and per-control render errors back into the UI. A chip is actionable: it opens
 * the matching Services card.
 */

import { loadDeviceModels } from "./model.js";
import { syncPageLedColors, syncUiToAgentPage } from "./pages.js";
import { getServiceState, setServiceState } from "./services/cards.js";
import { refreshSpotifyStatus } from "./services/spotify.js";
import { refreshTwitchStatus } from "./services/twitch.js";
import { goToService } from "./shell.js";
import { emit, state } from "./state.js";
import { $ } from "./util.js";

let statusPollTimer = null;
let pollTick = 0;
/** Spotify / Twitch are asked about every N polls (Spotify's profile call is a remote request). */
const SLOW_SERVICE_EVERY = 6;
/** Last device chip content, so a language change can redraw it without a new request. */
let lastStatus = null;
/** Which device the agent had at the previous poll (model reloaded when it changes). */
let lastDeviceKey = null;

/**
 * mode: "ok" (connected), "bad" (needs attention: shows the call to action), "idle" (not set up / off).
 * `action` is the short call to action shown inside the chip when it is not ok.
 */
function setChip(id, { mode, action = "", title = "", show = true }) {
  const chip = document.getElementById(id);
  if (!chip) return;
  chip.hidden = !show;
  chip.classList.toggle("ok", mode === "ok");
  chip.classList.toggle("bad", mode === "bad");
  const em = chip.querySelector(".chip-action");
  if (em) em.textContent = mode === "ok" ? "" : action;
  chip.title = title;
}

function serviceChip(id, svc) {
  const st = getServiceState(svc);
  if (!st) return;
  const action = st.mode === "ok" ? "" : t(st.mode === "bad" ? "common.connect" : "common.configure");
  setChip(id, { mode: st.mode, action, title: st.text, show: st.show });
}

function updateDeviceChip(usb) {
  const name = state.model ? state.model.name : "Loupedeck";
  const nameEl = document.querySelector("#chipDevice .chip-name");
  if (nameEl) nameEl.textContent = name;
  if (usb.disabled) {
    setChip("chipDevice", { mode: "idle", action: t("status.device.simulation"), title: t("status.device.simulation_title") });
  } else if (usb.connected) {
    setChip("chipDevice", { mode: "ok", title: t("status.device.connected", { path: usb.path || usb.detail || "" }) });
  } else {
    setChip("chipDevice", { mode: "bad", action: t("status.device.not_found"), title: t("status.device.not_found_title") });
  }
}

/** OBS / Home Assistant block of /api/status -> card pill + header chip. */
function updateConnection(svc, chipId, block) {
  let mode;
  let text;
  if (!block.configured) {
    mode = "idle";
    text = t("status.not_configured");
  } else if (block.connected) {
    mode = "ok";
    text = t("status.connected");
  } else {
    mode = "bad";
    text = t("status.offline");
  }
  setServiceState(svc, mode, text);
  const action = mode === "ok" ? "" : t(mode === "bad" ? "common.connect" : "common.configure");
  setChip(chipId, { mode, action, title: block.url ? `${text} — ${block.url}` : text });
}

function renderServiceChips() {
  serviceChip("chipSpotify", "spotify");
  serviceChip("chipTwitch", "twitch");
}

/** Redraw every chip from the last known data (after a language change). */
export function renderStatusChips() {
  if (lastStatus) {
    updateDeviceChip(lastStatus.usb || {});
    updateConnection("obs", "chipObs", lastStatus.obs || {});
    updateConnection("ha", "chipHa", lastStatus.ha || {});
  }
  renderServiceChips();
}

async function refreshConnectionStatus() {
  try {
    const r = await fetch("/api/status");
    if (!r.ok) return;
    const j = await r.json();
    lastStatus = j;
    emit("status:updated", j);

    // A device was plugged / unplugged / switched: the edited model may change with it.
    const deviceKey = `${j.deck_layout || ""}|${!!(j.usb && j.usb.connected)}`;
    if (lastDeviceKey !== null && deviceKey !== lastDeviceKey) {
      if (await loadDeviceModels()) emit("model:changed");
    }
    lastDeviceKey = deviceKey;

    updateDeviceChip(j.usb || {});
    updateConnection("obs", "chipObs", j.obs || {});
    updateConnection("ha", "chipHa", j.ha || {});
    renderServiceChips();

    if (typeof j.page_index === "number") {
      syncUiToAgentPage(j.page_index);
    }
    syncPageLedColors();
    // Render errors of the bindings on the page shown, by control id (the deck outlines them).
    state.controlErrors = j.control_errors && typeof j.control_errors === "object" ? j.control_errors : {};
    document.querySelectorAll("#deckRoot .dk-ctl").forEach((n) => {
      const err = state.controlErrors[n.dataset.cid];
      n.classList.toggle("has-error", !!err);
      if (err) n.title = err;
    });
  } catch {
    for (const id of ["chipDevice", "chipObs", "chipHa"]) setChip(id, { mode: "idle", title: t("status.unreachable") });
  }
  pollTick += 1;
  if (pollTick % SLOW_SERVICE_EVERY === 0) {
    void refreshSpotifyStatus();
    void refreshTwitchStatus();
  }
}

export function startConnectionStatusPolling() {
  if (!$("#connBar")) return;
  document.querySelectorAll("#connBar .pill").forEach((chip) => {
    chip.addEventListener("click", () => goToService(chip.dataset.svc));
  });
  void refreshSpotifyStatus();
  void refreshTwitchStatus();
  void refreshConnectionStatus();
  if (statusPollTimer) clearInterval(statusPollTimer);
  statusPollTimer = setInterval(refreshConnectionStatus, 1500);
}
