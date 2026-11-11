"""Control ids: legacy (``touch_N``, ``knobTL``, ``btn_circle``...) <-> model control ids.

Model control ids (``key_<col>_<row>``, ``knob_<n>``, ``button_<n>``, ``strip_<n>``...) are defined
in :mod:`open_loupedeck.devices.model`. Configs written before ``config_version: 2`` used legacy
ids; each model carries its own table (``DeviceModel.legacy_ids``). ``touch_N`` depends on the
model's key grid; the other legacy ids mean the same control on every model of a family (the Live
``btn_7`` is ``button_7`` everywhere, inactive on a Live S), so they fall back to the other models
of the family. Legacy ids stay readable forever.
"""

from __future__ import annotations

from .devices.model import DeviceModel, control_kind_from_id, is_control_id

LEGACY_ALIASES = {"btn_0": "btn_circle", "circle": "btn_circle", "left": "strip_left", "right": "strip_right"}
"""Older spellings of legacy ids (``btn_0`` was the Live S circle button in early configs)."""


def _family_models(model: DeviceModel) -> list[DeviceModel]:
    from .devices.registry import known_models

    return [model] + [m for m in known_models() if m.family == model.family and m.id != model.id]


def is_legacy_id(legacy_id: str) -> bool:
    s = str(legacy_id or "")
    return (s.startswith(("touch_", "btn_", "knob", "strip_")) and not is_control_id(s)) or s in LEGACY_ALIASES


def legacy_to_control_id(legacy_id: str, model: DeviceModel, *, aliases: bool = True) -> str | None:
    """Control id for a legacy id on ``model`` (``None`` when it has no meaning there).

    ``touch_N`` only uses ``model``'s key grid (``touch_14`` has no meaning on a 4 x 3 grid).
    """

    lid = str(legacy_id or "")
    if aliases:
        lid = LEGACY_ALIASES.get(lid, lid)
    if lid.startswith("touch_"):
        return model.legacy_map().get(lid)
    for m in _family_models(model):
        cid = m.legacy_map().get(lid)
        if cid is not None:
            return cid
    return None


def control_to_legacy_id(control_id: str, model: DeviceModel) -> str | None:
    """Legacy id of a control id on ``model`` (``None`` when there is none)."""

    cid = str(control_id or "")
    if control_kind_from_id(cid) == "key":
        return model.legacy_id_of(cid)
    for m in _family_models(model):
        lid = m.legacy_id_of(cid)
        if lid is not None:
            return lid
    return None


def to_control_id(any_id: str, model: DeviceModel) -> str | None:
    """A control id (returned as is) or a legacy id (mapped on ``model``) -> control id."""

    s = str(any_id or "").strip()
    if is_control_id(s):
        return s
    return legacy_to_control_id(s, model)


def driver_name_for_button(control_id: str) -> str | None:
    """python-loupedeck name of a round button (``button_0`` -> ``circle``, ``button_N`` -> ``N``)."""

    if control_id == "button_0":
        return "circle"
    if control_id.startswith("button_") and control_id[7:].isdigit():
        return control_id[7:]
    return None
