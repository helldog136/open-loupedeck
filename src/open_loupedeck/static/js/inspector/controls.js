/*
 * inspector/controls.js — What kind of control an id is (touch key, side screen, page button, plain
 * button, knob) and its plain-language name and scope for the inspector header.
 */

import { BTNS_LIVE_S } from "../constants.js";
import { currentPage, isKnobEncoderId, isLiveSPageSwitchButton } from "../model.js";
import { state } from "../state.js";

/** "touch" | "strip" | "pageButton" | "button" | "knob" */
export function controlKind(cid) {
  if (typeof cid !== "string") return "touch";
  if (isKnobEncoderId(cid)) return "knob";
  if (cid.startsWith("touch_")) return "touch";
  if (cid === "strip_left" || cid === "strip_right") return "strip";
  if (isLiveSPageSwitchButton(cid)) return "pageButton";
  return "button";
}

/** Page number (1-4) opened by a Live S round button. */
export function pageButtonNumber(cid) {
  return BTNS_LIVE_S.indexOf(cid) + 1;
}

export function controlName(cid) {
  const kind = controlKind(cid);
  if (kind === "touch") return t("inspector.name.key", { number: Number(cid.slice(6)) + 1 });
  if (cid === "strip_left") return t("inspector.name.strip_left");
  if (cid === "strip_right") return t("inspector.name.strip_right");
  if (kind === "pageButton") return t("inspector.name.page_button", { number: pageButtonNumber(cid) });
  if (cid === "btn_circle") return t("inspector.name.round_button");
  const m = /^btn_(\d+)$/.exec(cid);
  if (m) return t("inspector.name.button", { number: m[1] });
  return cid;
}

/** "On page “Main”" for per-page keys, "Same on every page" for the others. */
export function controlScope(cid) {
  if (typeof cid === "string" && cid.startsWith("touch_")) {
    const p = currentPage();
    const name = (p && p.name) || t("pages.default_name", { number: state.pageIndex + 1 });
    return t("inspector.scope.page", { page: name });
  }
  return t("inspector.scope.global");
}

/** Controls with a screen (their look can be edited). */
export function hasScreen(cid) {
  const k = controlKind(cid);
  return k === "touch" || k === "strip";
}
