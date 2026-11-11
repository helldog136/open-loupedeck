/*
 * virtual/device.js — The virtual device as an embeddable component.
 *
 *   const vd = mountVirtualDevice(container, options);
 *   vd.destroy();  vd.status();  vd.snapshot();
 *
 * Renders ANY model from the layout the server sends (DeviceModel.to_dict(): a `layout` in units
 * and, per control, a `position`), mirrors the device output (key images, LEDs, brightness) and
 * sends the user's input back over /ws/virtual (see connection.js and docs/virtual-device.md).
 *
 * options:
 *   url               WebSocket URL (default: same origin /ws/virtual)
 *   modelUrl          POST endpoint of the model selector (default /api/virtual/model)
 *   showStatus        status bar under the device (default true)
 *   showModelSelector model <select> in the status bar (default true; only when the server offers models)
 *   fit               "viewport" (default: also fits the window height) | "container" (width only)
 *   t                 translate function (default: the page's global t())
 *   onEvent(ev)       called for every input sent: { id, type, value }
 *   onStatus(status)  "connecting" | "open" | "closed" | "none" | "switching"
 *
 * Styles: css/virtual.css (needs tokens.css + components.css).
 */

import { connectVirtual } from "./connection.js";
import { createControl } from "./controls.js";

const PAD = 0.45; // bezel width around the layout, in units
const BED_PAD = 0.07; // recessed bed around the key grid, in units
const MAX_UNIT = 112; // px of one layout unit (a key) at most
const MIN_UNIT = 12;

const KIND_ORDER = { key: 0, strip: 1, knob: 2, slider: 3, button: 4 };

function globalT() {
  return typeof window.t === "function" ? window.t : (k) => k;
}

