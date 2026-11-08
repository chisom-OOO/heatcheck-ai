"""Frost demo screenshots (Max, 8 Nov 2026): the three chips and one market card, with and without
?frost=sample, on the running demo (demo.cmd --recorded-market, model on). Edge via Playwright.

    uv run --frozen --with playwright python reports/max/2026-11-08-frost-demo/frost_shots.py OUTDIR
"""
import json
import sys

from playwright.sync_api import sync_playwright

OUT = sys.argv[1]
BASE = "http://127.0.0.1:8765/demo.html?voice=0"
CHIPS = ["Is the hot hand real?", "Do home teams win more?", "Does rest matter?"]
STAMP = "() => { const s = document.getElementById('stamp'); return s && !s.hidden && s.textContent.trim().length > 0; }"


def run(page, label, api, errs):
    page.wait_for_function(STAMP, timeout=120000)
    page.wait_for_timeout(6000)   # reactions after the stamp
    page.screenshot(path=f"{OUT}/{label}.png")
    frost_on_page = page.evaluate("() => [...document.querySelectorAll('[class*=frost]')].filter(e => e.offsetParent && e.textContent.trim()).length")
    print(json.dumps({"shot": label, "api": api[-1:] or None, "frost_elements_visible": frost_on_page,
                      "stamp": page.locator("#stamp").inner_text(), "errors": errs[:]}))


with sync_playwright() as p:
    b = p.chromium.launch(channel="msedge")
    for suffix, tag in (("", "live"), ("&frost=sample", "sample")):
        for i, chip in enumerate(CHIPS):
            page = b.new_page(viewport={"width": 1440, "height": 900})
            api, errs = [], []
            page.on("pageerror", lambda e, errs=errs: errs.append(str(e)))

            def on_resp(r, api=api):
                if r.url.endswith("/api/dialogue"):
                    try:
                        d = r.json()
                        api.append({"claim_id": d.get("claim_id"), "verdict": d.get("verdict"),
                                    "frost_n": len(d.get("frost") or []), "frost_source": (d.get("sources") or {}).get("frost")})
                    except Exception as e:  # noqa: BLE001
                        api.append({"status": r.status, "parse": type(e).__name__})
            page.on("response", on_resp)
            page.goto(BASE + suffix, wait_until="networkidle")
            page.locator(".chip", has_text=chip).click()
            try:
                run(page, f"{tag}-chip{i + 1}", api, errs)
            except Exception as e:  # noqa: BLE001
                page.screenshot(path=f"{OUT}/{tag}-chip{i + 1}-TIMEOUT.png")
                print(json.dumps({"shot": f"{tag}-chip{i + 1}", "error": f"{type(e).__name__}: {str(e)[:200]}", "api": api, "errors": errs}))
            page.close()
        # one market card: the first card with an Ask button
        page = b.new_page(viewport={"width": 1440, "height": 900})
        api, errs = [], []
        page.on("pageerror", lambda e, errs=errs: errs.append(str(e)))

        def on_inv(r, api=api):
            if r.url.endswith("/api/investigate") and r.request.method == "POST":
                try:
                    d = r.json()
                    api.append({"verdict": d.get("verdict"), "frost_n": len(d.get("frost") or []), "team": d.get("team")})
                except Exception:  # noqa: BLE001
                    pass
        page.on("response", on_inv)
        page.goto(BASE + suffix + "&board=1", wait_until="networkidle")
        page.wait_for_selector(".mcard-ask:not(.board-retry)", timeout=60000)
        page.wait_for_timeout(1500)
        btn = page.locator(".mcard-ask:not(.board-retry):visible").first
        btn.click()
        try:
            run(page, f"{tag}-market", api, errs)
        except Exception as e:  # noqa: BLE001
            page.screenshot(path=f"{OUT}/{tag}-market-TIMEOUT.png")
            print(json.dumps({"shot": f"{tag}-market", "error": f"{type(e).__name__}: {str(e)[:200]}", "api": api[-1:], "errors": errs}))
        page.close()
    b.close()
