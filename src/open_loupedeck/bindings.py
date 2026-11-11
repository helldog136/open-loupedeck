"""Bindings: what a control does, with one resolution rule for every control.

Config shape (``config_version: 2``, see ``docs/devices-features.md`` "Config schema")::

    global:                 # control id -> binding, on every page
      button_0: {action: {type: agent.goto_page, index: 0}, button_color: "#3b6bff"}
    pages:
      - name: Main
        controls:           # control id -> binding, overrides the global one on this page
          key_0_0: {text: BRB, action: {type: obs.set_scene, scene: BRB}}
          knob_0: {rotate: {duo: system_volume}, press: {type: sound.mute_toggle}}

Resolution at runtime: the current page's binding if present, else the global one. A binding's
shape follows the control's kind (key / button / strip: actions + look + ``button_color``; knob:
``rotate`` role + ``press`` action). Entries for controls the device does not have are kept and
simply never resolve (switching devices is lossless).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

GLOBAL_KEY = "global"
PAGE_CONTROLS_KEY = "controls"

Scope = Literal["page", "global"]


@dataclass(frozen=True)
class Binding:
    control_id: str
    scope: Scope
    entry: dict[str, Any]
    page_index: int

    @property
    def storage_key(self) -> str:
        """Key of runtime caches (live-message text, error markers) for this binding."""

        return storage_key(self.control_id, self.scope, self.page_index)


def storage_key(control_id: str, scope: Scope, page_index: int) -> str:
    return f"p{int(page_index)}:{control_id}" if scope == "page" else f"g:{control_id}"


def global_bindings(raw: dict[str, Any]) -> dict[str, Any]:
    g = raw.get(GLOBAL_KEY)
    return g if isinstance(g, dict) else {}


def page_bindings(page: Any) -> dict[str, Any]:
    if not isinstance(page, dict):
        return {}
    c = page.get(PAGE_CONTROLS_KEY)
    return c if isinstance(c, dict) else {}


def current_page(raw: dict[str, Any], page_index: int) -> tuple[int, dict[str, Any] | None]:
    pages = raw.get("pages")
    if not isinstance(pages, list) or not pages:
        return 0, None
    idx = int(page_index) % len(pages)
    page = pages[idx]
    return idx, page if isinstance(page, dict) else None


def resolve_in(
    page: dict[str, Any] | None,
    global_map: dict[str, Any],
    control_id: str,
    page_index: int = 0,
) -> Binding | None:
    """The rule: ``page``'s binding for ``control_id`` if it has one, else the global one."""

    entry = page_bindings(page).get(control_id)
    if isinstance(entry, dict):
        return Binding(control_id, "page", entry, int(page_index))
    entry = global_map.get(control_id) if isinstance(global_map, dict) else None
    if isinstance(entry, dict):
        return Binding(control_id, "global", entry, int(page_index))
    return None


def resolve_binding(raw: dict[str, Any], page_index: int, control_id: str) -> Binding | None:
    """Binding of ``control_id`` on deck page ``page_index`` (wrapped), or ``None``."""

    idx, page = current_page(raw, page_index)
    return resolve_in(page, global_bindings(raw), control_id, idx)


def actions_of(entry: dict[str, Any]) -> list[dict[str, Any]]:
    """Actions of a key/button binding: a non-empty ``actions`` list, else the single ``action``.

    An empty ``actions: []`` must not hide a valid ``action`` (common when hand-editing YAML).
    """

    if "actions" in entry:
        a = entry["actions"]
        if isinstance(a, list) and len(a) > 0:
            return list(a)
        if a is not None and not isinstance(a, list):
            raise ValueError("actions must be a list")
    if "action" in entry:
        act = entry["action"]
        if isinstance(act, dict):
            return [act]
        raise ValueError("action must be a mapping")
    return []


def iter_bindings(raw: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    """``(storage_key, control_id, entry)`` for every binding, global and per page."""

    out: list[tuple[str, str, dict[str, Any]]] = []
    for cid, entry in global_bindings(raw).items():
        if isinstance(entry, dict):
            out.append((storage_key(str(cid), "global", 0), str(cid), entry))
    pages = raw.get("pages")
    if isinstance(pages, list):
        for pi, page in enumerate(pages):
            for cid, entry in page_bindings(page).items():
                if isinstance(entry, dict):
                    out.append((storage_key(str(cid), "page", pi), str(cid), entry))
    return out
