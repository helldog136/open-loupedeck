# Translating open-loupedeck

English (`en`) is the source language, French (`fr`) ships too. Adding a language is a single JSON file and no code.

## Add a language in 3 steps

1. **Copy** `src/open_loupedeck/locales/en.json` to `src/open_loupedeck/locales/<code>.json`
   (`<code>` is a short language code such as `de`, `es`, `pt-BR`). Set `_meta.name` to the language's *own* name
   (`"Deutsch"`, `"Español"`): that is what appears in the language selector.
2. **Translate** every value. Keep the keys unchanged.
3. **Check** with `python scripts/check_locales.py`, then open a pull request. CI runs the same check
   (`tests/test_locales.py`) and fails if your file has missing or extra keys, an empty value, or a lost placeholder.

## Rules

- **Translate by meaning, not word for word.** Use the wording a native speaker would expect on a button or in a menu;
  keep it about as short as the English, since labels live in small spaces (tray menu, buttons).
- **Keep placeholders exactly**: `{version}`, `{count}`, `{error}`... They are replaced at runtime; you may move them
  within the sentence but not rename, translate or drop them.
- **Plurals**: keys ending in `.one` / `.other` (for example `pages.count.one`, `pages.count.other`) are chosen from
  the `{count}` value. Provide both. (French treats 0 and 1 as "one"; Japanese, Chinese and Korean always use
  `.other`.)
- Do not translate product and service names (OBS, Home Assistant, Spotify, Twitch) or log messages (logs stay English).
- Keep `app.name` as is.
- A key that is missing at runtime falls back to English, then to the key itself, so a partial file never crashes the
  app, but CI requires completeness.

## Testing locally

```
pip install -e ".[dev]"
python scripts/check_locales.py
open-loupedeck --config /tmp/scratch/config.yaml --web 127.0.0.1:8774 --no-device
```

Open `http://127.0.0.1:8774`, go to the Services tab, **Language**, and pick your language: it applies immediately.
`http://127.0.0.1:8774/api/locale/<code>` shows the merged dictionary. You can also set `language: <code>` in
`config.yaml`; the default `auto` follows the operating system language.

## For developers

- Python: `from open_loupedeck.i18n import t`; `t("tray.quit")`, `t("tray.update.install", version="1.2")`,
  `t("pages.count", count=3)`. Never raises; falls back to English, then to the key.
- Web: `window.t("common.save")`, or `data-i18n="common.save"` / `data-i18n-attr="title:common.save"` in HTML;
  wait for `window.i18n.ready` before first render; listen to the `i18n:change` event to re-render dynamic parts.
- Add new keys to `en.json` **and** `fr.json` in the same change; `section.sub.name` naming, lowercase.

## The action catalog

Every action's name, field labels, placeholders, select options and category, plus the default key labels, live in the
same JSON files under three families of keys:

- `action.<type>.label`, `action.<type>.field.<name>.label|placeholder|help`, `action.<type>.field.<name>.option.<value>`
- `category.<slug>`
- `look.<type>.label` (the short text proposed on a key)

`python scripts/check_catalog_keys.py` lists catalog keys that are missing from a locale file (and stray ones). Technical
placeholders such as `{twitch_status}` must be kept; plain numbers and HTTP verbs are not translated. The web API
`GET /api/action_catalog?lang=fr` returns the catalog already translated, with the `*_key` of each text.
