# Max report: Referee view format `heatcheck-referee-view/1` and Experience's `fromRecord()`

> **Withdrawn, 18:00 UTC (user instruction).** The task was dropped: Experience's
> `experience/referee-ui-integrate@496901c` reads the ledger as-is, and it is merged
> unchanged in `89d3868`. Commit `954c0d5` was reverted in `60b5b10`, which removed the doc,
> projection, fixture, tool, tests and the `referee.js`/`app.js` edits. This report is kept
> as a record of what was built and then removed.

Written 2026-11-07 17:37 UTC on branch `max/integrate-r001-e001`. The code commit is
`954c0d5`. Raw logs are in `logs/2026-11-07-referee-view/`. The user agreed the read-only view
approach. Experience was rate-limited until 20:00 UTC, so Max changed `fromRecord()`.
**Experience reviews it after 20:00.**

## What changed

| File | Change |
|---|---|
| `docs/REFEREE_VIEW_FORMAT.md` | New. The shape, the reader rules, and a field mapping from `provisional-experience/0`. |
| `heatcheck/ledger/referee_view.py` | New. A pure projection of an already verified ledger entry. It copies values and never recomputes them. **Ledger records and hashes are not touched.** |
| `tools/build_referee_view_fixture.py` | New. Writes the projection of one entry to a file. |
| `apps/web/fixtures/referee/referee_view.sample.json` | New sample, **projected from the real live-turn entry** `3ff5ed9f…b661` (HH-K3, `nba:0022300061`, INSUFFICIENT_EVIDENCE). The ledger was read from a copy. |
| `apps/web/web/referee.js` | `fromRecord()` reads `heatcheck-referee-view/1` first (new `fromView()`/`viewAttack()`); the provisional reader is unchanged; new exports `VIEW_FORMAT`, `VIEW_FORMAT_STATUS`, `ATTACK_STATUSES`; the header note is updated. |
| `apps/web/web/app.js` | **One line, outside `fromRecord()`:** `OUTCOME_CELL` gains `EXECUTED` ("ran") and `UNSUPPORTED` ("– could not run"). Without it, every real attack would render as "? unrecognised outcome". Flagged for Experience. |
| `apps/web/tests/referee.test.mjs` | 3 new tests. The 8 existing tests are unchanged. |
| `heatcheck/agents/dialogue.py` | `/api/dialogue` also returns `referee_view`, which is null for NONE. |
| `tests/integration/test_referee_view.py` | 3 tests: the committed fixture equals the projection of the committed entry; the projection does not modify the entry; the committed ledger log is unchanged. |

## Key decisions in the format

- **Attack `status` is shown as supplied** (EXECUTED / FAILED / UNSUPPORTED). It is never
  mapped to PASSED: only the Referee's decision over all attacks says whether the claim
  survived. The JS test asserts that no PASSED appears.
- **`claim.revision` is null** for registered claims. The UI shows it as "not applicable
  (registered claim, version 1)", not as a gap.
- **`derived_from.evidence_id` and `entry_hash`** trace the view back to the ledger. A view
  without them is flagged.
- **The verdict enum** is identical to the provisional one.

## Checks

| Check | Command | Result |
|---|---|---|
| Referee view model (node) | `cd apps/web && node --test tests/referee.test.mjs` | **PASS**: 11 of 11 (8 existing + 3 new) |
| Experience app unit tests | `cd apps/web && uv run --frozen python -m unittest discover -s tests` | **PASS**: 75 OK |
| Projection tests | `uv run --frozen pytest tests/integration/test_referee_view.py` | **PASS**: 3 |
| Dialogue tests, with `referee_view` added | `pytest tests/integration/test_dialogue.py` | **PASS**: 24 (run together with the above: 27 passed) |
| ruff | `uv run --frozen ruff check .` | **PASS** |
| Browser render of the sample file | – | **NOT_RUN**: no browser run on this host |

## For Experience's review

1. Do you accept `fromView()` and the two `OUTCOME_CELL` entries in `app.js`?
2. The "ran" cell class is new and has no CSS rule, so it renders unstyled.
3. Wiring the UI to `POST http://127.0.0.1:8770/api/dialogue` is yours. CORS allows
   `127.0.0.1:8765` and `localhost:8765`. The response carries `referee_view`, ready for
   `fromRecord()`.
