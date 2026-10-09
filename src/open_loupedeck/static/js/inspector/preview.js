/*
 * inspector/preview.js — Server-rendered key previews for the inspector: POST /api/preview_key (the
 * device's own renderer, overflow headers), POST /api/resolve_look (proposed/modified look), a
 * preview "slot" that owns one <img> (stale responses dropped, object URLs revoked) and the idle /
 * press animation playback.
 */

import { state } from "../state.js";

/**
 * Render a key like the device does. `opts`: { offline, liveValue, animationFrame, pressElapsedFrames }.
 * Resolves to { blob, overflow, lines } or { blob: null } when there is nothing to draw.
 */
export async function fetchKeyPreview(entry, cid, opts = {}) {
  const body = { entry: entry || {}, control_id: cid || "touch_0" };
  if (opts.offline) body.offline = true;
  if (opts.liveValue != null) body.live_value = String(opts.liveValue);
  if (opts.animationFrame != null) body.animation_frame = opts.animationFrame;
  if (opts.pressElapsedFrames != null) body.press_elapsed_frames = opts.pressElapsedFrames;
  const r = await fetch("/api/preview_key", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (r.status === 404) return { blob: null, overflow: false, lines: 0 };
  if (!r.ok) throw new Error(await r.text());
  return {
    blob: await r.blob(),
    overflow: r.headers.get("X-Key-Overflow") === "1",
    lines: Number(r.headers.get("X-Key-Lines") || 0),
  };
}

/** Final look of an entry: { label, icon, bg, fg, mode, source: {field: "proposed"|"modified"}, live? }. */
export async function fetchResolvedLook(entry, lang) {
  const r = await fetch("/api/resolve_look", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ entry: entry || {}, lang: lang || undefined }),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

/**
 * One preview image: `slot.show(entry, cid, opts)` renders into `img`, ignoring answers that arrive
 * after a newer request, and calls `onResult({ overflow, lines, empty })`.
 */
export function createPreviewSlot(img, { onResult = () => {}, onEmpty = () => {} } = {}) {
  let url = null;
  let seq = 0;
  return {
    async show(entry, cid, opts) {
      const my = ++seq;
      try {
        const res = await fetchKeyPreview(entry, cid, opts);
        if (my !== seq) return;
        if (url) URL.revokeObjectURL(url);
        url = null;
        if (!res.blob) {
          img.removeAttribute("src");
          img.hidden = true;
          onEmpty();
          onResult({ overflow: false, lines: 0, empty: true });
          return;
        }
        url = URL.createObjectURL(res.blob);
        img.src = url;
        img.hidden = false;
        onResult({ overflow: res.overflow, lines: res.lines, empty: false });
      } catch {
        if (my === seq) onResult({ overflow: false, lines: 0, empty: true, error: true });
      }
    },
    dispose() {
      seq += 1;
      if (url) URL.revokeObjectURL(url);
      url = null;
    },
  };
}

// --- animations ----------------------------------------------------------------------------------

let animTimer = null;

/** Stop the idle-animation loop (also used by the legacy encoder editor when it takes the panel over). */
export function stopSidebarAnimPreview() {
  if (animTimer) clearInterval(animTimer);
  animTimer = null;
}

/** While the key has an idle animation, keep re-rendering it with an advancing frame. */
export function maybeStartIdleAnimation(slot, entry, cid) {
  stopSidebarAnimPreview();
  const idle = (entry && entry.idle_animation) || "none";
  if (idle === "none") return;
  let frame = 0;
  animTimer = setInterval(() => {
    if (state.selectedControl !== cid) return stopSidebarAnimPreview();
    frame += 1;
    void slot.show(entry, cid, { animationFrame: frame });
  }, 100);
}

// Must mirror button_render.py's PRESS_ANIMATION_DURATION_TICKS / _PRESS_ANIMATION_DURATION_OVERRIDES.
const PRESS_ANIMATION_DURATION_TICKS = 4;
const PRESS_ANIMATION_DURATION_OVERRIDES = { slide_reappear: 8 };

/** Play the press animation once in `slot`, then go back to the still (or idle) preview. */
export async function playPressAnimation(slot, entry, cid) {
  const type = (entry && entry.press_animation) || "none";
  if (type === "none") return;
  stopSidebarAnimPreview();
  const n = PRESS_ANIMATION_DURATION_OVERRIDES[type] || PRESS_ANIMATION_DURATION_TICKS;
  for (let f = 0; f < n; f++) {
    await slot.show(entry, cid, { pressElapsedFrames: f });
    await new Promise((r) => setTimeout(r, 100));
  }
  await slot.show(entry, cid);
  maybeStartIdleAnimation(slot, entry, cid);
}
