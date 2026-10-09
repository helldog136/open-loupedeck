/*
 * pickers/sound-picker.js — Sound library picker for the `sound.play` "file" field: list of the sounds in
 * library/sounds with ▶ preview (played by the server, i.e. on this PC), search, upload / drag-and-drop,
 * rename, delete and a volume slider mirrored on the action's `volume` field. Registers itself as the
 * custom renderer of that field (see registerFieldRenderer in action-fields.js). Also exports the two
 * helpers deck.js uses to turn an audio file dropped on an empty key into a `sound.play` key.
 */

import { registerFieldRenderer } from "../action-fields.js";
import { uploadFileToAssets } from "../api.js";
import { scheduleAutosave } from "../save.js";
import { state } from "../state.js";
import { SOUND_UPLOAD_EXT } from "../constants.js";

/** True for a file the sound library accepts (by extension). */
export function isAudioFile(file) {
  const low = String((file && file.name) || "").toLowerCase();
  const dot = low.lastIndexOf(".");
  return dot >= 0 && SOUND_UPLOAD_EXT.has(low.slice(dot));
}

/** "library/sounds/1a2b3c4d_Air_horn-loud.mp3" -> "Air horn loud" (label proposed for a sound key). */
export function cleanSoundName(pathOrName) {
  const base = String(pathOrName || "").replace(/\\/g, "/").split("/").pop() || "";
  const stem = base.replace(/\.[^.]*$/, "").replace(/^[0-9a-f]{8}_/, "");
  return stem.replace(/[_-]+/g, " ").replace(/\s+/g, " ").trim();
}

/** Upload one audio file to library/sounds; resolves to its config-relative path. */
export function uploadSoundFile(file) {
  return uploadFileToAssets(file, "sounds");
}

/* ------------------------------------------------------------------------------------------ server */

let libraryInfo = { sounds: [], platform: "", windows_extensions: [] };

async function fetchLibrary() {
  const r = await fetch("/api/sounds");
  if (!r.ok) throw new Error(await r.text());
  libraryInfo = await r.json();
  return libraryInfo;
}

async function postJson(url, body) {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  if (!r.ok) {
    let msg = "";
    try {
      const j = await r.json();
      msg = j.detail || "";
    } catch {
      msg = await r.text();
    }
    throw new Error(msg || `HTTP ${r.status}`);
  }
  return r.json();
}

function unsupportedOnThisPc(ext) {
  return libraryInfo.platform === "win32" && !(libraryInfo.windows_extensions || []).includes(ext);
}

function formatMeta(s) {
  const parts = [];
  if (s.duration != null) parts.push(`${s.duration < 10 ? s.duration.toFixed(1) : Math.round(s.duration)} s`);
  parts.push(s.size >= 1048576 ? `${(s.size / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(s.size / 1024))} KB`);
  return parts.join(" · ");
}

/** Replace a path everywhere in the config (after a rename) so no key silently loses its sound. */
function replacePathInConfig(oldPath, newPath) {
  const walk = (o) => {
    if (Array.isArray(o)) o.forEach((v, i) => (typeof v === "string" ? (o[i] = v === oldPath ? newPath : v) : walk(v)));
    else if (o && typeof o === "object") {
      for (const k of Object.keys(o)) {
        if (typeof o[k] === "string") {
          if (o[k] === oldPath) o[k] = newPath;
        } else walk(o[k]);
      }
    }
  };
  walk(state.cfg);
  scheduleAutosave();
}

/* ------------------------------------------------------------------------------------------- field */

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}

