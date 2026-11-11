"""Model-driven editor check (Playwright, Chromium), on the virtual models.

Starts nothing: point it at an already running instance on a SCRATCH config (it changes
``device.model`` and edits bindings, then undoes them and puts the model back):

    python -m open_loupedeck --config <scratch>/config.yaml --web 127.0.0.1:8803 --no-device
    python scripts/ui_models_check.py http://127.0.0.1:8803 [--chromium PATH] [--headed]

For virtual_mini, virtual_15 and virtual_mega (picked in Services > General > Hardware) it loads the
editor, checks the deck has every control of the model, selects a key, a knob and a button (when the
model has them) and assigns each an action / role, checks the saved config (control ids, the right
scope), switches page, undoes everything (Ctrl+Z) and checks the config is back. Any console error,
uncaught page error or failed request to the app fails the run (exit code 1); otherwise it prints OK.
The browser's ``/favicon.ico`` request and requests to other origins (CDN icons, web fonts) are
ignored.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any
from urllib.parse import urlsplit

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

MODELS = ("virtual_mini", "virtual_15", "virtual_mega")
DEFAULT_CHROMIUMS = (
    "/opt/pw-browsers/chromium-1243/chrome-linux64/chrome",
    "/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
)


def fetch_json(page, url: str) -> Any:
    return page.evaluate(f"fetch('{url}').then((r) => r.json())")


def wait_saved(page, predicate, what: str) -> dict:
    """Poll the stored config until `predicate(cfg)` (autosave is debounced by 500 ms)."""

    for _ in range(40):
        page.wait_for_timeout(150)
        cfg = fetch_json(page, "/api/config?format=v2")
        if predicate(cfg):
            return cfg
    raise AssertionError(f"not saved: {what}")


def current_page_index(page) -> int:
    return page.evaluate(
        "Array.from(document.querySelectorAll('#pageRail .pagetab'))"
        ".findIndex((t) => t.getAttribute('aria-selected') === 'true')"
    )


def pick_action(page) -> str:
    """Click the first action of the inspector's picker that is not the current one; its type."""

    row = page.locator('#keyEditorBlock .pk-act[aria-selected="false"]').first
    picked = row.get_attribute("data-type")
    row.click()
    page.wait_for_selector(f'#keyEditorBlock .pk-act[aria-selected="true"][data-type="{picked}"]')
    return picked