function mk(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

/** Visual order (top to bottom, left to right) = Tab order. */
function visualOrder(controls) {
  return [...controls].sort((a, b) => {
    const dy = Math.round(a.position.y * 4) - Math.round(b.position.y * 4);
    if (dy) return dy;
    const dx = Math.round(a.position.x * 4) - Math.round(b.position.x * 4);
    return dx || (KIND_ORDER[a.kind] ?? 9) - (KIND_ORDER[b.kind] ?? 9);
  });
}

export function mountVirtualDevice(container, options = {}) {
  const opts = { showStatus: true, showModelSelector: true, fit: "viewport", modelUrl: "/api/virtual/model", ...options };
  const tr = (key, vars) => (opts.t || globalT())(key, vars);

  const root = mk("div", "vd");
  root.style.setProperty("--pad", PAD);
  const stageHost = mk("div", "vd-stage-host");
  const status = mk("div", "vd-status");
  status.hidden = !opts.showStatus;
  root.append(stageHost, status);
  container.replaceChildren(root);

  let linkStatus = "connecting";
  let snap = null; // last snapshot
  let stage = null;
  const ctrls = new Map(); // control id -> { el, setImage?, setLed? }
  const images = {};
  const leds = {};
  let brightness = 100;
  let lastEvent = null;
  let switching = false;
  let destroyed = false;

  let selectEl = null;
  let evEl = null;
  let pillEl = null;
  let brightEl = null;
  let empty = null;

  // --- link ---------------------------------------------------------------------------------

  const link = connectVirtual({
    url: opts.url,
    onStatus(s) {
      linkStatus = s;
      paintStatus();
      paintEmpty();
      if (opts.onStatus) opts.onStatus(switching ? "switching" : s);
    },
    onMessage(msg) {
      switch (msg.t) {
        case "snapshot":
          applySnapshot(msg);
          break;
        case "image":
          if (typeof msg.id === "string" && typeof msg.png === "string") {
            images[msg.id] = msg.png;
            const c = ctrls.get(msg.id);
            if (c && c.setImage) c.setImage(msg.png);
          }
          break;
        case "led":
          if (Array.isArray(msg.rgb) && msg.rgb.length === 3) {
            leds[msg.id] = msg.rgb;
            const c = ctrls.get(msg.id);
            if (c && c.setLed) c.setLed(msg.rgb);
          }
          break;
        case "brightness":
          setBrightness(Number(msg.value));
          break;
        case "bye":
          // The server closes the socket; we reconnect and get the new device's snapshot.
          break;
        default:
          break;
      }
    },
  });

  function send(type, id, value) {
    const ev = { id, type };
    if (value !== undefined) ev.value = value;
    link.send({ t: "event", ...ev });
    lastEvent = ev;
    paintLastEvent();
    if (opts.onEvent) opts.onEvent(ev);
  }

  // --- rendering ----------------------------------------------------------------------------

  function labelFor(kind, n, ctl) {
    if (kind === "key" && snap) {
      const cols = snap.model.grid.cols || 1;
      const m = /^key_(\d+)_(\d+)$/.exec(ctl.id);
      if (m) return tr("virtual.control.key", { n: Number(m[2]) * cols + Number(m[1]) + 1 });
    }
    return tr(`virtual.control.${kind}`, { n });
  }
  const ctx = { send, label: labelFor, hint: (kind) => tr(`virtual.hint.${kind}`), t: tr };

  function applySnapshot(msg) {
    if (!msg.model || !msg.model.layout) return;
    snap = msg;
    switching = false;
    for (const k of Object.keys(images)) delete images[k];
    for (const k of Object.keys(leds)) delete leds[k];
    Object.assign(images, msg.images || {});
    Object.assign(leds, msg.leds || {});
    brightness = Number.isFinite(msg.brightness) ? msg.brightness : 100;
    buildStage();
    paintStatus();
    paintEmpty();
    fit();
    if (opts.onStatus) opts.onStatus(linkStatus);
  }

  function buildStage() {
    const model = snap.model;
    const bed = mk("div", "vd-bed");
    stage = mk("div", "vd-stage");
    stage.setAttribute("role", "group");
    stage.setAttribute("aria-label", model.name);
    stage.style.setProperty("--lw", model.layout.width);
    stage.style.setProperty("--lh", model.layout.height);
    ctrls.clear();

    const keys = model.controls.filter((c) => c.kind === "key");
    if (keys.length) {
      const x0 = Math.min(...keys.map((c) => c.position.x));
      const y0 = Math.min(...keys.map((c) => c.position.y));
      const x1 = Math.max(...keys.map((c) => c.position.x + c.position.w));
      const y1 = Math.max(...keys.map((c) => c.position.y + c.position.h));
      bed.style.setProperty("--x", x0 - BED_PAD);
      bed.style.setProperty("--y", y0 - BED_PAD);
      bed.style.setProperty("--w", x1 - x0 + 2 * BED_PAD);
      bed.style.setProperty("--h", y1 - y0 + 2 * BED_PAD);
      stage.append(bed);
    }

    const keyEls = new Map();
    for (const ctl of visualOrder(model.controls)) {
      const c = createControl(ctl, ctx);
      if (!c) continue;
      ctrls.set(ctl.id, c);
      stage.append(c.el);
      if (ctl.kind === "key") keyEls.set(ctl.id, c.el);
      if (c.setImage && images[ctl.id]) c.setImage(images[ctl.id]);
      if (c.setLed && leds[ctl.id]) c.setLed(leds[ctl.id]);
    }
    wireKeyNavigation(keyEls);
    stageHost.replaceChildren(stage);
    stage.style.setProperty("--dim", dimFactor());
  }

  /** Keys are one tab stop; arrow keys move between them (64 keys must not mean 64 Tab presses). */
  function wireKeyNavigation(keyEls) {
    if (!keyEls.size) return;
    const all = [...keyEls.values()];
    const at = new Map();
    for (const [id, node] of keyEls) {
      const m = /^key_(\d+)_(\d+)$/.exec(id);
      if (m) at.set(`${m[1]},${m[2]}`, node);
    }
    for (const node of all) node.tabIndex = -1;
    all[0].tabIndex = 0;
    const moves = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };
    for (const node of all) {
      node.addEventListener("focus", () => {
        for (const o of all) o.tabIndex = o === node ? 0 : -1;
      });
      node.addEventListener("keydown", (e) => {
        const d = moves[e.key];
        if (!d) return;
        const m = /^key_(\d+)_(\d+)$/.exec(node.dataset.control);
        const next = m && at.get(`${Number(m[1]) + d[0]},${Number(m[2]) + d[1]}`);
        e.preventDefault();
        if (next) next.focus();
      });
    }
  }

  function dimFactor() {
    return (0.14 + 0.86 * (brightness / 100)).toFixed(3);
  }

  function setBrightness(v) {
    if (!Number.isFinite(v)) return;
    brightness = Math.max(0, Math.min(100, v));
    if (stage) stage.style.setProperty("--dim", dimFactor());
    paintStatus();
  }

  // --- empty state --------------------------------------------------------------------------

  function paintEmpty() {
    const show = !snap && (linkStatus === "none" || linkStatus === "closed");
    if (!show) {
      if (empty) {
        empty.remove();
        empty = null;
      }
      return;
    }
    if (!empty) {
      empty = mk("div", "card vd-empty");
      empty.append(mk("h2", "", tr("virtual.none.title")), mk("p", "hint", tr("virtual.none.hint")));
      const code = mk("code", "mono vd-cmd", "open-loupedeck --web --virtual");
      empty.append(code);
      stageHost.replaceChildren(empty);
    }
  }

  // --- status bar ---------------------------------------------------------------------------


  function statusText() {
    if (switching) return ["idle", tr("virtual.status.switching")];
    switch (linkStatus) {
      case "open":
        return ["ok", tr("virtual.status.connected")];
      case "none":
        return ["bad", tr("virtual.status.none")];
      case "closed":
        return ["bad", tr("virtual.status.reconnecting")];
      default:
        return ["idle", tr("virtual.status.connecting")];
    }
  }

  function paintStatus() {
    if (!opts.showStatus) return;
    const [mode, text] = statusText();
    if (!pillEl) {
      pillEl = mk("span", "pill vd-pill");
      pillEl.append(document.createElement("i"), mk("span", "vd-pill-text"));
      pillEl.setAttribute("role", "status");
      status.append(pillEl);
      brightEl = mk("span", "vd-meta mono");
      evEl = mk("span", "vd-meta vd-last mono");
      evEl.setAttribute("aria-hidden", "true");
      status.append(brightEl, evEl);
    }
    pillEl.className = `pill vd-pill ${mode === "idle" ? "" : mode}`;
    pillEl.querySelector(".vd-pill-text").textContent = text;
    brightEl.textContent = snap ? tr("virtual.brightness", { pct: Math.round(brightness) }) : "";
    paintModel();
  }

  function paintModel() {
    const old = status.querySelector(".vd-model");
    if (!snap) {
      if (old) old.remove();
      selectEl = null;
      return;
    }
    const models = Array.isArray(snap.models) ? snap.models : [];
    const wantSelect = opts.showModelSelector && models.length > 1;
    let box = old;
    if (!box) {
      box = mk("label", "vd-model");
      status.insertBefore(box, pillEl.nextSibling);
    }
    box.replaceChildren();
    box.append(mk("span", "fl", tr("virtual.model")));
    if (wantSelect) {
      selectEl = mk("select", "vd-select");
      selectEl.setAttribute("aria-label", tr("virtual.model"));
      for (const m of models) {
        const o = mk("option", "", m.name);
        o.value = m.id;
        o.selected = m.id === snap.model.id;
        selectEl.append(o);
      }
      selectEl.addEventListener("change", () => switchModel(selectEl.value));
      box.append(selectEl);
    } else {
      selectEl = null;
      box.append(mk("strong", "", snap.model.name));
    }
  }

  function paintLastEvent() {
    if (!evEl || !lastEvent) return;
    const name = (ctrls.get(lastEvent.id) && ctrls.get(lastEvent.id).el.getAttribute("aria-label")) || lastEvent.id;
    let what;
    if (lastEvent.type === "rotate") what = tr(lastEvent.value > 0 ? "virtual.event.right" : "virtual.event.left");
    else if (lastEvent.type === "value") what = tr("virtual.event.value", { pct: Math.round(lastEvent.value * 100) });
    else what = tr(`virtual.event.${lastEvent.type}`);
    evEl.textContent = `${name} · ${what}`;
  }

  async function switchModel(id) {
    if (!snap || id === snap.model.id) return;
    switching = true;
    paintStatus();
    if (opts.onStatus) opts.onStatus("switching");
    try {
      const r = await fetch(opts.modelUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model: id }),
      });
      if (!r.ok) throw new Error(String(r.status));
    } catch {
      switching = false;
      paintStatus();
    }
  }

  // --- fitting ------------------------------------------------------------------------------

  function fit() {
    if (!snap || !stage) return;
    const W = snap.model.layout.width + 2 * PAD;
    const H = snap.model.layout.height + 2 * PAD;
    const availW = root.clientWidth || container.clientWidth || 320;
    let availH = Infinity;
    if (opts.fit !== "container") {
      const top = root.getBoundingClientRect().top + window.scrollY;
      const reserve = (opts.showStatus ? status.offsetHeight + 14 : 0) + 24;
      availH = Math.max(180, window.innerHeight - top - reserve);
    }
    const u = Math.max(MIN_UNIT, Math.min(MAX_UNIT, availW / W, availH / H));
    stage.style.setProperty("--u", `${u.toFixed(2)}px`);
  }

  const ro = typeof ResizeObserver === "function" ? new ResizeObserver(fit) : null;
  if (ro) ro.observe(container);
  window.addEventListener("resize", fit);
  const onLang = () => {
    if (snap) buildStage();
    paintStatus();
    paintEmpty();
    fit();
  };
  document.addEventListener("i18n:change", onLang);
  paintStatus();

  return {
    destroy() {
      if (destroyed) return;
      destroyed = true;
      link.close();
      if (ro) ro.disconnect();
      window.removeEventListener("resize", fit);
      document.removeEventListener("i18n:change", onLang);
      container.replaceChildren();
    },
    status: () => (switching ? "switching" : linkStatus),
    snapshot: () => snap,
    element: root,
  };
}
