# Experience: missing stamp fixed; scenario view on the game card

- Branch: `experience/market-board`, fast-forwarded to `origin/max/integrate-r001-e001` at 3539eb2.
- Code commits: **35cdb20** (speech time limit) and **c9ef784** (scenario view). All checks below ran on
  **c9ef784** with a clean worktree. This report and its log are in the commit after it.
- Gates: none closed or self-marked.

## 1. Why demo.cmd showed no stamp (35cdb20)

- **Seen in Max's runs:**
  - `reports/max/2026-11-07-demo-e2e`: the Ref line is shown, and no SAMPLE stamp.
  - `chip2.png`: no SURVIVED stamp, and Heater is not in the vindicated pose.
  - `reports/max/2026-11-08-market-live-recorded`: "No stamp was visible" on the idea board.
  - Every sequence stopped right after the Ref spoke.
- **Cause (ours):**
  - `demo.js` sets the stamp and the end pose after `await h.speak(refLine)`.
  - Voice is on unless the URL has `?voice=0`.
  - With voice on, `heater.js speak()` waited only for the utterance's `onend`/`onerror`, with no limit.
  - Max ran headless Chromium (Playwright) with voice on, and it never fired either event.
- **Fix:**
  - `speak()` also finishes after `speechGuardMs` = `fallbackSpeechMs` + 2500 ms (`heater-model.js`).
    Any voice keeps playing.
  - A speech that ends normally finishes as before, and the limit is cleared.
  - The finish step runs once, so a late event cannot clear a later line.
- **Test:** `apps/web/tests/speech.test.mjs` (4 tests) uses a fake `speechSynthesis` that never ends, with
  mocked timers.
  - Without the limit, the test hangs. I checked this by removing the line and running the test, then
    stopped the run and restored the file.
  - With the limit, `speak()` finishes exactly at the limit, never before, and the stamp is set.
- **Workaround before merge:** `demo.html?voice=0`.

## 2. Scenario view on the game card (c9ef784)

- **"What if…?"** on each market card loads `GET /api/scenario?game_id=…`. The URL is relative, and the
  call is made once per card. `scenario` is added to the UI server's pass-through list (`MAX_ENDPOINTS`).
- **Each scenario shows:**
  - the **ESTIMATE** label, plus SAMPLE when the numbers are invented;
  - "Forecast now" beside "In this scenario", and the change in points ("No real change" under half a point);
  - a **range bar** on a 0–100% track: band = range, line = forecast now, dot = scenario, with an
    aria-label;
  - under it, the range with its level, "Based on n …", and the **Caveats** list.
- **"Ask Heater about this scenario":**
  - **Heater** reacts to the direction only (up, down or flat), with no digits. On SAMPLE numbers he says
    a fixed line.
  - **The Ref:** "ESTIMATE, not a finding. If …: X p, against base now (change). Range …, based on n …."
    It adds a noise sentence when the range includes the current forecast, then the caveats. It
    **always ends "Edge unverified: nothing shows this model beats the market."** SAMPLE: no numbers.
  - **Stamp:** ESTIMATE (or SAMPLE). **End pose:** thinking, cooled or unsure; never vindicated.
  - **"Show the evidence"** lists the raw values, the method, each caveat, the source and the receipt.
- **The page computes no probability, range or n.**
  - **A scenario is refused** ("Not shown" with the reason) when:
    - the label is not `ESTIMATE`;
    - a probability is not a 0–1 decimal string;
    - the point is outside its range;
    - n is not a positive integer;
    - there are no caveats.
  - **The whole answer is refused** when its game, team, baseline or `is_sample` differs from the card's
    investigate answer, or its format is unknown.
- **Missing upstream:** Max's server has no `/api/scenario`, and no branch produces scenario estimates.
  - The card says: "No scenarios: Max's server has no scenario endpoint yet."
  - The proposed format `heatcheck-scenario/1` is in `apps/web/HANDOFF.md`.
- **Tests:**
  - `apps/web/tests/scenario.test.mjs` (11 tests) runs against hand-made answers labelled SAMPLE
    (`tests/fixtures/scenario_api.SAMPLE.json`) and Max's captured investigate answer for nba:0022600190.
  - `test_proxy.py` checks that `/api/scenario?…` is forwarded with its query and that Max's 404 comes
    back unchanged. The relative-URL check covers the two new files.

## Checks (commit c9ef784)

Complete raw output: `reports/experience/logs/2026-11-08-0100-scenario-and-stamp-checks.log` (LF).
The run started at 2026-11-08T01:10:39Z. The log holds the full output, then the same step summary
repeated at the end.

| Check | Command | Result |
|---|---|---|
| env | `uv sync --frozen --all-groups` | PASS |
| scaffold | `uv run --frozen --all-groups python tools/check_scaffold.py` | PASS |
| lint | `uv run --frozen --all-groups ruff check .` | PASS |
| pytest | `uv run --frozen --all-groups pytest -v` (git on PATH) | PASS: 595 passed, 31 skipped, 16 xfailed, 0 failed |
| bundles | `make_reference_bundle.py --check`; `-m heatcheck.contracts.bundle tests/fixtures/quotes/e001`; `make_e001_bundle.py --check` | PASS |
| web unittests | `cd apps\web && uv run --frozen --all-groups python -m unittest discover -s tests -v` | PASS (104 tests) |
| web node tests | `cd apps\web && node --test tests/scenario.test.mjs tests/speech.test.mjs tests/ideas.test.mjs tests/board.test.mjs tests/heater.test.mjs tests/referee.test.mjs` | PASS (61 tests) |

The RV-AL5 pytest failure from earlier reports is gone: Research's `research/al5-test-fix` is now in integrate.

## Not executed

- **Browser end-to-end and screenshots:** NOT_RUN (mock tests only, as instructed). The stamp fix needs
  confirming in Max's next demo.cmd run.
- **Scenario view with real estimates:** NOT_RUN. No scenario endpoint or estimate exists yet.
- **Re-capture on Research's real `forecasts.json`:** NOT_RUN by Experience. Max captured quotes
  20261108T001759Z and 20261108T001942Z against it himself.

## For Max

1. Merge `experience/market-board` up to this report's commit. All changes are under `apps/web/`.
2. Re-run demo.cmd and check the stamps (SAMPLE, SURVIVED, idea stamps) now appear.
3. To turn the scenario view on, add `GET /api/scenario` in the format in `apps/web/HANDOFF.md`, or tell me
   your shape and I'll match it. Someone has to produce the estimates (Research?).
