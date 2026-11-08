"""Do scrolls during speech coincide with a new conversation line? (Max, 8 Nov 2026 ~09:05 UTC)
One hot-hand round, headless Edge 1440x900, voice on. Logs window.scrollY changes and DOM line additions.

    uv run --frozen --with playwright python reports/max/2026-11-08-frost-demo/scroll_cause.py
"""
import json

from playwright.sync_api import sync_playwright

INIT = """() => {
  window.__ev = [];
  let y = scrollY;
  setInterval(() => { if (scrollY !== y) { __ev.push({t: Math.round(performance.now()), k: 'scroll', y: Math.round(scrollY), speaking: speechSynthesis.speaking}); y = scrollY; } }, 25);
  new MutationObserver(ms => { for (const m of ms) for (const n of m.addedNodes) if (n.nodeType === 1 && n.offsetParent !== null)
    __ev.push({t: Math.round(performance.now()), k: 'add', cls: String(n.className).slice(0, 30), speaking: speechSynthesis.speaking}); })
    .observe(document.body, {childList: true, subtree: true});
  for (const a of ['hidden']) new MutationObserver(ms => { for (const m of ms) if (!m.target.hidden && m.target.offsetParent !== null)
    __ev.push({t: Math.round(performance.now()), k: 'shown', cls: (m.target.id || String(m.target.className)).slice(0, 30), speaking: speechSynthesis.speaking}); })
    .observe(document.body, {attributes: true, attributeFilter: [a], subtree: true});
}"""

with sync_playwright() as p:
    b = p.chromium.launch(channel="msedge", args=["--autoplay-policy=no-user-gesture-required"])
    page = b.new_page(viewport={"width": 1440, "height": 900})
    page.goto("http://127.0.0.1:8765/demo.html", wait_until="networkidle")
    page.evaluate(INIT)
    with page.expect_response(lambda r: r.url.endswith("/api/dialogue"), timeout=180000):
        page.locator(".chip", has_text="Is the hot hand real?").first.click()
    page.wait_for_function("() => { const s = document.getElementById('stamp'); return s && !s.hidden && s.textContent.trim(); }", timeout=180000)
    page.wait_for_function("() => !speechSynthesis.speaking", timeout=180000)
    page.wait_for_timeout(1500)
    ev = page.evaluate("() => __ev")
    adds = [e for e in ev if e["k"] in ("add", "shown")]
    scrolls = [e for e in ev if e["k"] == "scroll"]
    # a scroll is "caused" if a line was added/shown in the 1.5 s before it (smooth scroll + layout)
    orphan = [s for s in scrolls if not any(0 <= s["t"] - a["t"] <= 1500 for a in adds)]
    print(json.dumps({"scrolls": len(scrolls), "scrolls_while_speaking": sum(s["speaking"] for s in scrolls),
                      "scrolls_without_a_new_line_in_prior_1.5s": orphan, "adds": len(adds)}, indent=1))
    b.close()
