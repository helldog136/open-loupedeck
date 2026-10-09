#!/usr/bin/env python3
"""Validate every locale file against en.json (the source of truth).

Usage:  python scripts/check_locales.py [--dir src/open_loupedeck/locales]

Checks, per file: valid JSON object of string values; ``_meta.name`` present; exactly the same key
set as en.json (missing / extra keys are listed); no empty values; every ``{var}`` placeholder
used in the English text is kept in the translation. Exit code 1 if anything is wrong.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

DEFAULT_DIR = Path(__file__).resolve().parent.parent / "src" / "open_loupedeck" / "locales"
SOURCE = "en"
PLACEHOLDER = re.compile(r"\{(\w+)\}")


def check_locales(directory: Path = DEFAULT_DIR) -> list[str]:
    """Return a list of human-readable problems (empty list = all good)."""

    problems: list[str] = []
    files = sorted(directory.glob("*.json"))
    source_path = directory / f"{SOURCE}.json"
    if not source_path.is_file():
        return [f"{source_path}: source language file is missing"]

    loaded: dict[str, dict[str, str]] = {}
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            problems.append(f"{path.name}: not valid JSON ({exc})")
            continue
        if not isinstance(data, dict):
            problems.append(f"{path.name}: top level must be a JSON object")
            continue
        for k, v in data.items():
            if not isinstance(v, str):
                problems.append(f"{path.name}: value of '{k}' must be a string")
            elif not v.strip():
                problems.append(f"{path.name}: value of '{k}' is empty")
        loaded[path.stem] = {k: v for k, v in data.items() if isinstance(v, str)}

    en = loaded.get(SOURCE)
    if en is None:
        return problems
    for code, msgs in loaded.items():
        if not msgs.get("_meta.name", "").strip():
            problems.append(f"{code}.json: '_meta.name' (the language's own name, e.g. 'Deutsch') is required")
        if code == SOURCE:
            continue
        missing = sorted(set(en) - set(msgs))
        extra = sorted(set(msgs) - set(en))
        if missing:
            problems.append(f"{code}.json: missing keys: {', '.join(missing)}")
        if extra:
            problems.append(f"{code}.json: extra keys (not in en.json): {', '.join(extra)}")
        for key in sorted(set(en) & set(msgs)):
            want = set(PLACEHOLDER.findall(en[key]))
            have = set(PLACEHOLDER.findall(msgs[key]))
            if want - have:
                problems.append(
                    f"{code}.json: '{key}' is missing placeholder(s) "
                    + ", ".join("{" + p + "}" for p in sorted(want - have))
                )
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dir", type=Path, default=DEFAULT_DIR, help="locales directory")
    args = ap.parse_args()
    problems = check_locales(args.dir)
    if problems:
        print("Locale check failed:\n")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(f"OK: {len(list(args.dir.glob('*.json')))} locale file(s) consistent with {SOURCE}.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
