# Experience: "Your own scenario" box on the game card; idea test made independent of proposals

- Branch: `experience/market-board`, fast-forwarded to `origin/max/integrate-r001-e001` at c15abf7.
- Code commits: **056a0ed** (the box) and **e0a47b8** (test fix). All checks below ran on **e0a47b8**
  with a clean worktree. This report and its log are in the commit after it.
- Gates: none closed or self-marked.

## 1. "Your own scenario" (056a0ed), as Max asked on 2026-11-08

Both what-if views stay:
- the card's "What if…?" lists the preset scenarios (`GET /api/scenario`);
- a **"Your own scenario"** box now sits under that list, on the same card.

The box:
- Submitting it calls `onOwnScenario(game, text)`. `demo.js` hands that to Max's `runScenario(text,
  game_id)`, pinned to the card's game.
- Max's flow then runs unchanged: `POST /api/scenario` with `{message, game_id}`, Heater reads the scenario
  back, the user confirms, `POST /api/scenario/estimate` runs, and Max's server supplies the Ref text and
  the HYPOTHETICAL stamp. One backend serves both views.
- The box fetches nothing itself. Empty text is ignored, input is capped at 200 characters, and the form
  never reloads the page. It has a visible label tied to the input.

Tests (`apps/web/tests/scenario.test.mjs`, now 13):
- the box sits after the presets, with its label and input;
- submit sends the trimmed text with this card's game id;
- the box makes no fetch;
- there is no box without `onOwnScenario`;
- `demo.js` wires it to `runScenario(text, g.row.game_id)`, and Max's flow posts `game_id`.

`demo.js` also passes a module-mode parse check (`node --check` on an `.mjs` copy). That check catches a
duplicate top-level declaration like the one Max fixed in 11772da.

## 2. Existing failure on integrate, fixed in the test (e0a47b8)

- **The failure:** `apps/web/tests/test_ideas.py::test_committed_api_capture_equals_the_reader_output`
  fails on c15abf7 alone. I checked c15abf7 without Experience's commits: 1 failure in 11 tests.
- **Cause:** since c15abf7, `ideas.read_all()` also adds Heater's proposals from the repo's
  `data/max/idea_requests`, whatever directory it is given. The committed capture has no `proposals`.
  Max's c15abf7 run listed pytest and node, not the `apps/web` unittests.
- **Fix:** test-only; Max's reader is unchanged.
  - `TestReader` points `HEATCHECK_PROPOSALS` at an empty directory.
  - The capture gains `"proposals": []`. The rest is byte-identical, rewritten with the same
    formatting after checking that the formatting reproduces.
  - New `TestProposals` (2 tests) runs against Max's committed files:
    - the model proposal is listed NOT_RUN with its request sha256;
    - the keyword request without model output is not listed;
    - a request that no longer matches the model's parsed ideas is refused.
- The first full run on 056a0ed showed this failure. Its log was replaced by this one.

## Checks (commit e0a47b8)

Complete raw output: `reports/experience/logs/2026-11-08-0230-own-scenario-box-checks.log` (LF), run started
2026-11-08T02:19:40Z.

| Check | Command | Result |
|---|---|---|
| env | `uv sync --frozen --all-groups` | PASS |
| scaffold | `uv run --frozen --all-groups python tools/check_scaffold.py` | PASS |
| lint | `uv run --frozen --all-groups ruff check .` | PASS |
| pytest | `uv run --frozen --all-groups pytest -v` (git on PATH) | PASS: 640 passed, 31 skipped, 16 xfailed |
| bundles | `make_reference_bundle.py --check`; `-m heatcheck.contracts.bundle tests/fixtures/quotes/e001`; `make_e001_bundle.py --check` | PASS |
| web unittests | `cd apps\web && uv run --frozen --all-groups python -m unittest discover -s tests -v` | PASS (106 tests) |
| web node tests | `cd apps\web && node --test tests/scenario.test.mjs tests/speech.test.mjs tests/whatif.test.mjs tests/ideas.test.mjs tests/board.test.mjs tests/heater.test.mjs tests/referee.test.mjs` | PASS (73 tests) |

## Not executed

- **Browser end-to-end:** NOT_RUN (mock tests only). Max's next demo.cmd run will show the box.
- **Sunday price capture:** not run, as Max asked. Fresh prices are captured on the demo machine before the
  demo.

## For Max

1. Merge `experience/market-board` up to this report's commit.
2. Please add `cd apps\web && uv run --frozen python -m unittest discover -s tests` to your runs: it is
   the suite that caught the `proposals` break.
3. Preset scenarios stamp **ESTIMATE**; typed ones stamp **HYPOTHETICAL** (your server). If you want one
   word on both, say which and I'll change the preset side.
4. Experience stops here until your rehearsal fixes.
