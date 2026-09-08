"""Load/save full YAML document for round-trip UI editing."""

from __future__ import annotations

import os
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from .config import DeviceConfig, HaConfig, ObsConfig, Settings


def load_raw_config(path: Path) -> dict[str, Any]:
    text = path.read_text()
    raw = yaml.safe_load(text)
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise TypeError("Config root must be a mapping")
    return raw


def save_raw_config(path: Path, raw: dict[str, Any]) -> None:
    """Write atomically (temp file + ``os.replace``): a kill/crash mid-write must never leave a
    truncated or partially-written config on disk -- the target either has the old content or the
    fully-written new content, never a half-written one."""

    path.parent.mkdir(parents=True, exist_ok=True)
    dumped = yaml.safe_dump(
        raw,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
        width=120,
    )
    tmp_path = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(dumped)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    finally:
        tmp_path.unlink(missing_ok=True)


def raw_to_settings(raw: dict[str, Any]) -> Settings:
    obs = None
    if raw.get("obs"):
        o = raw["obs"]
        obs = ObsConfig(
            host=str(o.get("host", "127.0.0.1")),
            port=int(o.get("port", 4455)),
            password=str(o.get("password", "")),
        )
    ha = None
    if raw.get("ha"):
        h = raw["ha"]
        ha = HaConfig(
            base_url=str(h.get("base_url", "")),
            token=str(h.get("token", "")),
        )
    dev = raw.get("device") or {}
    device = DeviceConfig(
        path=str(dev.get("path", "")),
        baudrate=int(dev["baudrate"]) if dev.get("baudrate") is not None else None,
        model=str(dev.get("model", "auto")).lower(),
    )
    bindings = raw.get("bindings") or []
    if not isinstance(bindings, list):
        raise TypeError("bindings must be a list")
    pages = raw.get("pages")
    if pages is None:
        pages = []
    if not isinstance(pages, list):
        raise TypeError("pages must be a list")
    plugins = raw.get("plugin_modules") or []
    if not isinstance(plugins, list):
        raise TypeError("plugin_modules must be a list")
    return Settings(
        obs=obs,
        ha=ha,
        device=device,
        bindings=list(bindings),
        pages=list(pages),
        plugin_modules=[str(p) for p in plugins],
    )


def default_raw_config() -> dict[str, Any]:
    return {
        "logging": {
            "dir": "",
            "level": "INFO",
            "file": True,
            "console": True,
        },
        "obs": {"host": "127.0.0.1", "port": 4455, "password": ""},
        "ha": {"base_url": "", "token": ""},
        "device": {"path": "", "baudrate": None, "model": "auto"},
        "plugin_modules": [],
        "global_buttons": {},
        "knob_pages": {},
        "pages": [
            {
                "id": 0,
                "name": "Page 1",
                "buttons": {
                    # Live S 5×3 touch grid: lower-left=touch_10, lower-right=touch_14.
                    "touch_10": {
                        "action": {
                            "type": "display.live_message",
                            "template": "Page {page_number}/{page_count}",
                        }
                    },
                    "touch_14": {
                        "action": {
                            "type": "display.clock",
                            "time_format": "%H:%M",
                            "date_format": "%a %d %b",
                        }
                    },
                },
            },
            {
                "id": 1,
                "name": "Page 2",
                "buttons": {
                    "touch_10": {
                        "action": {
                            "type": "display.live_message",
                            "template": "Page {page_number}/{page_count}",
                        }
                    },
                    "touch_14": {
                        "action": {
                            "type": "display.clock",
                            "time_format": "%H:%M",
                            "date_format": "%a %d %b",
                        }
                    },
                },
            },
            {
                "id": 2,
                "name": "Page 3",
                "buttons": {
                    "touch_10": {
                        "action": {
                            "type": "display.live_message",
                            "template": "Page {page_number}/{page_count}",
                        }
                    },
                    "touch_14": {
                        "action": {
                            "type": "display.clock",
                            "time_format": "%H:%M",
                            "date_format": "%a %d %b",
                        }
                    },
                },
            },
            {
                "id": 3,
                "name": "Page 4",
                "buttons": {
                    "touch_10": {
                        "action": {
                            "type": "display.live_message",
                            "template": "Page {page_number}/{page_count}",
                        }
                    },
                    "touch_14": {
                        "action": {
                            "type": "display.clock",
                            "time_format": "%H:%M",
                            "date_format": "%a %d %b",
                        }
                    },
                },
            },
        ],
        "bindings": [],
    }


def ensure_minimal_structure(raw: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(raw)
    if "pages" not in out:
        out["pages"] = []
    if "bindings" not in out:
        out["bindings"] = []
    if "plugin_modules" not in out:
        out["plugin_modules"] = []
    if "device" not in out:
        out["device"] = {"path": "", "baudrate": None, "model": "auto"}
    elif "model" not in out["device"]:
        out["device"]["model"] = "auto"
    if "obs" not in out:
        out["obs"] = {"host": "127.0.0.1", "port": 4455, "password": ""}
    if "ha" not in out or not isinstance(out["ha"], dict):
        out["ha"] = {"base_url": "", "token": ""}
    if "logging" not in out:
        out["logging"] = {
            "dir": "",
            "level": "INFO",
            "file": True,
            "console": True,
        }
    if "global_buttons" not in out or not isinstance(out["global_buttons"], dict):
        out["global_buttons"] = {}
    if "knob_pages" not in out or not isinstance(out["knob_pages"], dict):
        out["knob_pages"] = {}
    if "spotify" not in out or not isinstance(out["spotify"], dict):
        out["spotify"] = {}
    if "twitch" not in out or not isinstance(out["twitch"], (dict, list)):
        out["twitch"] = {}
    _normalize_live_s_pages_and_page_buttons(out)
    return out


def _normalize_live_s_pages_and_page_buttons(raw: dict[str, Any]) -> None:
    """Loupedeck Live S: allow any number of touch pages; physical buttons only switch indices 0–3."""

    dev = raw.get("device") or {}
    if str(dev.get("model", "auto")).lower() != "live_s":
        return
    pages = raw.get("pages")
    if not isinstance(pages, list):
        pages = []
    while len(pages) < 1:
        pages.append({"id": len(pages), "name": f"Page {len(pages) + 1}", "buttons": {}})
    for i, p in enumerate(pages):
        if not isinstance(p, dict):
            pages[i] = {"id": i, "name": f"Page {i + 1}", "buttons": {}}
            continue
        p.setdefault("buttons", {})
        p["id"] = i
        if "name" not in p or str(p.get("name") or "").strip() == "":
            p["name"] = f"Page {i + 1}"
    raw["pages"] = pages
    gb = raw.get("global_buttons")
    if not isinstance(gb, dict):
        gb = {}
    # Legacy configs used "btn_0" for the circle key; merge into btn_circle and drop the alias.
    if "btn_circle" not in gb and "btn_0" in gb:
        gb["btn_circle"] = gb.get("btn_0")
    gb.pop("btn_0", None)
    for bid in ("btn_circle", "btn_1", "btn_2", "btn_3"):
        ent = gb.get(bid)
        if not isinstance(ent, dict):
            continue
        c = ent.get("button_color")
        ent = dict(ent)
        if c is not None and str(c).strip() != "":
            ent["button_color"] = str(c).strip()
        else:
            ent.pop("button_color", None)
        gb[bid] = ent
    raw["global_buttons"] = gb
