/*
 * shell.js — App shell: the Buttons / Services tab bar, and "go to the matching Services card" used by
 * the actionable status chips.
 */

import { stopKeySequenceRecording } from "./key-sequence.js";
import { $ } from "./util.js";

export function switchTab(name) {
  stopKeySequenceRecording();
  const panels = { buttons: $("#tabPanelButtons"), services: $("#tabPanelServices") };
  const buttons = { buttons: $("#tabBtnButtons"), services: $("#tabBtnServices") };
  for (const key of Object.keys(panels)) {
    if (panels[key]) panels[key].hidden = key !== name;
    if (buttons[key]) buttons[key].setAttribute("aria-selected", key === name ? "true" : "false");
  }
}

/** Open the Services tab on a service's card, and focus its main action (Connect / Configure…). */
export function goToService(svc) {
  const cardId = svc === "device" ? "svc-general" : `svc-${svc}`;
  switchTab("services");
  const card = document.getElementById(cardId);
  if (!card) return;
  card.scrollIntoView({ block: "center", behavior: "smooth" });
  const main =
    svc === "device"
      ? card.querySelector("#deviceModel")
      : card.querySelector("[data-svc-main]:not([hidden])");
  if (main) main.focus({ preventScroll: true });
  card.classList.add("svc-flash");
  setTimeout(() => card.classList.remove("svc-flash"), 1600);
}

export function wireTabBar() {
  const btnButtons = $("#tabBtnButtons");
  const btnServices = $("#tabBtnServices");
  if (btnButtons) btnButtons.addEventListener("click", () => switchTab("buttons"));
  if (btnServices) btnServices.addEventListener("click", () => switchTab("services"));
}
