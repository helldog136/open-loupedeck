/*
 * virtual/main.js — Boots the stand-alone virtual device page (virtual.html): waits for the
 * translations, then mounts the device component into #virtualDevice.
 */

import { mountVirtualDevice } from "./device.js";

async function boot() {
  try {
    if (window.i18n && window.i18n.ready) await window.i18n.ready;
  } catch {
    /* untranslated labels are better than no device */
  }
  const host = document.getElementById("virtualDevice");
  if (host) window.__virtualDevice = mountVirtualDevice(host, { showStatus: true, showModelSelector: true });
}

boot();
