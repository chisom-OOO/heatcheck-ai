import sys, json
from playwright.sync_api import sync_playwright
S = sys.argv[1]
with sync_playwright() as p:
    b = p.chromium.launch(channel="msedge", args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
                                                  f"--use-file-for-fake-audio-capture={S}/spurs.wav"])
    page = b.new_page(viewport={"width": 1280, "height": 900}); errs, api = [], []
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.on("response", lambda r: api.append((r.status, r.text()[:300])) if r.url.endswith("/api/transcribe") else None)
    page.goto("http://127.0.0.1:8776/demo.html?voice=0", wait_until="networkidle")
    seen = []
    page.locator("#mic-status").evaluate("(el) => { window.__st = []; new MutationObserver(() => window.__st.push(el.textContent)).observe(el, {childList: true, characterData: true, subtree: true}); }")
    page.locator("#btn-mic").click()           # tap to start
    page.wait_for_timeout(4500)
    page.locator("#btn-mic").click()           # tap to stop
    page.wait_for_function("() => document.getElementById('q').value.length > 0 || /unavailable|catch|blocked/i.test(document.getElementById('mic-status').textContent)", timeout=45000)
    page.wait_for_timeout(500)
    page.screenshot(path=f"{S}/real_voice_box.png")
    print("API:", api)
    print("question box:", repr(page.locator("#q").input_value()))
    print("status line:", repr(page.locator("#mic-status").inner_text()))
    print("status sequence:", page.evaluate("() => window.__st"))
    print("asked automatically:", page.evaluate("() => document.body.dataset.phase || ''") not in ("", "idle"), "| errors:", errs)
    b.close()
