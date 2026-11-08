import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
DONE = "() => document.body.dataset.phase === 'done'"
NOT_DONE = "() => document.body.dataset.phase !== 'done'"
URL = "http://127.0.0.1:8765/demo.html?voice=0"


def stamp(page):
    st = page.locator("#stamp")
    return st.inner_text() if st.is_visible() else "(stamp NOT visible)"


def typed(page, text):
    page.locator("#q").fill(text)
    page.locator("#go").click()


with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 1280, "height": 1000})
    console = []
    page.on("console", lambda m: console.append(f"{m.type}: {m.text}"))
    page.goto(URL, wait_until="networkidle")

    # 1. stamps
    chips = page.locator(".chip")
    for i in range(chips.count()):
        text = chips.nth(i).inner_text()
        chips.nth(i).click()
        if i:
            page.wait_for_function(NOT_DONE, timeout=30000)
        page.wait_for_function(DONE, timeout=90000)
        page.wait_for_timeout(1500)
        page.screenshot(path=str(out / f"01_chip{i + 1}.png"))
        print(f"CHIP {i + 1} {text!r}: stamp {stamp(page)!r}")

    # 2. Sunday-game scenario card (LA Lakers at Detroit) on Research's shrunk answers
    page.locator("#btn-board").click()
    page.wait_for_selector(".mcard .mcard-verdict", timeout=90000)
    page.wait_for_timeout(800)
    card = page.locator(".mcard").filter(has_text="Detroit Pistons").first
    card.scroll_into_view_if_needed()
    card.get_by_role("button", name="What if").first.click()
    page.wait_for_timeout(2500)
    card.screenshot(path=str(out / "02_sunday_scenario_card.png"))
    print("SUNDAY CARD", card.inner_text().replace("\n", " | ")[:1200])

    # 3. idea board
    page.locator("#btn-ideas").click()
    page.wait_for_timeout(2000)
    page.screenshot(path=str(out / "03_idea_board.png"), full_page=True)

    # 4. free-text routing
    page.goto(URL, wait_until="networkidle")
    typed(page, "find me an interesting market tonight")
    page.wait_for_selector(".board-heater", timeout=90000)
    page.wait_for_timeout(1200)
    page.screenshot(path=str(out / "04_route_board.png"))
    print("ROUTE BOARD", page.locator(".board-heater").first.inner_text())

    page.goto(URL, wait_until="networkidle")
    typed(page, "What about the Lakers and Pistons game?")
    page.wait_for_selector(".mcard-focus", timeout=90000)
    page.wait_for_timeout(1500)
    page.screenshot(path=str(out / "05_route_card.png"))
    print("ROUTE CARD", page.locator(".mcard-focus").inner_text()[:120].replace("\n", " | "))

    page.goto(URL, wait_until="networkidle")
    typed(page, "What if Detroit were without Cade Cunningham?")
    page.wait_for_function(DONE, timeout=90000)
    page.wait_for_timeout(800)
    page.screenshot(path=str(out / "06_whatif_reading.png"))
    print("READING", page.locator("#take").inner_text())
    page.get_by_role("button", name="Yes").first.click()
    page.wait_for_function(NOT_DONE, timeout=30000)
    page.wait_for_function(DONE, timeout=90000)
    page.wait_for_timeout(1500)
    page.screenshot(path=str(out / "07_whatif_estimate.png"), full_page=True)
    print("WHATIF REF", page.locator("#ref-text").inner_text())
    print("WHATIF STAMP", stamp(page))
    page.locator("#evidence summary").click()
    page.wait_for_timeout(500)
    print("EVIDENCE", page.locator("#evidence").inner_text().replace("\n", " | ")[:900])
    page.screenshot(path=str(out / "08_whatif_evidence.png"), full_page=True)
    print("CONSOLE", console)
    b.close()
