/*
 * api.js — Thin fetch wrappers for the agent's HTTP API that several modules share (config, page
 * index, simulate press, upload, skin refresh).
 */

export async function apiGet() {
  const r = await fetch("/api/config");
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function apiPut(body) {
  const r = await fetch("/api/config", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function refreshSkin() {
  await fetch("/api/refresh_skin", { method: "POST" });
}

export async function postAgentPageIndex(ix) {
  const r = await fetch("/api/page_index", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ index: ix }),
  });
  if (!r.ok) throw new Error(await r.text());
}

export async function postSimulatePress(controlId, direction) {
  const body = { control_id: controlId };
  if (direction === "left" || direction === "right") body.direction = direction;
  const r = await fetch("/api/simulate_press", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    let detail = r.statusText;
    try {
      const j = await r.json();
      if (j.detail !== undefined) {
        detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
      }
    } catch {
      try {
        detail = await r.text();
      } catch {
        /* ignore */
      }
    }
    throw new Error(detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function uploadFileToAssets(file, library) {
  if (!file) throw new Error("No file selected");
  const lib = library || "images";
  const fd = new FormData();
  fd.append("file", file);
  const r = await fetch(`/api/upload?library=${encodeURIComponent(lib)}`, { method: "POST", body: fd });
  if (!r.ok) {
    const t = await r.text();
    throw new Error(t || `Upload failed (${r.status})`);
  }
  const j = await r.json();
  if (!j.path) throw new Error("Upload response missing path");
  return j.path;
}
