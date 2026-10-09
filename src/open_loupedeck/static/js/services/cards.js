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
