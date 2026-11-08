# Experience: rehearsal fixes for Frost (8 Nov 2026, ~08:40 UTC)

Branch `experience/frost`. Code commit `72e994f`; merge of Max's latest `4005c9f`
(max/integrate-r001-e001@cb0573e, whose tree equals main bf840db). The checks below ran on `4005c9f`.
This report and its logs are in the commit after it (hash given to Max separately).

Source: Max's click-through, `reports/max/2026-11-08-frost-demo/` and `reports/max/STATUS.md`
("Open items to report"). Only Experience files changed: `apps/web/web/demo.css`,
`apps/web/web/demo.js`, `apps/web/web/frost/fixtures/sample-dialogue.json`,
`apps/web/tests/frost.test.mjs`, new `apps/web/tests/layout/frost_layout.mjs`.
Nothing in `heatcheck/`, `voice.js` or the tamper files.

## The four fixes

1. **Frost covering the conversation at 1440x900.** The cause was `.frost-side { justify-self: end }`.
   That made the column shrink-to-fit, so Frost's figure (about 450 px wide at full height) overflowed
   leftwards over the 340 px column and onto the bubbles.
   - Now both side columns stretch and clip (`overflow: hidden`).
   - The middle column is `minmax(560px, 760px)`.
   - From 901 to 1680 px wide, Heater and Frost are drawn at 60% height.
   - Measured at 1440x900:
     - the conversation is 760 px wide (333 to 1093);
     - Frost's column starts at 1117 and his figure stays inside it (1117 to 1382);
     - Heater's figure ends at 309, the right edge of his column.
2. **Ref card below the fold after three rounds.** The thread scrolls each new line into view:
   Frost's questions, the chips, the Ref card when it lands, the stamp, and the reactions.
   - Smooth scrolling is turned off under `prefers-reduced-motion`.
   - Once the Ref starts checking, earlier chips fold to one line ending in "...". The full text is
     still on the page, and hovering or keyboard focus opens it again.
   - The browser run (below) found the stamp hanging about 50 px below the card, behind the fixed
     footer, at 1440x900 and in the 1920x1080 dialogue. Fix: the card keeps 56 px of room under it, and
     the scroll margin is the footer height plus 64 px.
   - Measured at the end of the 1440x900 dialogue: card 487 to 806, stamp 706 to 854, footer top 870.
3. **Market cards without Frost.** `runExchange` is now generic and takes the title, Ref line, stamp,
   end states and evidence for that run. `askMarket` runs the same Frost sequence when
   `/api/investigate` returns `frost`. The sequence is: Heater's take, Frost's questions with chips,
   the Ref with the market line and stamp, then both reactions. The market version uses Heater's
   market reaction and Frost's `frost_reaction`. If the answer has no `frost`, the card behaves as before.
4. **"47.27%" in the sample fixture.** `ref_text`, `claim_title` and the three chips in
   `web/frost/fixtures/sample-dialogue.json` are now computed from Max's code for CONF-HH, as follows:
   - `ref_text` is `ref_template(ref_facts(entry))`.
   - The chips are `frost.to_payload(frost.select(facts), None)`.
   - The `ref_guard` check and the chip number checks are both empty.
   - The fixture also carries `evidence_record_id`.
   - "47.27" does not appear in the record or the fixture, and a test checks this.
   - Heater's lines and `frost_reaction` are still the user's sample lines. The page still labels
     the run SAMPLE RESPONSE.

## Commands and results

| Check | Command | Result |
|---|---|---|
All checks below ran on commit `4005c9f`.

| Check | Command | Result |
|---|---|---|
| Sync | `uv sync --frozen --all-groups` | PASS |
| Scaffold | `uv run --frozen --all-groups python tools/check_scaffold.py` | PASS |
| Lint | `uv run --frozen --all-groups ruff check .` | PASS |
| pytest | `uv run --frozen --all-groups pytest -v` | PASS: 862 passed, 31 skipped, 16 xfailed |
| Reference bundle | `make_reference_bundle.py --check` | PASS |
| e001 bundle check (contracts) | `heatcheck.contracts.bundle tests/fixtures/quotes/e001` | PASS |
| e001 bundle rebuild | `make_e001_bundle.py --check` | PASS |
| apps/web unittest | `python -m unittest discover -s apps/web/tests -p "test_*.py"` | PASS: 107 OK |
| Node, 14 files (incl. frost and tamper) | `cd apps\web && node --test tests/...` | PASS: 150/150 |
| Browser layout, 4 cases | `node apps/web/tests/layout/frost_layout.mjs reports/experience/2026-11-08-0837-frost-layout` | PASS 4/4 |

Logs (LF):
- `reports/experience/logs/2026-11-08-0843-rehearsal-fixes-checks.log` is the run that counts.
- `reports/experience/logs/2026-11-08-0837-frost-layout.log` is the layout run.
- `reports/experience/logs/2026-11-08-0837-rehearsal-fixes-checks.log` is an earlier run, kept for
  the record. It had 1 failure: `test_ledger_chain.py::test_committed_ledger_migrated_without_changing_evidence`
  hit `FileNotFoundError` because git was not on PATH in my shell; that test calls `git show`.
  - With git on PATH, the same file passes 12/12, and the 0843 run is all PASS.
  - It was an environment fault, not a code fault. No test or threshold was changed.
- Both check logs say "worktree clean: False". The only untracked files were this report and its logs
  and screenshots, all under `reports/experience/`.

Screenshots and measurements are in `reports/experience/2026-11-08-0837-frost-layout/`
(`*.png`, `results.json`).

### How the layout test works (and what it is not)

- **Browser:** headless Edge (installed) driven over the DevTools protocol from Node 24. Nothing was
  downloaded; Playwright is not installed.
- **Mock server:** a local server serves `apps/web/web` and answers the API with mocks:

  | Route | Mock answer |
  |---|---|
  | `/api/route` | DIALOGUE |
  | `/api/live-forecast`, `/api/investigate` | Max's captured answers from `tests/fixtures/max_api/captures.json` |
  | `/api/market-mappings` | the recorded mapping index |

- **Market case is partly invented:** the captures predate Frost, so the test adds a mock `frost`
  list, labelled "MOCK: ..." on screen, built from that card's own captured checks. The captured
  forecast is a SAMPLE, so the market stamp says SAMPLE.
- **Viewports and runs:** 1440x900 and 1920x1080. Each viewport runs `?frost=sample` with "Is the hot
  hand real?" and the first market card, with voice off.
- **What it checks:**
  - the middle column is at least 560 px;
  - both figures stay inside their columns;
  - no bubble or chip reaches Frost's column or is covered at its right edge;
  - the Ref card and stamp are fully on screen above the footer when the stamp lands and at the end;
  - there are 3 Frost questions and 3 chips.

## Not run

- **The real end-to-end:** no model, live API or real `/api/investigate` with Frost. That is Max's
  `demo.cmd` run.
- **Voice on:** all browser runs used `?voice=0`, so speech timing with the new scrolling is not tested.
- **Other screen sizes:** only 1440x900 and 1920x1080. The 860–900 px layout and phones were not
  re-checked in a browser; the CSS for them is unchanged.
- **Main:** nothing was merged into main and no PR was opened.
