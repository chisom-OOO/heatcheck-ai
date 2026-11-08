"""README Frost screenshot (Max, 8 Nov 2026): 'Is the hot hand real?' chip on the running demo
(demo.cmd --recorded-market, model on), Edge via Playwright. Prints the API answer it shows.

    uv run --frozen --with playwright python reports/max/2026-11-08-frost-demo/readme_shot.py OUT.png W H
"""
import json
import sys

from playwright.sync_api import sync_playwright

OUT, W, H = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
STAMP = "() => { const s = document.getElementById('stamp'); return s && !s.hidden && s.textContent.trim().length > 0; }"
with sync_playwright() as p:
    b = p.chromium.launch(channel="msedge")
    page = b.new_page(viewport={"width": W, "height": H})
    api, errs = [], []
    page.on("pageerror", lambda e: errs.append(str(e)))

    def on(r):
        if r.url.endswith("/api/dialogue"):
            d = r.json()
            api.append({"claim_id": d.get("claim_id"), "verdict": d.get("verdict"),
                        "mapping": (d.get("sources") or {}).get("mapping"),
                        "frost": [(f["check"], f["question"], f["chip"]) for f in d.get("frost") or []]})
    page.on("response", on)
    page.goto("http://127.0.0.1:8765/demo.html?voice=0", wait_until="networkidle")
    page.locator(".chip", has_text="Is the hot hand real?").click()
    page.wait_for_function(STAMP, timeout=120000)
    page.wait_for_timeout(6000)
    page.screenshot(path=OUT)
    print(json.dumps({"api": api, "errors": errs}, indent=1))
    b.close()
