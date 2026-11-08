# Experience: safer-gambling notice on the demo page

- **Branch:** `experience/market-board`.
- **Merge:** **017001e** merges integrate **737b29d** (Max's safer-gambling wording) cleanly.
- **Code commit:** **7a49dd5**. All checks below ran on 7a49dd5 with a clean worktree. This report and its log
  are in the commit after it.
- **Max can merge it as a fast-forward** of 737b29d. It also carries 8983f3b, the voice review report.
- **Source:** `reports/max/2026-11-08-0514-safer-gambling.md`, §2: "Page footer, board header, first-ask panel:
  read from the JSON. **Experience**".
- **Not touched:** the wording itself. Max's `responsible_use.json` is the only source.
- **Also not touched:** numbers, verdicts, the mic and voice code, `heatcheck/`. No gate is marked.
- **This is not legal advice.** The user and the adviser review the wording before the demo.

## Where the notice now shows

| Place | Text | How |
|---|---|---|
| Page footer, every view, always visible | Max's `short` | Static in `demo.html`, so it shows even without JavaScript. The page then sets it from the JSON. A test keeps the two word for word equal. |
| "Tonight's games" header, above the cards | Max's `full` | `renderBoard(..., {notice})` in `market/board.js`, class `board-notice`, `role="note"`. Not shown on the board's error view, which shows no prices. |
| The first market Ask, card what-if or own scenario of a browser session | Max's `full` | `showFirstAskNotice()` in `demo.js`, shown above Heater's first line in `askMarket`, `askScenario` and `runScenario`. Once per session (`sessionStorage`, with an in-memory fallback). It stays until "Got it" or a view change and never blocks the answer. |

- **If `responsible_use.json` cannot be read,** the footer's static short text stays. The board header and the
  first-ask panel then show that short text.
- **Styling is calm:** muted text with a thin teal rule, and no orange fills, so it doesn't look like an ad. On a
  phone the footer is the last row of the layout.
- **No links:** the footer, header and panel contain no link (`gamcare.org.uk` is plain text). Max's test still
  finds no `polymarket.com` or `kalshi.com` link in the pages.

## Max's open item: Heater's fallback lines, done

`web/heater/heater-model.js` `PLACEHOLDER_LINES` are used only if `heater_personality.json` fails to load:
- GP-REST: "Fresh legs WIN games. ~~Bet the rested team~~ **The rested team takes it**, every time!"
- "*": "I've seen enough. ~~This one is a LOCK!~~ **I KNOW I'm right about this one!**"

Max's `todo` test in `apps/web/tests/safer_gambling.test.mjs` is now a full test, and it passes. That is the
only change to his file.

## Tests added (mocks only; no browser)

**`apps/web/tests/responsible.test.mjs`**, 9 tests:
- **The footer:** `demo.html` carries Max's `short` text exactly. The footer is never hidden, sits in the
  stage after the question box, has a grid row in both layouts, and contains no link.
- **Loading:** `loadResponsibleUse` returns `short` and `full` unchanged from a relative, same-origin URL. It
  returns null on a 404, a bad shape, an empty string or a network error.
- **Once per session:** `firstTimeThisSession` returns true once, then false. That holds with storage,
  without storage, and when storage throws.
- **The board header:** it shows the full text before the cards. It shows nothing without text, and nothing
  on the error view.
- **The page wiring** (source checks): `askMarket`, `askScenario` and `runScenario` show the notice after
  `reset()` and before Heater's first line; `ask` and `askIdea` don't. The page reads the JSON at start and
  updates the footer from it, and the board waits for the file before drawing its header.
- **One source:** `demo.js`, `responsible.js` and `board.js` don't restate the text.

## Checks (commit 7a49dd5)

Complete raw output: `reports/experience/logs/2026-11-08-0640-safer-gambling-page-checks.log` (LF).

| Check | Command | Result |
|---|---|---|
| env | `uv sync --frozen --all-groups` | PASS |
| scaffold | `uv run --frozen --all-groups python tools/check_scaffold.py` | PASS |
| lint | `uv run --frozen --all-groups ruff check .` | PASS |
| pytest | `uv run --frozen --all-groups pytest -v` (git on PATH) | PASS: 839 passed, 31 skipped, 16 xfailed |
| bundles | `make_reference_bundle.py --check`; `-m heatcheck.contracts.bundle tests/fixtures/quotes/e001`; `make_e001_bundle.py --check` | PASS |
| web unittests | `cd apps\web && uv run --frozen --all-groups python -m unittest discover -s tests -v` | PASS (107 tests) |
| web node tests | `cd apps\web && node --test tests/responsible.test.mjs tests/safer_gambling.test.mjs tests/board-lazy.test.mjs tests/heater-order.test.mjs tests/voice.test.mjs tests/scenario.test.mjs tests/speech.test.mjs tests/whatif.test.mjs tests/ideas.test.mjs tests/board.test.mjs tests/heater.test.mjs tests/referee.test.mjs` | PASS (116 tests, 0 todo) |

Also run: `node --check` on an `.mjs` copy of `demo.js` (module parse): PASS.

## Not executed

- **Browser end-to-end:** NOT_RUN by Experience, as instructed. Max runs it with `demo.cmd`. Please check
  three things there:
  - the footer on wide and phone widths;
  - the header notice on "Tonight's games";
  - the panel on the first "Ask Heater about this game", and that it doesn't come back on the second.
- **The helpline details:** Experience did not re-verify them. The text is Max's, as checked in his report.
- **Polymarket's terms (Max's §4, the UK is listed as restricted) and the event rules (G18):** still open
  decisions for the user and the adviser. This change doesn't settle them.
