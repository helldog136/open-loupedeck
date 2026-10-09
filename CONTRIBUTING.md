# Contributing

## Add a language in 3 steps

1. Copy `src/open_loupedeck/locales/en.json` to `src/open_loupedeck/locales/<code>.json` and set `_meta.name` to the
   language's own name.
2. Translate the values (by meaning, not word for word; keep `{placeholders}` and the keys unchanged).
3. Run `python scripts/check_locales.py`, then open a pull request.

Details, plural rules and how to test locally: [docs/translating.md](docs/translating.md).

## Code

`ruff format src tests`, `ruff check src tests` and `python -m pytest -q` must pass. User-visible strings go through
`t()` (see `src/open_loupedeck/i18n.py` and `static/i18n.js`); log messages stay in English.
