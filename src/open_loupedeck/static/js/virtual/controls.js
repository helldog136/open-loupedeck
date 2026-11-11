/*
 * virtual/controls.js — DOM + interaction of each kind of virtual control. Pure UI: every input is
 * handed to ctx.send(type, controlId, value) ("press" | "release" | "rotate" | "value" | "touch"),
 * the device (or the test harness) decides what to do with it.
 *
 *   const c = createControl(controlDescriptor, ctx) -> { el, setImage(b64), setLed([r,g,b]) }
 *
 * ctx = { send(type, id, value), label(kind, n) -> string, hint(kind) -> string, t }.
 * Keyboard: Space / Enter press, arrow keys turn knobs and move sliders; keys are arrow-navigable
 * (roving tab stop, handled by device.js).
 */

const KNOB_STEP_DEG = 14; // visual rotation of one step
const KNOB_DRAG_DEG = 18; // pointer travel (around the knob centre) per step
const KNOB_WHEEL_PX = 50; // wheel delta per step (one mouse notch is ~100)
const KNOB_HOLD_MS = 380; // a still hold longer than this is a (long) press
const SLIDER_SEND_MS = 40;

function el(tag, cls, attrs) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (attrs) for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  return node;
}

function indexOfId(id) {
  const m = /_(\d+)(?:_(\d+))?$/.exec(id);
  return m ? Number(m[1]) : 0;
}

/** Press / release from pointer (left button) and keyboard (Space, Enter) on one element. */
function wirePress(node, id, ctx) {
  let down = false;
  const press = () => {
    if (down) return;
    down = true;
    node.classList.add("is-down");
    ctx.send("press", id);
  };
  const release = () => {
    if (!down) return;
    down = false;
    node.classList.remove("is-down");
    ctx.send("release", id);
  };
  node.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    e.preventDefault();
    node.focus({ preventScroll: true });
    try {
      node.setPointerCapture(e.pointerId);
    } catch {
      /* synthetic pointer */
    }
    press();
  });
  for (const type of ["pointerup", "pointercancel", "lostpointercapture"]) node.addEventListener(type, release);
  node.addEventListener("keydown", (e) => {
    if (e.key !== " " && e.key !== "Enter") return;
    e.preventDefault();
    if (!e.repeat) press();
  });
  node.addEventListener("keyup", (e) => {
    if (e.key === " " || e.key === "Enter") release();
  });
  node.addEventListener("blur", release);
  return { press, release };
}

function baseNode(tag, kind, ctl, ctx) {
  const node = el(tag, `vd-ctl vd-${kind}`);
  node.dataset.control = ctl.id;
  node.dataset.kind = kind;
  const p = ctl.position;
  node.style.setProperty("--x", p.x);
  node.style.setProperty("--y", p.y);
  node.style.setProperty("--w", p.w);
  node.style.setProperty("--h", p.h);
  const name = ctx.label(ctl.kind, indexOfId(ctl.id) + 1, ctl);
  node.setAttribute("aria-label", name);
  node.title = `${name}\n${ctx.hint(ctl.kind)}`;
  if (tag === "button") node.type = "button";
  return node;
}

// --- display key ------------------------------------------------------------------------------

function createKey(ctl, ctx) {
  const node = baseNode("button", "key", ctl, ctx);
  const face = el("span", "vd-face");
  const img = el("img", "vd-img", { alt: "", draggable: "false" });
  img.hidden = true;
  face.append(img);
  node.append(face);
  wirePress(node, ctl.id, ctx);
  return {
    el: node,
    setImage(b64) {
      img.src = `data:image/png;base64,${b64}`;
      img.hidden = false;
    },
  };
}

// --- LED button -------------------------------------------------------------------------------

function createButton(ctl, ctx) {
  const node = baseNode("button", "btn", ctl, ctx);
  const face = el("span", "vd-face");
  const num = el("span", "vd-btn-num");
  num.textContent = String(indexOfId(ctl.id) + 1);
  face.append(num);
  node.append(face);
  wirePress(node, ctl.id, ctx);
  const dflt = ctl.outputs && ctl.outputs.led && ctl.outputs.led.default;
  const api = {
    el: node,
    setLed(rgb) {
      const [r, g, b] = rgb;
      const luma = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
      node.style.setProperty("--led", `rgb(${r}, ${g}, ${b})`);
      node.style.setProperty("--glow", `rgba(${r}, ${g}, ${b}, ${Math.min(0.85, luma * 1.3).toFixed(2)})`);
      node.classList.toggle("is-lit", luma > 0.22);
    },
  };
  if (dflt) api.setLed(dflt);
  return api;
}