function renderSoundField(container, wrap, f, idPrefix) {
  const fid = `${idPrefix}_${String(f.name).replace(/[^a-zA-Z0-9_]/g, "_")}`;
  const lab = el("label", "field-label", f.label || f.name);
  lab.htmlFor = fid;
  const input = document.createElement("input");
  input.type = "text";
  input.id = fid;
  input.className = "mono path-input snd-path";
  input.dataset.param = f.name;
  input.setAttribute("data-param", String(f.name));
  if (f.placeholder) input.placeholder = f.placeholder;

  const panel = el("div", "snd-picker");
  const bar = el("div", "snd-bar");
  const search = document.createElement("input");
  search.type = "search";
  search.className = "snd-search";
  search.placeholder = t("sound.picker.search");
  search.setAttribute("aria-label", t("sound.picker.search"));
  const addBtn = el("button", "btn-browse snd-add", t("sound.picker.add"));
  addBtn.type = "button";
  const stopBtn = el("button", "btn-browse snd-stop", t("sound.picker.stop"));
  stopBtn.type = "button";
  const fileIn = document.createElement("input");
  fileIn.type = "file";
  fileIn.hidden = true;
  fileIn.multiple = true;
  fileIn.accept = "audio/*,.wav,.mp3,.ogg,.flac,.m4a,.opus,.aac,.wma";
  bar.append(search, addBtn, stopBtn, fileIn);

  const list = el("ul", "snd-list");
  list.setAttribute("role", "listbox");
  const status = el("p", "hint snd-status");
  status.setAttribute("role", "status");

  const volRow = el("div", "snd-vol");
  const volLab = el("span", "snd-vol-label", t("sound.picker.volume"));
  const vol = document.createElement("input");
  vol.type = "range";
  vol.min = "0";
  vol.max = "100";
  vol.value = "100";
  vol.className = "snd-vol-range";
  vol.setAttribute("aria-label", t("sound.picker.volume"));
  const volOut = el("span", "snd-vol-out mono", "100");
  volRow.append(volLab, vol, volOut);
  const hint = el("p", "hint snd-hint", t("sound.picker.drop_hint"));

  panel.append(bar, list, status, volRow, hint);

  const volField = () => container.querySelector('[data-param="volume"]');
  const syncVolFromField = () => {
    const vf = volField();
    const raw = vf && String(vf.value).trim();
    const v = raw === "" || raw == null || Number.isNaN(Number(raw)) ? 100 : Math.max(0, Math.min(100, Number(raw)));
    vol.value = String(v);
    volOut.textContent = String(v);
  };
  vol.addEventListener("input", (ev) => {
    ev.stopPropagation();
    volOut.textContent = vol.value;
    const vf = volField();
    if (vf) {
      vf.value = vol.value === "100" ? "" : vol.value;
      vf.dispatchEvent(new Event("input", { bubbles: true }));
    }
  });
  setTimeout(() => {
    // the form is filled right after rendering: read the stored volume, then follow manual edits
    syncVolFromField();
    const vf = volField();
    if (vf) vf.addEventListener("input", syncVolFromField);
  }, 0);

  const say = (msg, bad) => {
    status.textContent = msg || "";
    status.classList.toggle("is-bad", !!bad);
  };

  const setValue = (rel) => {
    input.value = rel;
    input.dispatchEvent(new Event("input", { bubbles: true }));
    paint();
  };

  async function preview(s) {
    try {
      say("");
      await postJson("/api/sounds/preview", { file: s.file, volume: Number(vol.value) });
    } catch (e) {
      say(t("sound.picker.play_error", { error: String(e.message || e) }), true);
    }
  }

  async function rename(s) {
    const cur = cleanSoundName(s.name);
    const next = window.prompt(t("sound.picker.rename_prompt"), cur);
    if (next == null || !next.trim() || next.trim() === cur) return;
    try {
      const j = await postJson("/api/sounds/rename", { file: s.file, name: next.trim() });
      replacePathInConfig(s.file, j.file);
      if (input.value === s.file) input.value = j.file;
      await reload();
    } catch (e) {
      say(String(e.message || e), true);
    }
  }

  async function remove(s) {
    if (!window.confirm(t("sound.picker.delete_confirm", { name: cleanSoundName(s.name) }))) return;
    try {
      await postJson("/api/sounds/delete", { file: s.file });
      await reload();
    } catch (e) {
      say(String(e.message || e), true);
    }
  }

  function paint() {
    const q = search.value.trim().toLowerCase();
    list.innerHTML = "";
    const all = libraryInfo.sounds || [];
    const items = all.filter((s) => !q || cleanSoundName(s.name).toLowerCase().includes(q));
    if (!items.length) {
      list.appendChild(el("li", "snd-empty", t(all.length ? "sound.picker.no_match" : "sound.picker.empty")));
      return;
    }
    for (const s of items) {
      const li = el("li", "snd-row");
      li.dataset.file = s.file;
      const selected = input.value.trim() === s.file;
      li.classList.toggle("is-selected", selected);
      li.setAttribute("role", "option");
      li.setAttribute("aria-selected", selected ? "true" : "false");
      const play = el("button", "snd-play", "▶");
      play.type = "button";
      play.title = t("sound.picker.preview");
      play.setAttribute("aria-label", t("sound.picker.preview"));
      play.addEventListener("click", () => void preview(s));
      const pick = el("button", "snd-pick");
      pick.type = "button";
      pick.title = t("sound.picker.use");
      pick.append(el("span", "snd-name", cleanSoundName(s.name) || s.name), el("span", "snd-meta mono", formatMeta(s)));
      if (unsupportedOnThisPc(s.ext)) {
        const w = el("span", "snd-warn", "⚠");
        w.title = t("sound.picker.win_unsupported", { ext: s.ext });
        pick.appendChild(w);
      }
      pick.addEventListener("click", () => setValue(s.file));
      const ren = el("button", "snd-icon", "✎");
      ren.type = "button";
      ren.title = t("sound.picker.rename");
      ren.setAttribute("aria-label", t("sound.picker.rename"));
      ren.addEventListener("click", () => void rename(s));
      const del = el("button", "snd-icon", "✕");
      del.type = "button";
      del.title = t("sound.picker.delete");
      del.setAttribute("aria-label", t("sound.picker.delete"));
      del.addEventListener("click", () => void remove(s));
      li.append(play, pick, ren, del);
      list.appendChild(li);
    }
  }

  async function reload() {
    try {
      await fetchLibrary();
      paint();
    } catch (e) {
      say(String(e.message || e), true);
    }
  }

  async function upload(files) {
    const audio = Array.from(files || []).filter(isAudioFile);
    if (!audio.length) {
      say(t("sound.picker.not_audio"), true);
      return;
    }
    say(t("sound.picker.uploading"));
    let last = "";
    const warnings = [];
    try {
      for (const file of audio) {
        last = await uploadSoundFile(file);
        const ext = `.${file.name.split(".").pop().toLowerCase()}`;
        if (unsupportedOnThisPc(ext)) warnings.push(ext);
      }
      await reload();
      if (audio.length === 1 && last) setValue(last);
      say(
        warnings.length
          ? t("sound.picker.win_unsupported", { ext: warnings[0] })
          : t("sound.picker.uploaded", { count: audio.length }),
        warnings.length > 0,
      );
    } catch (e) {
      say(String(e.message || e), true);
    }
  }

  addBtn.addEventListener("click", () => fileIn.click());
  fileIn.addEventListener("change", () => {
    const files = Array.from(fileIn.files || []);
    fileIn.value = "";
    void upload(files);
  });
  stopBtn.addEventListener("click", () => void postJson("/api/sounds/stop").catch(() => {}));
  search.addEventListener("input", (ev) => {
    ev.stopPropagation(); // searching is not a form edit
    paint();
  });
  input.addEventListener("input", paint);
  const hasFiles = (ev) => ev.dataTransfer && Array.from(ev.dataTransfer.types || []).includes("Files");
  panel.addEventListener("dragover", (ev) => {
    if (!hasFiles(ev)) return;
    ev.preventDefault();
    panel.classList.add("is-drop");
  });
  panel.addEventListener("dragleave", () => panel.classList.remove("is-drop"));
  panel.addEventListener("drop", (ev) => {
    panel.classList.remove("is-drop");
    if (!hasFiles(ev)) return;
    ev.preventDefault();
    void upload(ev.dataTransfer.files);
  });

  wrap.append(lab, input, panel);
  if (f.help) wrap.appendChild(el("p", "hint field-help", f.help));
  container.appendChild(wrap);
  paint(); // cached list first, then the fresh one
  void reload();
}

registerFieldRenderer("sound.play", "file", renderSoundField);
