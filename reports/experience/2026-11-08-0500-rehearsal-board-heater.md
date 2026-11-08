# Experience: rehearsal fixes: the board opens at once; Heater never pre-empts the Ref

- **Branch:** `experience/market-board`, fast-forwarded to integrate `424b47c` first.
- **Code commit:** **897b5d2**. All checks below ran on 897b5d2 with a clean worktree. This report, its
  logs and the timing script are in the commit after it.
- **Max can merge it as a fast-forward** of `424b47c`.
- **Not touched:** `heatcheck/` (Max's server code is unchanged). No gate is closed or marked.

## 1. "Loading tonight's games…" for ~15 s

### What blocked

The page drew nothing until **every** `POST /api/investigate` had answered.
- There is one call per game: 14 tonight.
- They are sent one after another, and Max's server takes them one at a time anyway (`lock` in
  `heatcheck/api/dialogue_server.py`).
- Each call re-reads and re-validates all **88** quote bundles under `data/experience/quotes`
  (`select_bundle` → `discover_bundles` / `load_bundle`), plus the mapping verifications.
- With the model on, each call also makes one Heater model call (`heater_llm`).
- `/api/live-forecast` itself is fast: 1 to 9 ms.

Measured on Max's code with **no model call**, against a throwaway ledger
(`reports/experience/2026-11-08-0500-rehearsal/time_investigate.py`; raw output in
`logs/2026-11-08-0500-investigate-timing.log`):

| Run | 14 investigate calls in a row | Per call |
|---|---|---|
| first (cold file cache) | **12.51 s** | 5.1 s first, then about 0.56 s |
| second (logged) | **9.42 s** | 0.53 to 1.11 s |

With the model on, each call also waits for its model call, which is consistent with Max's ~15 s.

"On page load" does not match the code:
- `tools/demo.py` opens `/demo.html` with no parameters.
- The board section is `hidden` and was fetched only on "Tonight's games", on `?board=1`, or when
  a typed message routes to the board.
- So the 15 s was most likely the first open of the board.
- **Please tell me if it happened without any of those three.**

### Fix (page only)

- **Home view first.**
  - `main()` draws the talk view and wires the board and idea buttons before any network wait.
  - The evidence ledger now loads in the background. A question waits for it (`ledgerReady()`).
  - If the ledger fails to load, the Ref says "Can't rule: the evidence ledger did not load (…)",
    instead of the page failing to start.
- **Lazy board.** Nothing is fetched for the board until it is opened.
  - **Step 1** waits at most **5 s** for `/api/live-forecast` and `/api/market-mappings` together
    (`loadForecast`, `BOARD_TIMEOUT_MS = 5000`). Then every card is drawn at once from the forecast
    file, as "Checking the market…": no verdict, no price, no Ask button, `aria-busy="true"`. A SAMPLE
    forecast is labelled SAMPLE from the first draw.
  - **Step 2** runs the comparisons one at a time in card order (`investigateGames`, not awaited).
    Each card is redrawn **in place** when its answer arrives, and an open "What if…?" list is kept.
- **Clear errors.**
  - If the forecast doesn't answer within 5 s, the board says "No live forecast: Max's server did not
    answer within 5 seconds." with a **Try again** button.
  - If Max's server is down (the UI server's 502), it says "Max's server is not answering."
  - A failed load is not kept, so opening the board again retries.
  - A card whose comparison never answers says "The comparison could not be run (no answer within
    35 seconds)". The other cards carry on.
  - The per-card limit stays 35 s, because Max's investigate can make a model call (his doc asks for
    at least 30 s).
- **No double work.** Opening the board twice while it loads never investigates twice; each
  investigate call writes to Max's ledger.
- **Kept as before:** `loadBoard()` (both steps, waiting for all) is unchanged for its existing
  callers and tests.

### Suggested for Max (server; not done, it is your code)

- `select_bundle` could cache the parsed bundles, keyed by path and mtime, because the bundles don't
  change. That would remove about 0.5 s per card: about 7 s of the 9 to 12 s.
- The page no longer waits on this, so it is not needed for the demo.

## 2. Heater's first line never pre-empts the Ref

### Finding: it did, in the main question flow

- **Dialogue flow (`ask`).** The page said Max's `heater_text` as Heater's **opening** line, before
  "Checking the tape".
  - Max writes that text **after** the ruling: `_heater(question, claim_id, facts["decision"], facts)`
    in `heatcheck/agents/dialogue.py`.
  - Its fallbacks state the verdict, for example "Heater here! The Ref says it SURVIVED the
    checks…" and "…the Ref threw out the data!".
  - The model's prompt says "never… pre-empt the Ref's verdict", but the model is given the verdict.
  - The page then also added the personality's reaction after the stamp. So both a reaction and a
    verdict-aware opener were said, the opener first.
