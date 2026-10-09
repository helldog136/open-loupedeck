"""Knob "duos": one linked setting whose left / right rotation are its − / + directions.

A duo is pure data: an id, a category (reuses the action catalog's ``category.<slug>`` keys), a
small params schema (step size, OBS input name, Home Assistant entity...) and two action templates
built from existing action types. A config stores only ``{duo: <id>, params: {...}}``; the actions
are expanded at run time, so improving a duo improves every knob that uses it.

Template values may be :class:`P` placeholders: ``P("step", sign=-1)`` becomes ``-step``,
``P("input_name")`` becomes the param value. Optional params without a value drop their key.

Locale keys (``locales/<code>.json``):

- ``knob.duo.<id>.label`` — the duo's name ("System volume")
- ``knob.duo.<id>.left`` / ``.right`` — feedback drawn on the neighbouring key after a turn
  ("Volume −{step}"); every param is available as a ``{placeholder}``
- ``knob.duo.param.<name>.label`` — a param's field label (shared between duos)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .i18n import t


@dataclass(frozen=True)
class P:
    """Placeholder for a duo param inside an action template."""

    name: str
    sign: int = 1


@dataclass(frozen=True)
class DuoParam:
    name: str
    kind: str = "number"  # "number" | "text"
    default: Any = None
    required: bool = False
    min: float | None = None
    max: float | None = None

    @property
    def label_key(self) -> str:
        return f"knob.duo.param.{self.name}.label"


@dataclass(frozen=True)
class KnobDuo:
    id: str
    category: str
    left: tuple[dict[str, Any], ...]
    right: tuple[dict[str, Any], ...]
    params: tuple[DuoParam, ...] = field(default_factory=tuple)

    @property
    def label_key(self) -> str:
        return f"knob.duo.{self.id}.label"

    def side_key(self, direction: str) -> str:
        return f"knob.duo.{self.id}.{'left' if direction == 'left' else 'right'}"


def _step(default: float, lo: float = 1, hi: float = 50) -> DuoParam:
    return DuoParam("step", "number", default, False, lo, hi)


def _keys(*names: str) -> dict[str, Any]:
    return {"type": "keyboard.play_sequence", "steps": [{"keys": [n]} for n in names]}


KNOB_DUOS: tuple[KnobDuo, ...] = (
    KnobDuo(
        "system_volume",
        "sound",
        ({"type": "sound.volume_delta", "delta": P("step", -1)},),
        ({"type": "sound.volume_delta", "delta": P("step")},),
        (_step(5, 1, 25),),
    ),
    KnobDuo(
        "obs_input_volume",
        "obs",
        ({"type": "obs.input_volume_delta", "input_name": P("input_name"), "delta": P("step", -1)},),
        ({"type": "obs.input_volume_delta", "input_name": P("input_name"), "delta": P("step")},),
        (DuoParam("input_name", "text", None, True), _step(5, 1, 25)),
    ),
    KnobDuo(
        "obs_scene",
        "obs",
        ({"type": "obs.scene_step", "step": -1},),
        ({"type": "obs.scene_step", "step": 1},),
    ),
    KnobDuo(
        "ha_light_brightness",
        "home_assistant",
        (
            {
                "type": "ha.call_service",
                "domain": "light",
                "service": "turn_on",
                "entity_id": P("entity_id"),
                "data": {"brightness_step_pct": P("step", -1)},
            },
        ),
        (
            {
                "type": "ha.call_service",
                "domain": "light",
                "service": "turn_on",
                "entity_id": P("entity_id"),
                "data": {"brightness_step_pct": P("step")},
            },
        ),
        (DuoParam("entity_id", "text", None, True), _step(10, 1, 50)),
    ),
    KnobDuo(
        "spotify_volume",
        "spotify",
        ({"type": "spotify.volume_delta", "delta": P("step", -1)},),
        ({"type": "spotify.volume_delta", "delta": P("step")},),
        (_step(5, 1, 25),),
    ),
    KnobDuo(
        "spotify_track",
        "spotify",
        ({"type": "spotify.previous"},),
        ({"type": "spotify.next"},),
    ),
    KnobDuo(
        "deck_page",
        "deck",
        ({"type": "agent.prev_page"},),
        ({"type": "agent.next_page"},),
    ),
    KnobDuo("keyboard_up_down", "keyboard", (_keys("up"),), (_keys("down"),)),
    KnobDuo("keyboard_page_up_down", "keyboard", (_keys("page_up"),), (_keys("page_down"),)),
    KnobDuo("keyboard_left_right", "keyboard", (_keys("left"),), (_keys("right"),)),
)

_BY_ID: dict[str, KnobDuo] = {d.id: d for d in KNOB_DUOS}


def get_duo(duo_id: Any) -> KnobDuo | None:
    return _BY_ID.get(str(duo_id or ""))


# --- params -----------------------------------------------------------------------------------


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _num_out(x: float) -> int | float:
    return int(x) if float(x).is_integer() else x


def resolved_params(duo: KnobDuo, params: dict[str, Any] | None) -> dict[str, Any]:
    """Params with defaults applied and numbers clamped to the schema; unknown keys are dropped."""

    src = params if isinstance(params, dict) else {}
    out: dict[str, Any] = {}
    for p in duo.params:
        v = src.get(p.name)
        if v is None or (isinstance(v, str) and not v.strip()):
            v = p.default
        if v is None:
            continue
        if p.kind == "number":
            n = _number(v)
            if n is None:
                n = _number(p.default)
            if n is None:
                continue
            if p.min is not None:
                n = max(p.min, n)
            if p.max is not None:
                n = min(p.max, n)
            out[p.name] = _num_out(n)
        else:
            out[p.name] = str(v).strip()
    return out


def missing_params(duo: KnobDuo, params: dict[str, Any] | None) -> list[str]:
    rp = resolved_params(duo, params)
    return [p.name for p in duo.params if p.required and p.name not in rp]


def validate_duo_params(duo: KnobDuo, params: Any, where: str) -> list[str]:
    """Type problems only: a required param left empty is allowed (the UI autosaves while typing)."""

    if params is None:
        return []
    if not isinstance(params, dict):
        return [f"{where}.params must be an object"]
    errors: list[str] = []
    for p in duo.params:
        v = params.get(p.name)
        if v is None or v == "":
            continue
        if p.kind == "number" and _number(v) is None:
            errors.append(f"{where}.params.{p.name} must be a number")
        elif p.kind == "text" and not isinstance(v, (str, int, float)):
            errors.append(f"{where}.params.{p.name} must be text")
    return errors


# --- expansion --------------------------------------------------------------------------------

_DROP = object()


def _fill(tpl: Any, rp: dict[str, Any]) -> Any:
    if isinstance(tpl, P):
        if tpl.name not in rp:
            return _DROP
        v = rp[tpl.name]
        if tpl.sign != 1 and _number(v) is not None:
            return _num_out(_number(v) * tpl.sign)  # type: ignore[operator]
        return v
    if isinstance(tpl, dict):
        out = {}
        for k, v in tpl.items():
            fv = _fill(v, rp)
            if fv is not _DROP:
                out[k] = fv
        return out
    if isinstance(tpl, list):
        return [x for x in (_fill(v, rp) for v in tpl) if x is not _DROP]
    return tpl


def expand_duo(duo_id: Any, params: dict[str, Any] | None, direction: str) -> list[dict[str, Any]]:
    """Concrete actions for one rotation step of a duo (``direction``: ``left`` or ``right``)."""

    duo = get_duo(duo_id)
    if duo is None:
        return []
    rp = resolved_params(duo, params)
    side = duo.left if direction == "left" else duo.right
    return [_fill(tpl, rp) for tpl in side]


def duo_feedback(duo_id: Any, params: dict[str, Any] | None, direction: str, lang: str | None = None) -> str:
    """Text drawn on the neighbouring key after a turn, e.g. ``Volume +5``."""

    duo = get_duo(duo_id)
    if duo is None:
        return ""
    return t(duo.side_key(direction), lang, **resolved_params(duo, params))


# --- matching (used by the legacy knob_pages migration) ---------------------------------------


def _unify(tpl: Any, val: Any, found: dict[str, Any]) -> bool:
    if isinstance(tpl, P):
        if tpl.sign != 1:
            n = _number(val)
            if n is None:
                return False
            v: Any = _num_out(n * tpl.sign)
        else:
            v = val
        if tpl.name in found and found[tpl.name] != v:
            return False
        found[tpl.name] = v
        return True
    if isinstance(tpl, dict):
        if not isinstance(val, dict) or set(val) != set(tpl):
            return False
        return all(_unify(tv, val[k], found) for k, tv in tpl.items())
    if isinstance(tpl, list):
        if not isinstance(val, list) or len(val) != len(tpl):
            return False
        return all(_unify(a, b, found) for a, b in zip(tpl, val, strict=True))
    if _number(tpl) is not None and _number(val) is not None:
        return _number(tpl) == _number(val)
    return tpl == val


def match_duo(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> tuple[str, dict[str, Any]] | None:
    """Find the duo whose expansion is exactly ``left`` / ``right`` (and the params that give it)."""

    for duo in KNOB_DUOS:
        if len(duo.left) != len(left) or len(duo.right) != len(right):
            continue
        found: dict[str, Any] = {}
        ok = all(_unify(tp, a, found) for tp, a in zip(duo.left, left, strict=True)) and all(
            _unify(tp, a, found) for tp, a in zip(duo.right, right, strict=True)
        )
        if not ok:
            continue
        step = found.get("step")
        if step is not None and (_number(step) is None or _number(step) <= 0):  # type: ignore[operator]
            continue
        params = {k: v for k, v in found.items() if any(p.name == k for p in duo.params)}
        if resolved_params(duo, params) != params:  # outside the schema range: keep as split
            continue
        if expand_duo(duo.id, params, "left") == left and expand_duo(duo.id, params, "right") == right:
            return duo.id, params
    return None


# --- API --------------------------------------------------------------------------------------


def _template_json(tpl: Any) -> Any:
    if isinstance(tpl, P):
        return {"param": tpl.name, "sign": tpl.sign}
    if isinstance(tpl, dict):
        return {k: _template_json(v) for k, v in tpl.items()}
    if isinstance(tpl, list):
        return [_template_json(v) for v in tpl]
    return tpl


def list_duos(lang: str | None = None) -> list[dict[str, Any]]:
    """The catalogue for ``GET /api/knob_duos``: translated texts plus their ``*_key``."""

    out: list[dict[str, Any]] = []
    for d in KNOB_DUOS:
        defaults = resolved_params(d, {})
        # Show "{input_name}"-style holes as-is when a param has no default yet.
        sample = {p.name: defaults.get(p.name, "…") for p in d.params}
        out.append(
            {
                "id": d.id,
                "label": t(d.label_key, lang),
                "label_key": d.label_key,
                "category": t(f"category.{d.category}", lang),
                "category_key": f"category.{d.category}",
                "left_label": t(d.side_key("left"), lang, **sample),
                "left_label_key": d.side_key("left"),
                "right_label": t(d.side_key("right"), lang, **sample),
                "right_label_key": d.side_key("right"),
                "params": [
                    {
                        "name": p.name,
                        "kind": p.kind,
                        "label": t(p.label_key, lang),
                        "label_key": p.label_key,
                        "default": p.default,
                        "required": p.required,
                        "min": p.min,
                        "max": p.max,
                    }
                    for p in d.params
                ],
                "left": [_template_json(x) for x in d.left],
                "right": [_template_json(x) for x in d.right],
            }
        )
    return out
