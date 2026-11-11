/*
 * device-layout.js — Geometry shared by the two pictures of a device drawn from its model
 * (DeviceModel.to_dict(): a `layout` in units, a `position` per control): the editor deck (deck.js)
 * and the virtual device (virtual/device.js). Pure functions, no DOM.
 *
 * Both draw the device as a stage of (layout + 2 * PAD) units, one unit being `--u` px, every control
 * absolutely placed from its position (CSS variables --x --y --w --h), the display keys sitting in a
 * recessed bed.
 */

/** Bezel around the layout, in units. */
export const PAD = 0.45;
/** Recessed bed around the key grid, in units. */
export const BED_PAD = 0.07;

const KIND_ORDER = { key: 0, strip: 1, knob: 2, slider: 3, button: 4, pedal: 5 };
const KEY_ID = /^key_(\d+)_(\d+)$/;

/** [col, row] of a `key_<col>_<row>` id, else null. */
export function keyCoord(id) {
  const m = KEY_ID.exec(String(id || ""));
  return m ? [Number(m[1]), Number(m[2])] : null;
}

/** Visual order (top to bottom, left to right) = Tab order. */
export function visualOrder(controls) {
  return [...controls].sort((a, b) => {
    const dy = Math.round(a.position.y * 4) - Math.round(b.position.y * 4);
    if (dy) return dy;
    const dx = Math.round(a.position.x * 4) - Math.round(b.position.x * 4);
    return dx || (KIND_ORDER[a.kind] ?? 9) - (KIND_ORDER[b.kind] ?? 9);
  });
}

/** Rectangle {x, y, w, h} (units) of the bed under the display keys, or null without keys. */
export function keyBed(model) {
  const keys = (model.controls || []).filter((c) => c.kind === "key");
  if (!keys.length) return null;
  const x0 = Math.min(...keys.map((c) => c.position.x));
  const y0 = Math.min(...keys.map((c) => c.position.y));
  const x1 = Math.max(...keys.map((c) => c.position.x + c.position.w));
  const y1 = Math.max(...keys.map((c) => c.position.y + c.position.h));
  return { x: x0 - BED_PAD, y: y0 - BED_PAD, w: x1 - x0 + 2 * BED_PAD, h: y1 - y0 + 2 * BED_PAD };
}

/** Set the position variables of an absolutely placed node from a rectangle in units. */
export function placeAt(node, r) {
  node.style.setProperty("--x", r.x);
  node.style.setProperty("--y", r.y);
  node.style.setProperty("--w", r.w);
  node.style.setProperty("--h", r.h);
}

/**
 * Px per layout unit so that the stage fits `availW` x `availH` (Infinity = no limit), clamped.
 * `pad` is the bezel on each side, `extraH` units reserved below (captions).
 */
export function fitUnit(model, availW, availH = Infinity, { min = 12, max = 112, pad = PAD, extraH = 0 } = {}) {
  const W = model.layout.width + 2 * pad;
  const H = model.layout.height + 2 * pad + extraH;
  return Math.max(min, Math.min(max, availW / W, availH / H));
}
