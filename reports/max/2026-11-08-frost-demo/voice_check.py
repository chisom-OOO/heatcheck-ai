"""Rehearsal check (Max, 8 Nov 2026 ~09:00 UTC): demo.cmd --recorded-market --fresh-ledger, fresh quotes,
Edge 1440x900 headless, voice ON (headed window was closed twice ~20 s in, from outside the page) (no ?voice=0), model on.

Checks:
  chips: three rounds in one page; after the last, the Ref card and the stamp are inside the viewport.
  market: one card shows Frost's three challenges and his reaction.
  all runs: no Frost line is clipped (scrollWidth > clientWidth or overflowing its column/viewport), and
  the scroll position never moves while speechSynthesis.speaking (sampled every 100 ms).

    uv run --frozen --with playwright python reports/max/2026-11-08-frost-demo/voice_check.py OUTDIR
"""
import json
import sys

from playwright.sync_api import sync_playwright

OUT = sys.argv[1]
BASE = "http://127.0.0.1:8765/demo.html"
CHIPS = ["Is the hot hand real?", "Do home teams win more?", "Does rest matter?"]

MONITOR = """() => {
  window.__samples = [];
  const scroller = () => { const c = [...document.querySelectorAll('*')].filter(e => e.scrollHeight > e.clientHeight + 4 &&
      /(auto|scroll)/.test(getComputedStyle(e).overflowY)); return c; };
  setInterval(() => {
    const sc = scroller().map(e => (e.id || e.className || e.tagName).toString().slice(0, 30) + ':' + Math.round(e.scrollTop));
    window.__samples.push({t: Math.round(performance.now()), speaking: !!(window.speechSynthesis && speechSynthesis.speaking),
                           y: Math.round(window.scrollY), sc: sc.join('|')});
  }, 100);
}"""

FROST_LINES = """() => {
  const vw = innerWidth, vh = innerHeight;
  return [...document.querySelectorAll('[class*=frost]')].filter(e => e.offsetParent && e.textContent.trim() && e.children.length === 0 || (e.offsetParent && /bubble|chip|line|reaction/.test(e.className) && /frost/.test(e.className))).map(e => {
    const r = e.getBoundingClientRect();
    return {cls: e.className.toString().slice(0, 40), text: e.textContent.trim().slice(0, 60),
            clippedX: e.scrollWidth > e.clientWidth + 1, clippedY: e.scrollHeight > e.clientHeight + 1 && getComputedStyle(e).overflowY !== 'visible',
            left: Math.round(r.left), right: Math.round(r.right), offscreenX: r.left < 0 || r.right > vw};
  });
}"""

IN_VIEW = """(sel) => { const e = document.querySelector(sel); if (!e || e.hidden || !e.offsetParent) return null;
  const r = e.getBoundingClientRect(); const foot = document.getElementById('ru-footer');
  const fy = foot ? foot.getBoundingClientRect().top : innerHeight;
  return {top: Math.round(r.top), bottom: Math.round(r.bottom), footer_top: Math.round(fy), inside: r.top >= 0 && r.bottom <= fy + 1}; }"""


def jumps(samples):
    """Scroll changes while someone is speaking (between two consecutive samples both speaking)."""
    out = []
    for a, b in zip(samples, samples[1:]):
        if a["speaking"] and b["speaking"] and (a["y"] != b["y"] or a["sc"] != b["sc"]):
            out.append({"t": b["t"], "from": [a["y"], a["sc"]], "to": [b["y"], b["sc"]]})
    return out


def wait_quiet(page, ms=120000):
    page.wait_for_function("() => !(window.speechSynthesis && speechSynthesis.speaking)", timeout=ms)


