/*
 * shell.js — App shell: the Buttons / Services tab bar.
 */

import { stopKeySequenceRecording } from "./key-sequence.js";
import { $ } from "./util.js";

function switchTab(name) {
  stopKeySequenceRecording();
  const panels = { buttons: $("#tabPanelButtons"), services: $("#tabPanelServices") };
  const buttons = { buttons: $("#tabBtnButtons"), services: $("#tabBtnServices") };
  for (const key of Object.keys(panels)) {
    if (panels[key]) panels[key].hidden = key !== name;
    if (buttons[key]) buttons[key].setAttribute("aria-selected", key === name ? "true" : "false");
  }
}

export function wireTabBar() {
  const btnButtons = $("#tabBtnButtons");
  const btnServices = $("#tabBtnServices");
  if (btnButtons) btnButtons.addEventListener("click", () => switchTab("buttons"));
  if (btnServices) btnServices.addEventListener("click", () => switchTab("services"));
}
