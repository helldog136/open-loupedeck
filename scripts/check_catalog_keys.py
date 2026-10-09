#!/usr/bin/env python3
"""List the locale keys the action catalog needs and that are missing (or stray) in each locale file.

Usage:  python scripts/check_catalog_keys.py [--dir src/open_loupedeck/locales]

Required, per catalog action: ``action.<type>.label``, ``look.<type>.label`` (default key label) and
``category.<slug>``; per field ``action.<type>.field.<name>.label``; per select option
``action.<type>.field.<name>.option.<value>`` (except verbatim options such as ``GET`` or ``30``).
``.placeholder`` and ``.help`` keys are optional but, when present in en.json, must exist in every
locale (``scripts/check_locales.py`` enforces that too). Keys under ``action.``, ``category.`` and
``look.`` in en.json that no catalog entry uses are reported as stray. Exit code 1 on any problem.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

DEFAULT_DIR = ROOT / "src" / "open_loupedeck" / "locales"
SOURCE = "en"
_OPTIONAL = re.compile(r"^action\.[\w.]+\.(help|field\.\w+\.(placeholder|help))$")


def required_keys() -> set[str]:
    from open_loupedeck import action_catalog as ac

    keys: set[str] = set()
    for entry in ac.ACTION_CATALOG:
        t = entry["type"]
        keys.add(ac.label_key(t))
        keys.add(ac.category_key(entry["category"]))
        keys.add(f"look.{t}.label")
        for f in entry.get("fields") or []:
            keys.add(ac.field_key(t, f["name"], "label"))
            for opt in f.get("options") or []:
                if ac.option_has_key(opt):
                    keys.add(ac.option_key(t, f["name"], str(opt)))
    keys.add(ac.category_key("other"))
    return keys


def check_catalog_keys(directory: Path = DEFAULT_DIR) -> list[str]:
    """Human-readable problems (empty list = the catalog is fully translated)."""

    required = required_keys()
    problems: list[str] = []
    en: dict[str, str] = {}
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            problems.append(f"{path.name}: not valid JSON ({exc})")
            continue
        if path.stem == SOURCE:
            en = data
        missing = sorted(k for k in required if not str(data.get(k, "")).strip())
        if missing:
            problems.append(f"{path.name}: {len(missing)} missing catalog key(s): " + ", ".join(missing))
    owned = ("action.", "category.", "look.")
    stray = sorted(
        k for k in en if k.startswith(owned) and k not in required and not _OPTIONAL.match(k) and k != "category.other"
    )
    if stray:
        problems.append(f"{SOURCE}.json: stray catalog key(s) no action uses: " + ", ".join(stray))
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dir", type=Path, default=DEFAULT_DIR, help="locales directory")
    args = ap.parse_args()
    problems = check_catalog_keys(args.dir)
    if problems:
        print("Catalog key check failed:\n")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(f"OK: {len(required_keys())} catalog keys present in every locale file")
    return 0


if __name__ == "__main__":
    sys.exit(main())
