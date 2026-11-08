# Experience report: Referee ledger view on integrate, and reviewer fixes RV-E1..E8

Written 2026-11-07 ~17:20 UTC. Role: Experience.

## Branch and commits

**Branch:** `experience/referee-ui-integrate`. It is pushed and has no upstream tracking; each push names the remote branch explicitly.

**Base:** `origin/max/integrate-r001-e001` at `cb7320c`.

| Commit | Content |
|---|---|
| `a567f71` | Merge of `experience/live-quote@c0f1ff4` (recorded DEN@IND capture) onto `cb7320c`. Already in Max's PR #3 history. |
| `1f6989a`, `101f190`, `80dd8ae`, `d8d862f`, `539f323` | Cherry-picks of `experience/app-referee-ui` (`cbcf449`..`ffdb1e7`): app import, path fixes, fixture fixes, provisional Referee view, report. |
| `1b6eb7b` | The UI shows Max's evidence-ledger entries, read-only, with hashes verified on the server. |
| `602ae1d` | Fixes for reviewer findings RV-E1..E8 in `heatcheck/markets/adapters`. |
| this report commit | Hash given in the chat reply; it is the branch head after this push. |

Max's branch has one newer commit, `5573806`, which only touches reports: `reports/max/2026-11-07-1700-meta-api-test.md` and its logs. I did **not** merge it into this branch.
- It contains no code.
- I was told not to merge anything.

Max can merge this branch onto `5573806` without conflicts, because the two sides touch different paths.

## PRs #3 and #4 (merged into main)

Both PRs were opened and merged in the GitHub web UI by the `nichols-leo` account. That is the user's account, not one of the Claude sessions.

| PR | Branch | Merged | Merge commit | Checks at merge |
|---|---|---|---|---|
| #3 | `experience/referee-ui-integrate`, at `539f323` | 16:54:21Z | `ac973ca` | 0 of 2 passed |
| #4 | `experience/app-referee-ui`, at `ffdb1e7` | 16:54:48Z | `617c190` | 1 of 2 passed |

- **Committer:** both merge commits show `GitHub <noreply@github.com>` as committer, which means they were made through the web UI.
- **This session:** my transcript has no tool call that opens or merges a PR. My only browser visits to `/pull/3` and `/pull/4` came after the merges, to read who did them.
- **What reached main:** `1b6eb7b` (ledger view) and `602ae1d` (RV-E fixes) were pushed after the merges and are **not** on main.
- **Rule from now on:** no PRs into main and no merges. I push `experience/*` only; Max integrates.

## 1. Referee evidence-ledger view (`1b6eb7b`)

The UI renders Max's evidence-ledger entries (`heatcheck/ledger/evidence.py`) as claim, attacks run, verdict and evidence. The stand-in engine output is no longer the only source.

- **Server: `apps/web/server/evidence.py`.**
  - It reads the JSONL named by `--ledger` or by `HEATCHECK_LEDGER`, and serves it at `GET /api/evidence`.
  - It verifies each entry with Max's own `EvidenceLedger._entries()`, so a tampered entry is refused (409 `TAMPERED`).
  - It never writes: it builds the reader with `EvidenceLedger.__new__` so the constructor's mkdir/touch does not run. A test checks that the bytes, the mtime and a missing path are all left unchanged.
  - Hashes are checked only on the server. Python canonical floats (`31.0`) do not survive JavaScript.
- **Browser: `apps/web/web/referee.js`, `fromLedgerEntry`.**
  - Attack statuses (`EXECUTED` / `FAILED` / `UNSUPPORTED`) are shown exactly as recorded.
  - A mandatory or Challenger-selected attack with no result is listed as `NOT_RUN`. Nothing is zero-filled.
  - An unknown status or protocol is flagged, never reinterpreted.
  - An entry that the server did not verify is labelled as not verified.