// --- knob -------------------------------------------------------------------------------------

function createKnob(ctl, ctx) {
  const node = baseNode("div", "knob", ctl, ctx);
  node.tabIndex = 0;
  node.setAttribute("role", "button");
  const face = el("span", "vd-face");
  const dial = el("span", "vd-dial");
  dial.append(el("span", "vd-mark"));
  face.append(dial);
  node.append(face);
  let angle = 0;
  const id = ctl.id;

  function turn(steps) {
    if (!steps) return;
    angle += steps * KNOB_STEP_DEG;
    dial.style.setProperty("--a", `${angle}deg`);
    ctx.send("rotate", id, steps);
  }

  // wheel: up = clockwise (+1); trackpads accumulate small deltas
  let wheelAcc = 0;
  node.addEventListener(
    "wheel",
    (e) => {
      e.preventDefault();
      const px = e.deltaMode === 1 ? e.deltaY * 16 : e.deltaMode === 2 ? e.deltaY * 120 : e.deltaY;
      wheelAcc -= px;
      const steps = Math.trunc(wheelAcc / KNOB_WHEEL_PX);
      if (steps) {
        wheelAcc -= steps * KNOB_WHEEL_PX;
        turn(steps);
      }
    },
    { passive: false },
  );

  // drag around the centre turns; a tap presses; a still hold is a long press
  let drag = null;
  const angleAt = (e, c) => (Math.atan2(e.clientY - c.y, e.clientX - c.x) * 180) / Math.PI;
  node.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    e.preventDefault();
    node.focus({ preventScroll: true });
    try {
      node.setPointerCapture(e.pointerId);
    } catch {
      /* synthetic pointer */
    }
    const r = node.getBoundingClientRect();
    const c = { x: r.left + r.width / 2, y: r.top + r.height / 2 };
    drag = { x: e.clientX, y: e.clientY, c, last: angleAt(e, c), acc: 0, moved: false, pressed: false, timer: 0 };
    node.classList.add("is-down");
    drag.timer = window.setTimeout(() => {
      if (drag && !drag.moved) {
        drag.pressed = true;
        ctx.send("press", id);
      }
    }, KNOB_HOLD_MS);
  });
  node.addEventListener("pointermove", (e) => {
    if (!drag) return;
    if (!drag.moved && Math.hypot(e.clientX - drag.x, e.clientY - drag.y) > 5) {
      drag.moved = true;
      window.clearTimeout(drag.timer);
      drag.last = angleAt(e, drag.c);
      return;
    }
    if (!drag.moved) return;
    const a = angleAt(e, drag.c);
    let d = a - drag.last;
    if (d > 180) d -= 360;
    if (d < -180) d += 360;
    drag.last = a;
    drag.acc += d;
    const steps = Math.trunc(drag.acc / KNOB_DRAG_DEG);
    if (steps) {
      drag.acc -= steps * KNOB_DRAG_DEG;
      turn(steps);
    }
  });
  const end = () => {
    if (!drag) return;
    const d = drag;
    drag = null;
    window.clearTimeout(d.timer);
    node.classList.remove("is-down");
    if (d.pressed) ctx.send("release", id);
    else if (!d.moved) {
      ctx.send("press", id);
      ctx.send("release", id);
    }
  };
  for (const type of ["pointerup", "pointercancel", "lostpointercapture"]) node.addEventListener(type, end);

  // keyboard: arrows turn, Space / Enter press
  let kdown = false;
  node.addEventListener("keydown", (e) => {
    if (e.key === "ArrowRight" || e.key === "ArrowUp") {
      e.preventDefault();
      turn(1);
    } else if (e.key === "ArrowLeft" || e.key === "ArrowDown") {
      e.preventDefault();
      turn(-1);
    } else if ((e.key === " " || e.key === "Enter") && !e.repeat && !kdown) {
      e.preventDefault();
      kdown = true;
      node.classList.add("is-down");
      ctx.send("press", id);
    }
  });
  const kup = () => {
    if (!kdown) return;
    kdown = false;
    node.classList.remove("is-down");
    ctx.send("release", id);
  };
  node.addEventListener("keyup", (e) => {
    if (e.key === " " || e.key === "Enter") kup();
  });
  node.addEventListener("blur", kup);
  return { el: node };
}

// --- slider -----------------------------------------------------------------------------------

