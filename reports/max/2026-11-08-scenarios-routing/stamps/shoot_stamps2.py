import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
DONE = "() => document.body.dataset.phase === 'done'"
NOT_DONE = "() => document.body.dataset.phase !== 'done'"
URL = "http://127.0.0.1:8765/demo.html?voice=0"


def confirm_and_read(page, tag, api):
    page.wait_for_function(DONE, timeout=90000)
    page.get_by_role("button", name="Yes").first.click()
    page.wait_for_function(NOT_DONE, timeout=30000)
    page.wait_for_function(DONE, timeout=90000)
    page.wait_for_timeout(1200)
    page.screenshot(path=str(out / f"{tag}.png"))
    stamp = page.locator("#stamp").inner_text() if page.locator("#stamp").is_visible() else "(none)"
    badge = page.locator(".scn-badge").last.inner_text()
    server = api[-1]["stamp"] if api else "(no response)"
    print(f"{tag}: page stamp {stamp!r}, panel badge {badge!r}, API stamp {server!r}")
    return stamp, badge, server


with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 1280, "height": 1000})
    console, api = [], []
    page.on("console", lambda m: console.append(m.text))
    page.on("pageerror", lambda e: console.append(f"PAGEERROR {e}"))

    def on_resp(r):
        if r.url.endswith("/api/scenario/estimate") and r.status == 200:
            api.append(json.loads(r.text()))
    page.on("response", on_resp)
    results = []

    # 1. Experience's "Your own scenario" box on the Detroit card: data -> ESTIMATE
    page.goto(URL, wait_until="networkidle")
    page.locator("#btn-board").click()
    page.wait_for_selector(".mcard .mcard-verdict", timeout=90000)
    card = page.locator(".mcard").filter(has_text="Detroit Pistons").first
    card.get_by_role("button", name="What if").first.click()
    card.locator(".scen-own-input").wait_for(timeout=30000)
    card.locator(".scen-own-input").fill("What if Detroit were without Cade Cunningham?")
    card.locator(".scen-own-go").click()
    results.append(confirm_and_read(page, "own_box_player_out", api))

    # 2. typed in the main box, user's number -> YOUR ASSUMPTION
    page.goto(URL, wait_until="networkidle")
    page.locator("#q").fill("Assume it costs Boston 5%")
    page.locator("#go").click()
    results.append(confirm_and_read(page, "typed_assumption", api))

    # 3. typed, Elo model -> ESTIMATE
    page.goto(URL, wait_until="networkidle")
    page.locator("#q").fill("What if Boston and Milwaukee played on a neutral floor?")
    page.locator("#go").click()
    results.append(confirm_and_read(page, "typed_neutral", api))

    print("AGREE", all(s == bd == sv for s, bd, sv in results))
    print("CONSOLE", console)
    b.close()