- **Committed ledger:** `reports/max/logs/2026-11-07-loop/evidence_real_game.jsonl` verifies and renders as follows.

  | Claim | Verdict |
  |---|---|
  | HH-K3 | INSUFFICIENT_EVIDENCE |
  | HH-K2 | NOT_SUPPORTED |
  | GP-REST | BLOCKED (all three mandatory attacks `NOT_RUN`) |

## 2. Reviewer findings RV-E1..E8 (`602ae1d`)

These are all in Experience-owned `heatcheck/markets/adapters/`. Nothing in `heatcheck/contracts/` changed.

| Finding | Fix |
|---|---|
| R1 allowlist prefix bypass | `check_request` matches the **whole path** against exact patterns; prefix matching is gone. A path segment is `[A-Za-z0-9][A-Za-z0-9_-]*`, so `.`/`..`, `%2F` and `/bookkeeping`-style prefixes are refused. Allowed paths: Gamma `/markets/slug/<seg>`, `/markets` and `/events`; CLOB `/book`; Kalshi `/trade-api/v2/markets[/<seg>[/orderbook]]` and `/trade-api/v2/events[/<seg>]`. Every URL in both committed bundles still passes (new test). |
| U1/U4 off-tick price | A level price must be a multiple of the market's own `tick_size`, for both Polymarket and Kalshi. If the tick is unknown, levels are refused; an empty book is still `EMPTY`. |
| U2 zero size | `0`, `0.00` and similar sizes are refused. |
| T1/T2 implausible provider time | Refused when provider time is more than **5 s after** receipt, or more than **1 day before** it (e.g. epoch seconds read as ms). |
| S1 stale book | Provider time more than **60 s before** receipt gives QUOTE `status: STALE` with a reason. That status is already in `heatcheck-records/1`. Precedence: EMPTY, then crossed ERROR, then PAUSED, then STALE, then OK. |
| S2 day-long fetch | `Capture.checked()` refuses a fetch window over **60 s**. |
| O1 NO as YES-team win | Refused: the Kalshi label `NO` names no team. |
| O2 wrong team | `propose_mapping` requires the outcome label to name **exactly** the team in `team_id`. Names come from a 30-team table (tricode, NBA Stats id, city and nickname). Ids accepted are `nba-team:<NBA Stats id>` and `syn-team:<tricode>`. "Los Angeles" alone names no team; a label that names two teams is refused. |
| O3 missing asset_id | A Polymarket book must carry the requested `asset_id`. |
| OT1 overtime reading | Negations ("not including overtime", "overtime does not count", …) are read first. Positive phrases cannot match inside a negation. "At the end of regulation" counts as regulation-only only when its sentence does not mention overtime or a tie. Conflicting phrases read `UNKNOWN`. |

These thresholds (60 s, 5 s, 1 day, 60 s) are new adapter-level bounds. No existing threshold was changed. They do not replace Max's eligibility `max_age` (600 s historical), which still applies later against the cutoff.

**Answer to the reviewer's question to Experience:**
- `check_request` now matches whole path segments, with no normalisation step: dots and `%` can never form a segment, so there is nothing to normalise.
- `propose_mapping` now requires the team's own name, city or tricode in the outcome label.

## Checks

All checks ran on Windows 11 with Python and uv, in commit `602ae1d`. Complete raw output (LF) is in two logs:
- `reports/experience/logs/2026-11-07-1709-referee-ui-integrate-checks.log`, run with a clean worktree;
- `…-checks-part2.log`. Its "worktree clean: False" refers only to the untracked report and log files. The code is `602ae1d`.

**Log 1 bug:** the last two steps (reviewer probes and baseline) started with cmd `REM`, which commented out the whole line. Nothing ran, so their `exit: 0` means nothing. Both steps were re-run for real in part2, and the results below come from part2.

**Part2 no-op label:** the baseline step starts with `git_head_5573806_baseline_same_venv 2>nul &`. That is a label meant to fail silently. It does nothing.

