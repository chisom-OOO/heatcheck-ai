# Rehearsal check after experience/frost@49fc49c (Max, 8 Nov 2026, 08:53–09:05 UTC)

- **Setup:**
  - `experience/frost@49fc49c` merged unchanged as `4ecff2d` (every file identical).
  - Fresh read-only quotes: `capture_quotes.cmd` at 08:53:56 UTC; 7/7 Polymarket bundles VERIFIED;
    no key in 116 files.
  - `demo.cmd --recorded-market --fresh-ledger`, model on.
- **Browser:** Edge 1440x900 via Playwright, voice ON (no `?voice=0`), autoplay allowed. Speech played:
  `speechSynthesis.speaking` was true in 1,669 of 2,015 samples over the three rounds.
- **Headless:** the visible window was closed by the user twice, about 20 s in, so this run is headless.

| Check | Result |
|---|---|
| Three chip rounds in one page | CONF-HH (3 Frost), CONF-HA (2), GP-REST (3); fixed routes |
| Ref card and stamp on screen after each round, above the footer | PASS: card bottom 806 px, stamp bottom ≤ 855 px, footer top 870 px |
| Market card (Chicago Bulls, RECORDED) shows Frost's 3 questions, 3 chips and reaction | PASS (7/7 strings on the page) |
| Frost's lines not cut off | PASS by screenshot: `voice-round1/2.png`, `voice-market.png`. The script's `scrollWidth` flag on reactions is the bubble's tail, not text. Earlier chips fold to one line with "…" by design (hover shows them). |
| Page does not jump mid-speech | PASS: 10/10 scrolls during speech came within 1.5 s after a new line appeared (`scroll_cause.out.txt`); smooth scroll-into-view, no uncaused movement |
| Page errors | none |

**Broken and fixed** (user report): `hot_take.webp` shows Heater with three arms. The `hot_take`
state now uses the `thinking` pose (ball spinning, hand on hip). The image stays on disk, unused.
Commit `5811133`; node 150 pass.

Scripts: `reports/max/2026-11-08-frost-demo/voice_check.py`, `scroll_cause.py`. Raw output: `voice_check.out.txt`.
