/*
 * page-field.js — The "Go to page" action's page parameter as a list of the config's pages by name
 * ("1 · Main") instead of a zero-based number. Registered with action-fields.js; the select keeps
 * `data-param="index"` so the stored action is unchanged (`index: 0` = the first page).
 */

import { registerFieldRenderer } from "./action-fields.js";
import { pageName } from "./model.js";
import { state } from "./state.js";

function renderPageIndexField(container, wrap, f, idPrefix) {
  const fid = `${idPrefix}_${f.name}`;
  const lab = document.createElement("label");
  lab.className = "field-label";
  lab.htmlFor = fid;
  lab.textContent = t("inspector.field.goto_page");
  const sel = document.createElement("select");
  sel.id = fid;
  sel.dataset.param = f.name;
  const none = document.createElement("option");
  none.value = "";
  none.textContent = t("inspector.field.goto_page.none");
  sel.append(none);
  (state.cfg.pages || []).forEach((_, i) => {
    const o = document.createElement("option");
    o.value = String(i);
    o.textContent = `${i + 1} · ${pageName(i)}`;
    sel.append(o);
  });
  lab.append(sel);
  wrap.append(lab);
  // The page list comes first; the other ways to name a page sit in "More" (rendered just before).
  const more = container.querySelector(".field-more");
  container.insertBefore(wrap, more);
}

/** `id` / `name` (other ways to name the page) as plain text fields inside a closed "More" section. */
function renderMoreField(container, wrap, f, idPrefix) {
  let more = container.querySelector(".field-more");
  if (!more) {
    more = document.createElement("details");
    more.className = "field-more";
    const sum = document.createElement("summary");
    sum.textContent = t("inspector.field.goto_page.more");
    more.append(sum);
    container.append(more);
  }
  const fid = `${idPrefix}_${f.name}`;
  const lab = document.createElement("label");
  lab.className = "field-label";
  lab.htmlFor = fid;
  lab.textContent = f.label || f.name;
  const input = document.createElement("input");
  input.type = "text";
  input.id = fid;
  input.dataset.param = f.name;
  lab.append(input);
  wrap.append(lab);
  more.append(wrap);
}

registerFieldRenderer("agent.goto_page", "id", renderMoreField);
registerFieldRenderer("agent.goto_page", "name", renderMoreField);
registerFieldRenderer("agent.goto_page", "index", renderPageIndexField);