| # | Command | Result |
|---|---|---|
| 1 | `uv sync --frozen --all-groups` | PASS (exit 0) |
| 2 | `uv run python tools/check_scaffold.py` | PASS ("application/research gates NOT_RUN") |
| 3 | `uv run ruff check .` | PASS |
| 4 | `uv run pytest -q tests -p no:cacheprovider` | **FAIL: 19 failed, 239 passed, 9 skipped.** All 19 are in `tests/review/`, and they are exactly the 19 failures at the baseline (row 13). |
| 5 | `uv run python tools/make_reference_bundle.py --check` | PASS, `faa3d335…7465` |
| 6 | `uv run python tests/experience/make_e001_bundle.py --check` | PASS, `b98438c4…e843` (unchanged) |
| 7 | `uv run python -m heatcheck.markets.adapters.capture build tests/fixtures/quotes/e001-recorded-0022600189 --check` | PASS, reproducible |
| 8 | `uv run python -m heatcheck.contracts.bundle tests/fixtures/quotes/e001` | PASS |
| 9 | `uv run python -m heatcheck.contracts.bundle tests/fixtures/quotes/e001-recorded-0022600189` | PASS, `9a412c7a…4c06` (unchanged) |
| 10 | `cd apps\web && uv run python -m unittest discover -s tests` | PASS, 80 tests OK |
| 11 | `cd apps\web && node --test tests/referee.test.mjs` | PASS, 12/12. The log shows `✔` as mojibake because of the console code page. |
| 12 | Reviewer probes: `tests/review/test_rv_e001_adapter.py` from `origin/review/independent-tests`, copied in for this step and then deleted (never committed) | PASS, 43 passed. **Before** the fixes: 20 failed, 23 passed. |
| 13 | Baseline: detached worktree at `origin/max/integrate-r001-e001` `5573806`, same venv; `heatcheck` imported from the worktree (shown in log) | 19 failed, 177 passed, 9 skipped |

**The 19 failures in rows 4 and 13**, compared with a sorted diff of the `FAILED` lines (identical):
- the validator probes in `test_rv_validator_probes.py` that Max deferred: L5, L6, G3, O3, O5, O7, U2×3, U3, U7, U8, S1, S2, T2, T3, T4;
- `test_rv_candidates.py::test_experience_bundle`;
- `test_rv_checks_selftest.py::test_experience_check_fires[outside fetch]`.

All of them test `heatcheck/contracts`, which Max owns; none is in Experience code.

**The 62 extra passes on this branch**, from per-file `--collect-only` counts against the baseline:

| Tests | File | Source |
|---|---|---|
| +51 | `tests/experience/test_e001_rv_fixes.py` | new |
| +9 | `tests/experience/test_e001_recorded.py` | the `experience/live-quote` merge `a567f71`, which is not on `origin/max/integrate-r001-e001` |
| +2 | `tests/experience/test_e001_readonly.py` | allowlist-pattern and recorded-URL tests |

## Not executed

- **Playwright end-to-end UI run:** NOT_RUN. The `browser` group is installed, but no e2e script exists for the ledger view yet. The view was exercised by the node tests and the API test.
- **Live venue path after these fixes:** NOT_RUN. No new network GETs were made. The recorded real capture was re-parsed offline and still rebuilds byte-identically.
- **Gates G01–G18:** not self-marked. Max and the reviewer decide them.

## Open points for Max

1. **Read-only constructor.** `EvidenceLedger` has none, so the UI uses `__new__` plus `path`. A `EvidenceLedger.open_readonly(path)` or a `read_only=True` flag would remove that coupling.
2. **Cancel/postpone rules differ.** Kalshi and Polymarket word them differently. The adapter copies the rules sentences verbatim; mapping verification is yours.
3. **Adapter freshness bounds.** Please confirm the 60 s STALE threshold, or name your own. It only marks status and never changes prices.
4. **Earlier points still open:**
   - the `CLOCK_SKEW` name;
   - `numpy` is needed for the app's research group (`uv sync --all-groups`).
