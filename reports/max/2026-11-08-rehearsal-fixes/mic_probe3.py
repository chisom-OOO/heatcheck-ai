import sys
from playwright.sync_api import sync_playwright
URL = "http://127.0.0.1:8765/demo.html?voice=0"
OPERA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 OPR/115.0.0.0"
out = sys.argv[1]
def run(p, label, launch, ctx_kw=None, init=None, click=True, wait=6000):
    b = p.chromium.launch(**launch); ctx = b.new_context(viewport={"width": 1280, "height": 900}, **(ctx_kw or {}))
    page = ctx.new_page(); errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    if init: page.add_init_script(init)
    page.goto(URL, wait_until="networkidle")
    vis = page.locator("#btn-mic").is_visible()
    if click and vis:
        page.locator("#btn-mic").click(); page.wait_for_timeout(wait)
    page.screenshot(path=f"{out}/mic_{label}.png", clip={"x": 0, "y": 700, "width": 1280, "height": 200})
    if label == "edge_fake_mic": print("   asked:", repr(page.locator("#q").input_value()))
    print(f"{label:22} button visible={vis!s:5} status={page.locator('#mic-status').inner_text()!r} errors={errs}")
    b.close()
with sync_playwright() as p:
    # run(p, "edge_blocked", {"channel": "msedge"})
    run(p, "edge_fake_mic", {"channel": "msedge", "args": ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"]}, wait=9000)
    # run(p, "opera_ua", {"channel": "msedge"}, {"user_agent": OPERA}, click=False)
    # run(p, "no_speech_api", {"channel": "msedge"}, init="delete window.SpeechRecognition; delete window.webkitSpeechRecognition;", click=False)
    run(p, "never_starts", {"channel": "msedge"}, init="window.SpeechRecognition = window.webkitSpeechRecognition = class { start(){} stop(){} abort(){} };", wait=5500)