function createSlider(ctl, ctx) {
  const node = baseNode("div", "slider", ctl, ctx);
  const vertical = ctl.position.h >= ctl.position.w;
  node.classList.add(vertical ? "is-vertical" : "is-horizontal");
  node.tabIndex = 0;
  node.setAttribute("role", "slider");
  node.setAttribute("aria-orientation", vertical ? "vertical" : "horizontal");
  node.setAttribute("aria-valuemin", "0");
  node.setAttribute("aria-valuemax", "100");
  const track = el("span", "vd-track");
  const thumb = el("span", "vd-thumb");
  node.append(track, thumb);
  let value = 0;
  let lastSent = 0;
  let timer = 0;

  function show() {
    node.style.setProperty("--v", value);
    node.setAttribute("aria-valuenow", String(Math.round(value * 100)));
  }
  function emit() {
    window.clearTimeout(timer);
    timer = 0;
    lastSent = performance.now();
    ctx.send("value", ctl.id, value);
  }
  function set(v, now) {
    value = Math.min(1, Math.max(0, v));
    show();
    const wait = SLIDER_SEND_MS - (performance.now() - lastSent);
    if (now || wait <= 0) emit();
    else if (!timer) timer = window.setTimeout(emit, wait);
  }
  function fromPointer(e) {
    const r = track.getBoundingClientRect();
    const f = vertical ? 1 - (e.clientY - r.top) / r.height : (e.clientX - r.left) / r.width;
    set(f);
  }
  let dragging = false;
  node.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    e.preventDefault();
    node.focus({ preventScroll: true });
    try {
      node.setPointerCapture(e.pointerId);
    } catch {
      /* synthetic pointer */
    }
    dragging = true;
    node.classList.add("is-down");
    fromPointer(e);
  });
  node.addEventListener("pointermove", (e) => {
    if (dragging) fromPointer(e);
  });
  const end = () => {
    if (!dragging) return;
    dragging = false;
    node.classList.remove("is-down");
    if (timer) emit();
  };
  for (const type of ["pointerup", "pointercancel", "lostpointercapture"]) node.addEventListener(type, end);
  node.addEventListener("keydown", (e) => {
    const big = e.shiftKey ? 0.2 : 0.05;
    const moves = {
      ArrowUp: big,
      ArrowRight: big,
      ArrowDown: -big,
      ArrowLeft: -big,
      PageUp: 0.1,
      PageDown: -0.1,
    };
    if (e.key in moves) {
      e.preventDefault();
      set(value + moves[e.key], true);
    } else if (e.key === "Home" || e.key === "End") {
      e.preventDefault();
      set(e.key === "Home" ? 0 : 1, true);
    }
  });
  show();
  return { el: node };
}

// --- touch strip ------------------------------------------------------------------------------

function createStrip(ctl, ctx) {
  const node = baseNode("div", "strip", ctl, ctx);
  node.tabIndex = 0;
  node.setAttribute("role", "button");
  const face = el("span", "vd-face");
  const img = el("img", "vd-img", { alt: "", draggable: "false" });
  img.hidden = true;
  face.append(img);
  node.append(face);
  const size = (ctl.outputs && ctl.outputs.image) || { width: 1, height: 1 };
  const touch = (e) => {
    const r = node.getBoundingClientRect();
    const x = Math.round(((e.clientX - r.left) / r.width) * (size.width - 1));
    const y = Math.round(((e.clientY - r.top) / r.height) * (size.height - 1));
    ctx.send("touch", ctl.id, [x, y]);
  };
  let down = false;
  node.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    e.preventDefault();
    node.focus({ preventScroll: true });
    try {
      node.setPointerCapture(e.pointerId);
    } catch {
      /* synthetic pointer */
    }
    down = true;
    node.classList.add("is-down");
    touch(e);
  });
  node.addEventListener("pointermove", (e) => {
    if (down) touch(e);
  });
  const end = () => {
    down = false;
    node.classList.remove("is-down");
  };
  for (const type of ["pointerup", "pointercancel", "lostpointercapture"]) node.addEventListener(type, end);
  node.addEventListener("keydown", (e) => {
    if (e.key === " " || e.key === "Enter") {
      e.preventDefault();
      ctx.send("touch", ctl.id, [Math.floor(size.width / 2), Math.floor(size.height / 2)]);
    }
  });
  return {
    el: node,
    setImage(b64) {
      img.src = `data:image/png;base64,${b64}`;
      img.hidden = false;
    },
  };
}

const BUILDERS = { key: createKey, button: createButton, knob: createKnob, slider: createSlider, strip: createStrip };

/** Control element for a model control descriptor, or null for a kind that has no widget. */
export function createControl(ctl, ctx) {
  const build = BUILDERS[ctl.kind];
  return build ? build(ctl, ctx) : null;
}
