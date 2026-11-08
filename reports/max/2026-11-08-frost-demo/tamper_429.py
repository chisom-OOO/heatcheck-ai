"""429 within 5 s on the real route, shown by the page (Max, 8 Nov 2026).
A flip is sent from inside the page (fetch, same origin), then the red button is clicked at once."""
import json
import sys
import time

from playwright.sync_api import sync_playwright

OUT = sys.argv[1]
with sync_playwright() as p:
    b = p.chromium.launch(channel="msedge")
    page = b.new_page(viewport={"width": 1440, "height": 900})
    errs, calls = [], []
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.on("response", lambda r: calls.append((round(time.monotonic(), 2), r.request.method, r.url.split("8765")[-1], r.status)) if "/api/tamper/" in r.url else None)
    page.goto("http://127.0.0.1:8765/demo.html?voice=0&tamper=1", wait_until="networkidle")
    first = page.evaluate("async () => { const r = await fetch('/api/tamper/flip', {method: 'POST'}); return [r.status, await r.json()]; }")
    page.locator("#btn-tamper").click()
    page.wait_for_function("() => /429|wait|limit|seconds/i.test(document.getElementById('tamper').textContent)", timeout=20000)
    page.wait_for_timeout(800)
    page.screenshot(path=f"{OUT}/tamper-5-429-within-5s.png")
    print(json.dumps({"first_flip_status": first[0], "panel": page.locator("#tamper").inner_text()[:400], "calls": calls, "errors": errs}))
    page.evaluate("async () => { await fetch('/api/tamper/restore', {method: 'POST'}); }")
    b.close()