- **Market card (`askMarket`).** The opener was Max's whole `heater_text`. On a home-bias card it
  ends "And the Ref's calibration note says…" (`HOME_BIAS_HEATER`). The model writing it is given
  `refs_verdict`.
- **Already fine:**
  - Idea board (`heaterIdeaLine`) and preset scenarios (`heaterScenarioLine`, direction only):
    page-written and verdict-blind.
  - The typed what-if read-back runs before any ruling exists.

### Fix (page only)

- **Rule:** before the stamp, Heater may not mention the Ref or say or hint at any verdict. Text
  written with the verdict in hand is said only after the stamp.
  - `preemptsRef(text)` is the check.
  - `splitTake(text)` splits a line by sentence: the sentences that don't pre-empt come first, the
    rest after the stamp. Nothing is dropped or reworded.
- **Dialogue.** The opener is the personality's line for the claim (`takeFor`), which is
  verdict-blind. Max's `heater_text` becomes Heater's **last word**, after the stamp, in place of the
  personality reaction. With no API text, the personality reaction is used, as before.
- **Market.** The opener is the sentences of Max's line that don't pre-empt the Ref, or
  "Let's put this card under the lights." if none are left. The rest (for example the home-bias
  sentence) is said after the stamp.
- **Shown separately:** the take and the reaction are separate elements. The reaction is hidden at
  the start of every turn and shown only after the stamp.

## Tests (mocks only; no browser)

`apps/web/tests/board-lazy.test.mjs` (6 tests, mock of Max's API from `fixtures/max_api/captures.json`):
- opening asks only for `/api/live-forecast` and `/api/market-mappings`, then draws 6 pending cards with
  no verdict and no Ask button;
- comparisons run one at a time (at most one in flight), in card order, and each fills its own card
  in place; card elements and the What-if slot are the same objects afterwards;
- `loadBoard()` still makes the same calls as before;
- with `mock.timers`, nothing at 4.999 s, then "did not answer within 5 seconds" at 5 s, and Try
  again calls back;
- the 502 wording, and one card timing out while the others still answer;
- `demo.js` wiring:
  - home view before the first `await`;
  - no board fetch in `main`;
  - the comparisons are not awaited;
  - opening twice never loads twice.

`apps/web/tests/heater-order.test.mjs` (4 tests):
- Max's `HEATER_FALLBACK` (read from `dialogue.py`) and `HOME_BIAS_HEATER` (read from
  `market_investigation.py`) do pre-empt, so the fix is needed;
- every possible opener is verdict-blind: every personality claim line, every idea line in the fixture,
  scenario up/down/flat/SAMPLE, the market opener, and `SAMPLE_HEATER`;
- `splitTake` drops no words and never leaves a pre-empting sentence first;
- in `ask`, `askIdea`, `askScenario` and `askMarket`, the source order is Heater's opener < the Ref's
  line < the stamp < any later Heater line.

## Checks (commit 897b5d2)

Complete raw output: `reports/experience/logs/2026-11-08-0500-rehearsal-board-heater-checks.log` (LF),
run started 2026-11-08T04:11:03Z.

| Check | Command | Result |
|---|---|---|
| env | `uv sync --frozen --all-groups` | PASS |
| scaffold | `uv run --frozen --all-groups python tools/check_scaffold.py` | PASS |
| lint | `uv run --frozen --all-groups ruff check .` | PASS |
| pytest | `uv run --frozen --all-groups pytest -v` (git on PATH) | PASS: 650 passed, 31 skipped, 16 xfailed |
| bundles | `make_reference_bundle.py --check`; `-m heatcheck.contracts.bundle tests/fixtures/quotes/e001`; `make_e001_bundle.py --check` | PASS |
| web unittests | `cd apps\web && uv run --frozen --all-groups python -m unittest discover -s tests -v` | PASS (107 tests) |
| web node tests | `cd apps\web && node --test tests/board-lazy.test.mjs tests/heater-order.test.mjs tests/scenario.test.mjs tests/speech.test.mjs tests/whatif.test.mjs tests/ideas.test.mjs tests/board.test.mjs tests/heater.test.mjs tests/referee.test.mjs` | PASS (89 tests) |

Also run: `node --check` on an `.mjs` copy of `demo.js` (module parse): PASS.

## Not executed

- **Browser end-to-end:** NOT_RUN by Experience, as instructed. Max runs it with `demo.cmd`.
- **The ~15 s with the model on:** NOT_RUN. No key is used by Experience. Only the no-model timing
  was measured.
- **The real demo bundle:** not built here (`data/bundles/r001-nba-0022300061` is absent), so the
  timing called Max's `run_investigation` directly, not through his HTTP server.
