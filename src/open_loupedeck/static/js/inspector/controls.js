/*
 * inspector/controls.js — Which inspector view a control gets, from its capabilities in the device
 * model (not from its id): a rotation -> the knob view; a press -> the action view (with Appearance when
 * it shows an image, with Light when it has an LED); anything else -> "not supported yet". Also the
 * control's plain-language name.
 */

import { controlLabel, hasImage, hasInput, hasLed, kindOf } from "../model.js";

/** "knob" | "action" | "unsupported" */
export function viewKind(cid) {
  if (hasInput(cid, "rotate")) return "knob";
  if (hasInput(cid, "press")) return "action";
  return "unsupported";
}

/** What the action view shows for this control. */
export function capabilities(cid) {
  return { press: hasInput(cid, "press"), image: hasImage(cid), led: hasLed(cid), kind: kindOf(cid) };
}

export function controlName(cid) {
  return controlLabel(cid);
}