with sync_playwright() as p:
    b = p.chromium.launch(channel="msedge", headless=True, args=["--autoplay-policy=no-user-gesture-required"])
    ctx = b.new_context(viewport={"width": 1440, "height": 900})
    errs = []
    voices = None

    # ---- three chips in one page, voice on
    page = ctx.new_page()
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.on("close", lambda _: print("PAGE CLOSED", flush=True))
    page.on("crash", lambda _: print("PAGE CRASHED", flush=True))
    b.on("disconnected", lambda _: print("BROWSER DISCONNECTED", flush=True))
    api = []
    page.on("response", lambda r: api.append(r.json() if r.url.endswith("/api/dialogue") else None) if r.url.endswith("/api/dialogue") else None)
    page.goto(BASE, wait_until="networkidle")
    page.wait_for_timeout(1500)
    voices = page.evaluate("() => speechSynthesis.getVoices().map(v => v.name).slice(0, 6)")
    page.evaluate(MONITOR)
    for i, chip in enumerate(CHIPS):
        page.wait_for_selector(f".chip:has-text('{chip}'):not([disabled])", timeout=180000)
        n0 = page.evaluate("() => window.__samples.length")
        with page.expect_response(lambda r: r.url.endswith("/api/dialogue"), timeout=180000):
            page.locator(".chip", has_text=chip).first.click()
        page.wait_for_function("() => { const s = document.getElementById('stamp'); return s && !s.hidden && s.textContent.trim(); }", timeout=180000)
        page.wait_for_timeout(1000)
        wait_quiet(page, 180000)
        page.wait_for_timeout(1500)
        page.screenshot(path=f"{OUT}/voice-round{i + 1}.png")
        print(json.dumps({"round": i + 1, "chip": chip,
                          "api": {k: (api[-1] or {}).get(k) for k in ("claim_id", "verdict")} if api else None,
                          "frost_n": len((api[-1] or {}).get("frost") or []) if api else None,
                          "ref_card": page.evaluate(IN_VIEW, "#ref") or page.evaluate(IN_VIEW, ".ref-card"),
                          "stamp": page.evaluate(IN_VIEW, "#stamp"),
                          "frost_clipped": [x for x in page.evaluate(FROST_LINES) if x["clippedX"] or x["clippedY"] or x["offscreenX"]],
                          "speaking_samples_this_round": sum(x["speaking"] for x in page.evaluate("() => window.__samples")[n0:])}))
    s = page.evaluate("() => window.__samples")
    print(json.dumps({"chips_speaking_samples": sum(x["speaking"] for x in s), "samples": len(s), "jumps_while_speaking": jumps(s)[:12],
                      "n_jumps": len(jumps(s)), "voices": voices}))
    page.close()

    # ---- one market card, voice on
    page = ctx.new_page()
    page.on("pageerror", lambda e: errs.append(str(e)))
    inv = []
    page.on("response", lambda r: inv.append(r.json()) if r.url.endswith("/api/investigate") and r.request.method == "POST" else None)
    page.goto(BASE + "?board=1", wait_until="networkidle")
    page.wait_for_selector(".mcard-ask:not(.board-retry)", timeout=60000)
    page.wait_for_timeout(1500)
    page.evaluate(MONITOR)
    page.locator(".mcard-ask:not(.board-retry):visible").first.click()
    page.wait_for_function("() => { const s = document.getElementById('stamp'); return s && !s.hidden && s.textContent.trim(); }", timeout=180000)
    page.wait_for_timeout(1000)
    wait_quiet(page, 180000)
    page.wait_for_timeout(1500)
    page.screenshot(path=f"{OUT}/voice-market.png")
    d = inv[-1] if inv else {}
    shown = page.evaluate("""(qs) => { const t = document.body.innerText; return qs.map(q => t.includes(q)); }""",
                          [f["question"] for f in d.get("frost") or []] + [f["chip"] for f in d.get("frost") or []] + [d.get("frost_reaction") or "<none>"])
    s = page.evaluate("() => window.__samples")
    print(json.dumps({"market": d.get("team"), "verdict": d.get("verdict"), "api_frost_n": len(d.get("frost") or []),
                      "questions_chips_reaction_on_page": shown,
                      "ref_card": page.evaluate(IN_VIEW, "#ref") or page.evaluate(IN_VIEW, ".ref-card"), "stamp": page.evaluate(IN_VIEW, "#stamp"),
                      "frost_clipped": [x for x in page.evaluate(FROST_LINES) if x["clippedX"] or x["clippedY"] or x["offscreenX"]],
                      "speaking_samples": sum(x["speaking"] for x in s), "n_jumps": len(jumps(s)), "jumps_while_speaking": jumps(s)[:12]}))
    page.close()
    print(json.dumps({"page_errors": errs}))
    b.close()
