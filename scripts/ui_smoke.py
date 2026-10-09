"""Smoke test for the config web UI (Playwright, Chromium).

Starts nothing: point it at an already running instance, ideally on a scratch config
(``python -m open_loupedeck --config <scratch>/config.yaml --web 127.0.0.1:8775 --no-device``).
It loads the page, switches both tabs, selects a touch key, picks an action type in the action
picker (which autosaves), then presses Ctrl+Z and checks the saved config is back to how it started.
Any console error, uncaught page error or failed request fails the run (exit code 1); otherwise it
prints ``OK``.

    python scripts/ui_smoke.py http://127.0.0.1:8775
    python scripts/ui_smoke.py http://127.0.0.1:8775 --chromium /path/to/chrome --ignore-external

Needs ``pip install playwright`` and a Chromium (``playwright install chromium``, or ``--chromium``).
The browser's automatic ``/favicon.ico`` request (the app serves none) is not counted as an error.
"""

from __future__ import annotations

import argparse
import os
import sys
from urllib.parse import urlsplit

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

DEFAULT_CHROMIUM = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"


def fetch_config(page) -> dict:
    return page.evaluate("fetch('/api/config').then((r) => r.json())")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("base_url", help="e.g. http://127.0.0.1:8775")
    ap.add_argument("--chromium", default=os.environ.get("PW_CHROMIUM"), help="Chromium executable path")
    ap.add_argument(
        "--ignore-external",
        action="store_true",
        help="do not fail on failed requests to other origins (e.g. web fonts while offline)",
    )
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args()
    base = args.base_url.rstrip("/")
    origin = "{0.scheme}://{0.netloc}".format(urlsplit(base))
    chromium = args.chromium or (DEFAULT_CHROMIUM if os.path.exists(DEFAULT_CHROMIUM) else None)

    errors: list[str] = []

    def on_console(msg) -> None:
        if msg.type != "error":
            return
        url = str((msg.location or {}).get("url", ""))
        if url.endswith("/favicon.ico"):
            return
        if args.ignore_external and url and not url.startswith(origin):
            return  # e.g. "Failed to load resource" for a CDN icon while offline
        errors.append(f"console error: {msg.text} ({(msg.location or {}).get('url', '')})")

    def on_request_failed(req) -> None:
        if args.ignore_external and not req.url.startswith(origin):
            print(f"warning: external request failed: {req.url} ({req.failure})")
            return
        errors.append(f"request failed: {req.url} ({req.failure})")

    def on_response(resp) -> None:
        if resp.status >= 400 and not resp.url.endswith("/favicon.ico"):
            if args.ignore_external and not resp.url.startswith(origin):
                return
            errors.append(f"HTTP {resp.status}: {resp.url}")

    def step(name: str) -> None:
        print(f"- {name}")

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chromium, headless=not args.headed)
        page = browser.new_page(viewport={"width": 1400, "height": 1000})
        page.on("console", on_console)
        page.on("pageerror", lambda exc: errors.append(f"page error: {exc}"))
        page.on("requestfailed", on_request_failed)
        page.on("response", on_response)
        page.set_default_timeout(10_000)
        try:
            step("load page")
            page.goto(base + "/")
            page.wait_for_selector("#deckRoot .dk-key")
            page.wait_for_selector("#keyEditorBlock .insp-empty-state")  # inspector mounted (catalog loaded)
            page.wait_for_timeout(500)  # rest of the boot sequence (status, wiring)
            config_before = fetch_config(page)

            step("Services tab")
            page.click("#tabBtnServices")
            page.wait_for_selector("#tabPanelServices:not([hidden])")
            step("Buttons tab")
            page.click("#tabBtnButtons")
            page.wait_for_selector("#tabPanelButtons:not([hidden])")

            step("select touch_0")
            page.click('.dk-key[data-cid="touch_0"]')
            page.wait_for_selector('#keyEditorBlock .insp-view[data-control="touch_0"] .pk-act')

            step("pick an action type")
            selected = '#keyEditorBlock .pk-act[aria-selected="true"]'
            before = page.get_attribute(selected, "data-type") if page.locator(selected).count() else ""
            page.locator('#keyEditorBlock .pk-act[aria-selected="false"]').first.click()
            page.wait_for_selector(selected)
            picked = page.get_attribute(selected, "data-type")
            if not picked or picked == before:
                raise AssertionError(f"action type did not change (still {before!r})")
            print(f"  action type: {before or '(none)'} -> {picked}")

            step("undo (restore the config)")
            page.wait_for_timeout(300)
            page.keyboard.press("Control+z")
            for _ in range(20):  # debounced autosave (500 ms) + PUT
                page.wait_for_timeout(250)
                if fetch_config(page) == config_before:
                    break
            else:
                raise AssertionError("config not restored after Ctrl+Z")
        except (PlaywrightError, AssertionError) as exc:
            errors.append(f"step failed: {exc}")
        finally:
            browser.close()

    if errors:
        print("FAILED")
        for e in errors:
            print(f"  {e}")
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
