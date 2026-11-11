/*
 * catalog.js — The action catalog (GET /api/action_catalog, in state.actionCatalog): spec lookup and
 * the short human names shown on the deck, in captions and in the inspector.
 */

import { splitActionLabel } from "./pickers/helpers.js";
import { state } from "./state.js";

export function getSpec(type) {
  return state.actionCatalog.find((a) => a.type === type) || null;
}

/** Short name of an action type ("Next track" for "Spotify — next track"); the type when unknown. */
export function actionShortName(type) {
  const spec = getSpec(type);
  return spec ? splitActionLabel(spec.label || type, spec.category).name : String(type || "");
}
