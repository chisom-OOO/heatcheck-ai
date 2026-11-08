import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
URL = "http://127.0.0.1:8765/demo.html?voice=0"
with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 1280, "height": 1100})
    console = []
    page.on("console", lambda m: console.append(m.text))
    page.on("pageerror", lambda e: console.append(f"PAGEERROR {e}"))
    page.goto(URL, wait_until="networkidle")
    page.locator("#btn-board").click()
    page.wait_for_selector(".mcard .mcard-verdict", timeout=90000)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1500)
    cards = page.locator(".mcard")
    n_cav, first = 0, None
    for i in range(cards.count()):
        c = cards.nth(i)
        t = c.inner_text()
        title = t.splitlines()[0]
        diff = next((ln for ln in t.splitlines() if "ask" in ln and ("above" in ln or "below" in ln or "spread" in ln.lower())), "")
        has = c.locator(".mcard-caveat").count() > 0
        n_cav += has
        if has and first is None:
            first = i
        print(f"{title[:45]:45} | {diff[:32]:32} | caveat={has}")
    print("cards", cards.count(), "with caveat", n_cav)
    c = cards.nth(first)
    c.scroll_into_view_if_needed()
    page.evaluate("(i) => document.querySelectorAll('.mcard')[i].scrollIntoView({block:'start'})", first)
    page.wait_for_timeout(600)
    page.screenshot(path=str(out / "caveat_card.png"))
    c.locator(".mcard-ask").click()
    page.wait_for_function("() => document.body.dataset.phase !== 'done'", timeout=30000)
    page.wait_for_function("() => document.body.dataset.phase === 'done'", timeout=90000)
    page.wait_for_timeout(1500)
    page.screenshot(path=str(out / "caveat_ask.png"))
    print("HEATER", page.locator("#take").inner_text())
    print("REF", page.locator("#ref-text").inner_text())
    print("STAMP", page.locator("#stamp").inner_text())
    print("CONSOLE", console)
    b.close()