def check_model(page, model_id: str, info: dict, step) -> None:
    model = info["models"][model_id]
    step(f"{model_id}: select it in Services > General")
    page.click("#tabBtnServices")
    option = model["config_name"]
    page.select_option("#deviceModel", option)
    page.click("#tabBtnButtons")
    page.wait_for_selector(f'#deckRoot .dk-stage[aria-label^="{model["name"]}"]')
    wait_saved(page, lambda c: c["device"]["model"] == option, "device.model")
    before = fetch_json(page, "/api/config?format=v2")

    step(f"{model_id}: every control is drawn")
    drawn = set(page.eval_on_selector_all("#deckRoot .dk-ctl", "(n) => n.map((x) => x.dataset.cid)"))
    expected = {c["id"] for c in model["controls"]}
    if drawn != expected:
        raise AssertionError(
            f"deck controls differ: missing {sorted(expected - drawn)}, extra {sorted(drawn - expected)}"
        )
    by_kind = {k: [c["id"] for c in model["controls"] if c["kind"] == k] for k in ("key", "knob", "button")}
    pi = current_page_index(page)

    key = by_kind["key"][min(1, len(by_kind["key"]) - 1)]
    step(f"{model_id}: key {key} -> an action on this page")
    page.click(f'#deckRoot .dk-key[data-cid="{key}"]')
    page.wait_for_selector(f'#keyEditorBlock .insp-view[data-control="{key}"] .pk-act')
    picked = pick_action(page)
    wait_saved(
        page,
        lambda c: ((c["pages"][pi].get("controls") or {}).get(key) or {}).get("action", {}).get("type") == picked,
        f"{key} -> {picked} on page {pi + 1}",
    )

    if by_kind["knob"]:
        knob = by_kind["knob"][0]
        step(f"{model_id}: knob {knob} -> a rotation role")
        page.click(f'#deckRoot .dk-knob[data-cid="{knob}"]')
        page.wait_for_selector(f'#keyEditorBlock .kn-view[data-knob="{knob}"] .kn-duo[data-duo]')
        duo = page.get_attribute("#keyEditorBlock .kn-duo[data-duo]", "data-duo")
        page.click(f'#keyEditorBlock .kn-duo[data-duo="{duo}"]')
        wait_saved(
            page,
            lambda c: ((c["pages"][pi].get("controls") or {}).get(knob) or {}).get("rotate", {}).get("duo") == duo,
            f"{knob} rotate {duo}",
        )
        # The key showing the knob's feedback is outlined.
        fk = model["feedback_keys"].get(knob)
        if fk and not page.locator(f'#deckRoot .dk-key.is-knob-link[data-cid="{fk}"]').count():
            raise AssertionError(f"feedback key {fk} of {knob} is not outlined")

    if by_kind["button"]:
        button = by_kind["button"][-1]
        step(f"{model_id}: button {button} -> an action on every page")
        page.click(f'#deckRoot .dk-btn[data-cid="{button}"]')
        page.wait_for_selector(f'#keyEditorBlock .insp-view[data-control="{button}"] .pk-act')
        scope = page.get_attribute('#keyEditorBlock .insp-scope-seg button[aria-pressed="true"]', "data-scope")
        if scope != "global":
            raise AssertionError(f"a button edits {scope!r} by default, expected every page")
        picked_b = pick_action(page)
        wait_saved(
            page,
            lambda c: ((c.get("global") or {}).get(button) or {}).get("action", {}).get("type") == picked_b,
            f"{button} -> {picked_b} (global)",
        )

    step(f"{model_id}: switch page")
    other = (pi + 1) % len(before["pages"])
    page.locator("#pageRail .pagetab").nth(other).click()
    page.wait_for_function(
        f"document.querySelectorAll('#pageRail .pagetab')[{other}].getAttribute('aria-selected') === 'true'"
    )
    if page.locator(f'#deckRoot .dk-key.is-filled[data-cid="{key}"]').count():
        raise AssertionError(f"{key} still shows page {pi + 1}'s action on page {other + 1}")

    step(f"{model_id}: undo every change")
    edits = 1 + bool(by_kind["knob"]) + bool(by_kind["button"])
    page.locator("body").click(position={"x": 2, "y": 2})  # focus out of any field
    for _ in range(edits):
        page.keyboard.press("Control+z")
        page.wait_for_timeout(200)
    strip = lambda c: {k: v for k, v in c.items() if k not in ("onboarding_done",)}  # noqa: E731
    wait_saved(page, lambda c: strip(c) == strip(before), "config restored by Undo")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("base_url", help="e.g. http://127.0.0.1:8803")
    ap.add_argument("--chromium", default=os.environ.get("PW_CHROMIUM"), help="Chromium executable path")
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args()
    base = args.base_url.rstrip("/")
    origin = "{0.scheme}://{0.netloc}".format(urlsplit(base))
    chromium = args.chromium or next((c for c in DEFAULT_CHROMIUMS if os.path.exists(c)), None)
    errors: list[str] = []

    def on_console(msg) -> None:
        url = str((msg.location or {}).get("url", ""))
        if msg.type != "error" or url.endswith("/favicon.ico") or (url and not url.startswith(origin)):
            return
        errors.append(f"console error: {msg.text} ({url})")

    def on_response(resp) -> None:
        if resp.status >= 400 and resp.url.startswith(origin) and not resp.url.endswith("/favicon.ico"):
            errors.append(f"HTTP {resp.status}: {resp.url}")

    def on_request_failed(req) -> None:
        if req.url.startswith(origin):
            errors.append(f"request failed: {req.url} ({req.failure})")

    def step(name: str) -> None:
        print(f"- {name}")

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chromium, headless=not args.headed)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.on("console", on_console)
        page.on("pageerror", lambda exc: errors.append(f"page error: {exc}"))
        page.on("response", on_response)
        page.on("requestfailed", on_request_failed)
        page.set_default_timeout(10_000)
        original = None
        try:
            step("load the editor")
            page.goto(base + "/")
            page.wait_for_selector("#deckRoot .dk-stage, #obStartBlank")
            if page.locator("#obStartBlank").is_visible():
                page.click("#obStartBlank")
            page.wait_for_selector("#keyEditorBlock .insp-empty-state")
            page.wait_for_timeout(500)
            info = fetch_json(page, "/api/device_model")
            original = fetch_json(page, "/api/config?format=v2")["device"]["model"]
            for model_id in MODELS:
                if model_id not in info["models"]:
                    raise AssertionError(f"the server does not know {model_id}")
                check_model(page, model_id, info, step)
        except (PlaywrightError, AssertionError) as exc:
            errors.append(f"step failed: {exc}")
        finally:
            if original is not None:
                try:
                    step(f"put device.model back to {original!r}")
                    page.click("#tabBtnServices")
                    page.select_option("#deviceModel", original if original != "virtual_15" else "virtual")
                    wait_saved(page, lambda c: c["device"]["model"] in (original, "virtual"), "device.model restored")
                except (PlaywrightError, AssertionError) as exc:
                    errors.append(f"could not restore device.model: {exc}")
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
