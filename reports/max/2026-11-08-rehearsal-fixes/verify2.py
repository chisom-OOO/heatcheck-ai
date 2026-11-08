import sys, time
from playwright.sync_api import sync_playwright
URL = "http://127.0.0.1:8776/demo.html?voice=0"
out = sys.argv[1]
with sync_playwright() as p:
    b = p.chromium.launch(channel="msedge"); page = b.new_page(viewport={"width": 1280, "height": 1000}); errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.goto(URL, wait_until="networkidle")
    t0 = time.time()
    page.locator("#q").fill("spurs vs trailblazers?"); page.locator("#go").click()
    page.wait_for_selector(".mcard-focus", timeout=60000)
    page.wait_for_timeout(1500)
    print(f"card focused after {time.time()-t0:.1f}s:", page.locator(".mcard-focus").first.inner_text().splitlines()[0])
    print("heater line:", page.locator(".board-heater").all_inner_texts())
    page.screenshot(path=f"{out}/route_spurs_fixed.png")
    # dialogue order: take before Ref, reaction after stamp
    page.goto(URL, wait_until="networkidle")
    page.locator("#q").fill("Is the hot hand real?"); page.locator("#go").click()
    page.wait_for_function("() => document.body.dataset.phase === 'take'", timeout=60000)
    print("TAKE (before Ref):", page.locator("#take").inner_text(), "| ref visible:", page.locator("#ref").is_visible())
    page.wait_for_function("() => document.body.dataset.phase === 'done'", timeout=90000)
    print("REF:", page.locator("#ref-text").inner_text()[:90]); print("STAMP:", page.locator("#stamp").inner_text())
    print("REACT (after stamp):", page.locator("#react").inner_text() if page.locator("#react").is_visible() else "(none)")
    # market card Ask: first line must not mention the Ref
    page.goto(URL, wait_until="networkidle"); page.locator("#btn-board").click()
    page.wait_for_selector(".mcard .mcard-ask", timeout=60000)
    card = page.locator(".mcard").filter(has_text="Chicago Bulls").first
    card.locator(".mcard-ask").click()
    page.wait_for_function("() => document.body.dataset.phase === 'take'", timeout=60000)
    print("MARKET TAKE:", page.locator("#take").inner_text())
    print("errors:", errs)
    b.close()
