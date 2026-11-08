"""Sunday board check (Max, 8 Nov 2026 ~10:10 UTC): demo.cmd --recorded-market --fresh-ledger after a
fresh capture_quotes.cmd. Edge 1440x900 headless, ?voice=0. Prints each card's price and verdict, the
'Earlier' row, and for one card the Ref box title and evidence dropdown.

    uv run --frozen --with playwright python reports/max/2026-11-08-frost-demo/board_check.py OUTDIR
"""
import json
import sys

from playwright.sync_api import sync_playwright

OUT = sys.argv[1]
with sync_playwright() as p:
    b = p.chromium.launch(channel="msedge")
    page = b.new_page(viewport={"width": 1440, "height": 900})
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    inv = {}
    page.on("response", lambda r: inv.__setitem__(len(inv), r.json()) if r.url.endswith("/api/investigate") and r.request.method == "POST" else None)
    page.goto("http://127.0.0.1:8765/demo.html?voice=0&board=1", wait_until="networkidle")
    page.wait_for_selector(".mcard", timeout=60000)
    page.wait_for_function("() => ![...document.querySelectorAll('.mcard')].some(c => /Checking/.test(c.textContent))", timeout=180000)
    page.wait_for_timeout(1000)
    cards = page.evaluate("""() => [...document.querySelectorAll('.mcard')].map(c => ({
        text: c.innerText.replace(/\\s+/g, ' ').slice(0, 600)}))""")
    earlier = page.evaluate("() => { const d = document.querySelector('.board-earlier'); return d ? d.querySelector('summary').textContent : null; }")
    page.screenshot(path=f"{OUT}/board-sunday.png", full_page=True)
    for i, c in enumerate(cards):
        print(json.dumps({"card": i + 1, "text": c["text"]}))
    for r in inv.values():
        g = r.get("game") or {}
        q = r.get("quote") or {}
        print(json.dumps({"api": f"{g.get('away_team')} at {g.get('home_team')}", "verdict": r.get("verdict"),
                          "bid": q.get("best_bid"), "ask": q.get("best_ask"), "venue": q.get("venue"),
                          "received": q.get("received_utc"), "mode": r.get("mode"), "ref_text": (r.get("ref_text") or "")[:220]}))
    print(json.dumps({"earlier_row": earlier, "n_cards": len(cards)}))
    # Ref box on one card
    page.locator(".mcard-ask:not(.board-retry):visible").first.click()
    page.wait_for_function("() => { const s = document.getElementById('stamp'); return s && !s.hidden && s.textContent.trim(); }", timeout=180000)
    page.wait_for_timeout(8000)
    ref = page.evaluate("""() => ({badge: document.querySelector('#ref .ref-badge')?.textContent,
        title: document.getElementById('ref-title')?.textContent, title_visible: !!document.getElementById('ref-title')?.offsetParent,
        evidence_visible: !!document.getElementById('evidence')?.offsetParent,
        summary: document.querySelector('#evidence summary')?.textContent})""")
    page.locator("#evidence summary").click()
    page.wait_for_timeout(800)
    ref["evidence_open_text"] = page.locator("#evidence-body").inner_text()[:700]
    page.screenshot(path=f"{OUT}/board-card-ref-evidence.png")
    print(json.dumps({"ref_box": ref, "page_errors": errs}))
    b.close()
