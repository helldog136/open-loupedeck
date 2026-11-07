/*
 * services/cards.js — Shared plumbing of the Services connection cards: each card's state pill (also read
 * by the header chips), the "Configure" buttons that open a card's details, and the inline two-step
 * confirmation used instead of window.confirm.
 */

import { $ } from "../util.js";

/** svc -> { mode: "ok" | "bad" | "idle", text: string, show: boolean } */
const serviceStates = {};

/** Update a card's pill and remember the state for the header chip. `show:false` hides the chip. */
export function setServiceState(svc, mode, text, show = true) {
  serviceStates[svc] = { mode, text, show };
  const pill = document.querySelector(`#svc-${svc} .svc-pill`);
  if (!pill) return;
  pill.classList.toggle("ok", mode === "ok");
  pill.classList.toggle("bad", mode === "bad");
  const label = pill.querySelector(".svc-pill-text");
  if (label) {
    label.textContent = text;
    label.title = text;
  }
}

export function getServiceState(svc) {
  return serviceStates[svc] || null;
}

/** OBS / Home Assistant: "Configure" opens the card's details and puts the cursor in the first field. */
export function wireConfigureButtons() {
  const pairs = [
    ["#btnObsConfigure", "#obsDetails", "#obsHost"],
    ["#btnHaConfigure", "#haDetails", "#haBaseUrl"],
  ];
  for (const [btnSel, detailsSel, fieldSel] of pairs) {
    const btn = $(btnSel);
    if (!btn) continue;
    btn.addEventListener("click", () => {
      const details = $(detailsSel);
      if (details) details.open = true;
      const field = $(fieldSel);
      if (field) field.focus();
    });
  }
}

/**
 * Turn a destructive button into a two-step action: the first click swaps it for "Are you sure?" with
 * a confirm and a cancel button (auto-cancels after 10 s). `promptKey` / `confirmKey` are i18n keys.
 */
export function wireInlineConfirm(btn, { promptKey, confirmKey, vars, onConfirm }) {
  btn.addEventListener("click", () => {
    const wrap = document.createElement("span");
    wrap.className = "confirm-inline";
    const text = document.createElement("span");
    text.className = "confirm-text";
    text.textContent = t(promptKey, vars);
    const yes = document.createElement("button");
    yes.type = "button";
    yes.className = "btn btn-danger btn-sm";
    yes.textContent = t(confirmKey, vars);
    const no = document.createElement("button");
    no.type = "button";
    no.className = "btn btn-sm";
    no.textContent = t("common.cancel");
    wrap.append(text, yes, no);
    btn.hidden = true;
    btn.after(wrap);
    let timer = 0;
    const close = () => {
      clearTimeout(timer);
      wrap.remove();
      btn.hidden = false;
    };
    timer = setTimeout(close, 10000);
    yes.addEventListener("click", () => {
      close();
      onConfirm();
    });
    no.addEventListener("click", () => {
      close();
      btn.focus();
    });
    no.focus();
  });
}

/**
 * "General" card: screen brightness slider (live apply, debounced save) and "Night mode"
 * (from / to times + a dimmer level). Built here and inserted before the config-folder row;
 * state lives on the server (GET / PUT /api/brightness), the device follows immediately.
 */
export async function initBrightnessCard() {
  const rows = document.querySelector("#svc-general .svc-rows");
  if (!rows) return;
  let data = null;
  try {
    const r = await fetch("/api/brightness");
    if (r.ok) data = await r.json();
  } catch {
    /* offline: leave the card as it is */
  }
  if (!data) return;

  const wrap = document.createElement("div");
  wrap.className = "svc-brightness";
  wrap.style.display = "contents";
  rows.insertBefore(wrap, rows.lastElementChild);

  let timer = 0;
  const pending = {};
  const showError = (msg) => {
    const box = $("#saveError");
    if (box) box.textContent = msg;
  };
  const send = (patch) => {
    for (const k of Object.keys(patch)) {
      if (k === "night") pending.night = { ...(pending.night || {}), ...patch.night };
      else pending[k] = patch[k];
    }
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const body = { ...pending };
      for (const k of Object.keys(pending)) delete pending[k];
      try {
        const r = await fetch("/api/brightness", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        if (r.ok) data = await r.json();
        else {
          const err = await r.json().catch(() => ({}));
          showError(err.detail || String(r.status));
        }
      } catch (e) {
        showError(String(e));
      }
    }, 150);
  };

  const mk = (tag, props = {}, ...kids) => {
    const n = Object.assign(document.createElement(tag), props);
    n.append(...kids);
    return n;
  };
  const slider = (id, value, onInput) => {
    const range = mk("input", { type: "range", id, min: "0", max: "100", step: "10", value: String(value) });
    const tag = mk("span", { className: "tag", textContent: `${value}%` });
    range.addEventListener("input", () => {
      tag.textContent = `${range.value}%`;
      onInput(Number(range.value));
    });
    return mk("span", { className: "svc-slider" }, range, tag);
  };

  const render = () => {
    wrap.replaceChildren();
    const night = data.night || {};
    const lvlRow = mk(
      "div",
      { className: "svc-row" },
      mk("label", { className: "svc-row-label", htmlFor: "brightnessLevel", textContent: t("svc.brightness.level") }),
      slider("brightnessLevel", data.level, (v) => send({ level: v })),
    );
    const toggle = mk("input", { type: "checkbox", id: "brightnessNightToggle", checked: !!night.enabled });
    const nightRow = mk(
      "label",
      { className: "svc-row" },
      mk("span", { className: "svc-row-label", textContent: t("svc.brightness.night") }),
      mk("span", { className: "toggle" }, toggle, mk("span")),
    );
    const from = mk("input", { type: "time", id: "brightnessFrom", value: night.from || "22:00" });
    const to = mk("input", { type: "time", id: "brightnessTo", value: night.to || "07:00" });
    const timesRow = mk(
      "div",
      { className: "svc-row svc-night-times" },
      mk("span", { className: "svc-row-label", textContent: t("svc.brightness.night_desc") }),
      mk(
        "span",
        { className: "svc-times" },
        mk("label", { htmlFor: "brightnessFrom", textContent: t("svc.brightness.from") }),
        from,
        mk("label", { htmlFor: "brightnessTo", textContent: t("svc.brightness.to") }),
        to,
      ),
    );
    const nightLvlRow = mk(
      "div",
      { className: "svc-row svc-night-level" },
      mk("label", {
        className: "svc-row-label",
        htmlFor: "brightnessNightLevel",
        textContent: t("svc.brightness.night_level"),
      }),
      slider("brightnessNightLevel", night.level ?? 20, (v) => send({ night: { level: v } })),
    );
    const showNight = () => {
      timesRow.hidden = nightLvlRow.hidden = !toggle.checked;
    };
    showNight();
    toggle.addEventListener("change", () => {
      showNight();
      send({ night: { enabled: toggle.checked } });
    });
    for (const [inp, key] of [
      [from, "from"],
      [to, "to"],
    ]) {
      inp.addEventListener("change", () => {
        if (inp.value) send({ night: { [key]: inp.value } });
      });
    }
    wrap.append(lvlRow, nightRow, timesRow, nightLvlRow);
  };
  render();
  document.addEventListener("i18n:change", render);
}
