/*
 * status.js — Connection status pills (USB / OBS / Home Assistant) and the 1.5 s /api/status poll,
 * which also feeds the agent's deck layout, current page and per-key render errors back into the UI.
 */

import { ensurePages } from "./model.js";
import { syncPageSelect, syncUiToAgentPage, updateLiveSPageChrome } from "./pages.js";
import { state } from "./state.js";

let statusPollTimer = null;

function setConnBadge(el, mode, text) {
  if (!el) return;
  el.textContent = text;
  el.classList.remove("ok", "offline", "muted");
  el.classList.add(mode);
}

async function refreshConnectionStatus() {
  const usbBadge = document.getElementById("stUsbBadge");
  const usbPath = document.getElementById("stUsbPath");
  const obsBadge = document.getElementById("stObsBadge");
  const obsMeta = document.getElementById("stObsMeta");
  const haBadge = document.getElementById("stHaBadge");
  const haMeta = document.getElementById("stHaMeta");
  if (!usbBadge || !obsBadge) return;
  try {
    const r = await fetch("/api/status");
    if (!r.ok) return;
    const j = await r.json();
    const usb = j.usb || {};
    if (usb.disabled) {
      setConnBadge(usbBadge, "muted", "Disabled");
      if (usbPath) usbPath.textContent = "";
    } else if (usb.connected) {
      setConnBadge(usbBadge, "ok", "Connected");
      if (usbPath) usbPath.textContent = usb.path || usb.detail || "";
    } else {
      setConnBadge(usbBadge, "offline", "Offline");
      if (usbPath) usbPath.textContent = usb.path || usb.detail || "";
    }

    const obs = j.obs || {};
    if (!obs.configured) {
      setConnBadge(obsBadge, "muted", "Not configured");
      if (obsMeta) obsMeta.textContent = "";
    } else if (obs.connected) {
      setConnBadge(obsBadge, "ok", "Connected");
      if (obsMeta) obsMeta.textContent = obs.url || "";
    } else {
      setConnBadge(obsBadge, "offline", "Offline");
      if (obsMeta) obsMeta.textContent = obs.url || obs.detail || "";
    }

    if (haBadge) {
      const ha = j.ha || {};
      if (!ha.configured) {
        setConnBadge(haBadge, "muted", "Not configured");
        if (haMeta) haMeta.textContent = "";
      } else if (ha.connected) {
        setConnBadge(haBadge, "ok", "Connected");
        if (haMeta) haMeta.textContent = ha.url || "";
      } else {
        setConnBadge(haBadge, "offline", "Offline");
        if (haMeta) haMeta.textContent = ha.url || ha.detail || "";
      }
    }

    const prevLayout = state.agentDeckLayout;
    if (j.deck_layout === "live" || j.deck_layout === "live_s") {
      state.agentDeckLayout = j.deck_layout;
    } else {
      state.agentDeckLayout = null;
    }
    if (prevLayout !== state.agentDeckLayout) {
      ensurePages();
      updateLiveSPageChrome();
      syncPageSelect();
    }

    if (typeof j.page_index === "number") {
      syncUiToAgentPage(j.page_index);
    }
    state.touchErrors = j.touch_errors && typeof j.touch_errors === "object" ? j.touch_errors : {};
    // Update outlines without waiting for a full re-render.
    document.querySelectorAll(".cell").forEach((el) => {
      const cid = el && el.dataset && el.dataset.cid;
      if (cid && typeof cid === "string" && cid.startsWith("touch_") && state.touchErrors[cid]) {
        el.classList.add("error-outline");
        el.title = `${cid} — ${state.touchErrors[cid]}`;
      } else if (el) {
        el.classList.remove("error-outline");
      }
    });
  } catch {
    setConnBadge(usbBadge, "muted", "…");
    setConnBadge(obsBadge, "muted", "…");
    if (haBadge) setConnBadge(haBadge, "muted", "…");
  }
}

export function startConnectionStatusPolling() {
  if (!document.getElementById("connBar")) return;
  void refreshConnectionStatus();
  if (statusPollTimer) clearInterval(statusPollTimer);
  statusPollTimer = setInterval(refreshConnectionStatus, 1500);
}
