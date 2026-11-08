"""Real tamper click-through (Max, 8 Nov 2026), Edge via Playwright against the running demo.

    uv run --frozen --with playwright python reports/max/2026-11-08-frost-demo/tamper_clicks.py OUTDIR

Demo: demo.cmd --recorded-market on 8765/8770 (tamper on). --no-tamper instance: Max's API on 8776
started with --no-tamper, page server on 8775 forwarding to it.
"""
import json
import sys
import time

from playwright.sync_api import sync_playwright

OUT = sys.argv[1]


def logger(page, calls):
    def on(r):
        if "/api/tamper/" in r.url:
            try:
                body = r.json()
            except Exception:  # noqa: BLE001
                body = None
            calls.append({"t": round(time.monotonic(), 2), "method": r.request.method,
                          "path": r.url.split("8765")[-1].split("8775")[-1], "status": r.status, "body": body})
    page.on("response", on)


def panel(page):
    return page.locator("#tamper").inner_text() if page.locator("#tamper").is_visible() else ""


with sync_playwright() as p:
    b = p.chromium.launch(channel="msedge")
    errs = []

    # 0. default: button hidden
    page = b.new_page(viewport={"width": 1440, "height": 900})
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.goto("http://127.0.0.1:8765/demo.html?voice=0", wait_until="networkidle")
    print(json.dumps({"step": "default page", "button_visible": page.locator("#btn-tamper").is_visible()}))
    page.close()

    # 1. ?tamper=1: flip, events, restore, then a second flip within 5 s of the first -> 429
    page = b.new_page(viewport={"width": 1440, "height": 900})
    page.on("pageerror", lambda e: errs.append(str(e)))
    calls = []
    logger(page, calls)
    page.goto("http://127.0.0.1:8765/demo.html?voice=0&tamper=1", wait_until="networkidle")
    print(json.dumps({"step": "?tamper=1", "button_visible": page.locator("#btn-tamper").is_visible()}))
    t0 = time.monotonic()
    page.locator("#btn-tamper").click()
    page.wait_for_function("() => { const s = document.getElementById('stamp'); return s && !s.hidden && /DATA/i.test(s.textContent); }", timeout=60000)
    page.wait_for_function("() => /TAMPER_ATTEMPT|evidence_id|event/i.test(document.getElementById('tamper').textContent)", timeout=20000)
    page.wait_for_timeout(1500)
    page.screenshot(path=f"{OUT}/tamper-1-flip.png")
    print(json.dumps({"step": "flip", "panel": panel(page)[:900], "stamp": page.locator("#stamp").inner_text()}))
    page.locator("#btn-restore").click()
    page.wait_for_function("() => /deleted|restored/i.test(document.getElementById('tamper').textContent)", timeout=20000)
    page.wait_for_timeout(500)
    page.screenshot(path=f"{OUT}/tamper-2-restore.png")
    print(json.dumps({"step": "restore", "panel": panel(page)[:500]}))
    page.locator("#btn-tamper").click()
    since = time.monotonic() - t0
    page.wait_for_timeout(2500)
    page.screenshot(path=f"{OUT}/tamper-3-second-flip.png")
    print(json.dumps({"step": "second flip", "seconds_after_first": round(since, 2), "panel": panel(page)[:500]}))
    print(json.dumps({"api_calls": [{k: c[k] for k in ("method", "path", "status")} for c in calls]}))
    print(json.dumps({"flip_body": next((c["body"] for c in calls if c["path"].endswith("/flip") and c["status"] == 200), None)}))
    page.close()

    # 2. --no-tamper server -> 503
    page = b.new_page(viewport={"width": 1440, "height": 900})
    page.on("pageerror", lambda e: errs.append(str(e)))
    calls = []
    logger(page, calls)
    page.goto("http://127.0.0.1:8775/demo.html?voice=0&tamper=1", wait_until="load")
    page.wait_for_selector("#btn-tamper:not([hidden])", timeout=30000)
    page.locator("#btn-tamper").click()
    page.wait_for_timeout(3000)
    page.screenshot(path=f"{OUT}/tamper-4-no-tamper-503.png")
    print(json.dumps({"step": "--no-tamper", "panel": panel(page)[:500],
                      "api_calls": [{k: c[k] for k in ("method", "path", "status")} for c in calls]}))
    page.close()
    print(json.dumps({"page_errors": errs}))
    b.close()
