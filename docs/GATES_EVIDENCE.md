# Gate evidence index, G01–G18

Written by Max, 8 November 2026 ~02:40 UTC, at `max/integrate-r001-e001` (candidate commit: the one
that adds this file). Gate definitions: `ACCEPTANCE.json`. **This file marks no gate.** Every gate
stays NOT_RUN until a reviewer other than the author replays the commands below against the exact
candidate bytes and records PASS / FAIL / NOT_RUN with scope on a `review/` branch (CLAUDE.md
rule 7). Self-reported results are quoted as "self-reported"; reviewer results name the report.

## Before you start

Environments:
- Root suite: `uv sync --frozen --group dev --group research`, then commands from the repo root.
- Research handoff ("HO" = `handoff/research-20261107/`): no lock file of its own; run from inside HO
  with the root venv, e.g. `../../.venv/bin/python -m pytest -q` (Linux) or
  `..\..\.venv\Scripts\python.exe -m pytest -q` (Windows).
  `test_custodian.py`, `test_confirmatory.py` and `test_guard_fixes.py` import `fcntl`, so they need
  **Linux/macOS**. Real-data tests skip without a build (`HC_DATA=<build dir>`).
- Experience (`apps/web/`): `python -m unittest discover -s tests` and `node --test tests/*.test.mjs`
  from inside `apps/web`.

Data in this checkout:
- Not committed: the 2023-24 raw archives (`HO/raw/repo/` holds only COMMIT, SHA256SUMS and the
  licence) and any 2024-25 build. Rebuild with `bash scripts/setup_data.sh` (HO; network).
- Git-ignored local copies exist on Max's machine only (`data/raw/research-20261107/`,
  `data/processed/research-20261107/`). **Defect:** that local manifest records
  `upstream_revision` `05a7107d…` (a HeatCheck commit), not the upstream `46488f0f…` in
  `HO/raw/repo/COMMIT`: the nested-checkout defect Research described in its 1633 report. Do not use
  the local build as provenance evidence; rebuild.

Do not:
- rerun `HO/scripts/confirmatory.py final` on the committed evidence: it is not write-once and
  rewrites `final_result.json`. Use a copy of `HO/evidence/` if you replay.
- rerun `HO/scripts/game_prediction.py final` on committed evidence: it appends to the committed
  ledger. Use a copy.
- run `capture_quotes.cmd` / `live_quotes capture` expecting byte-equal output: they make live
  read-only network calls; prices change.

Max's own baseline at this commit (author's runs, Windows, 8 Nov 02:20–02:40 UTC):

| Command | Result |
|---|---|
| `uv run --frozen pytest -q` (root `tests/`, what CI runs) | 642 passed, 29 skipped, 16 xfailed |
| `uv run --frozen ruff check .` | clean |
| HO: `python -m pytest -q --ignore=tests/test_custodian.py --ignore=tests/test_confirmatory.py --ignore=tests/test_guard_fixes.py` | 92 passed, 8 skipped (dataset not built) |
| `apps/web`: `python -m unittest discover -s tests` | 104 OK |
| `apps/web`: `node --test tests/*.test.mjs` | 71 pass |

CI (`.github/workflows/checks.yml`) runs only the root `tests/` (`testpaths = ["tests"]`): the HO
and `apps/web` suites are **not** in CI.

## G01 Data/provenance (Research)
- 2023-24 build: 1,230 games, 674,937 events, 218,693 FGA; reconciliation against nbastats (same
  organisation, so not independent). `HO/EVIDENCE.md` §1; `HO/evidence/season_manifest_2023-24.json`,
  `reconciliation_2023.csv`, `replay_determinism.txt` (6eba349). Rerun (HO, network):
  `bash scripts/setup_data.sh` or `python -I scripts/build_dataset.py raw/repo data/run1 raw/extracted`.
  Self-reported: two builds, all logical table hashes identical; BALLDONTLIE cross-check NOT_RUN.
- Reviewer rebuild: `reports/review/2026-11-07-1642-r001-e001-replay.md` (8226407) row 2a, "PASS …
  8/8 logical table hashes equal"; logged RV-R3 (manifest/script hash mismatch).
- 2024-25 seal: 1,230 games, 1 SCORE_MISMATCH, game 0022400072 quarantined.
  `reports/research/2026-11-07-1757-confirmatory-seal.md` (2d277d4),
  `HO/evidence/confirmatory-2024-25/season_manifest_2024-25.json`; fresh rebuild
  `reports/research/2026-11-07-2015-rebuild-and-seal-binding.md` (e382785), rerun
  `bash logs/rebuild/rebuild_2024-25.sh` (network, clone).
- 2026-27 inputs: balldontlie raw pages with sha256 and fetch times, `data/live/raw/balldontlie/`
  (commit eec051d on `max/nba-schedule`; fetcher `tools/fetch_balldontlie.py` there; needs the key,
  which is not in the repo). Forecast `data/live/forecasts.json` (e03629d). No rerun command given
  for the forecast build.

## G02 Temporal correctness (Research)
- `HO/tests/test_time_integrity.py` (6eba349): future perturbation pre-game/pre-shot, leakage
  fixture, withheld label raises. Rerun: `HC_DATA=<build> python -m pytest -v tests/test_time_integrity.py`
  (HO). Research's own critique (1633): pre-shot test covers 1 of 181 shots; no leaky pre-shot control.
- Reviewer harness on Research's builder: `pytest tests/review/incoming/test_rv_research_preshot.py`
  (root; needs data and `HEATCHECK_REVIEW_RESEARCH_SRC`). Reviewer 1642: "PASS 9/9", 3 full games, FGA only.
- Via Max's bridge: `HEATCHECK_REVIEW_FEATURE_BUILDER=heatcheck.contracts.research_bridge:harness_builder HEATCHECK_REVIEW_RESEARCH_BUNDLE=data/bundles/r001-nba-0022300061 uv run --frozen pytest tests/review/test_rv_preshot_invariance.py tests/review/test_rv_candidates.py -rA`.
  Reviewer 1642: 14 pass, 2 FAIL (RV-R6, RV-R7); RV-R6 later closed by decision D12 (`docs/DECISIONS.md`).
- Live forecast cutoff: `HO/tests/test_live_forecast.py` (e03629d). Self-reported 4/4.

## G03 Statistical oracles (Research)
- `HO/tests/test_kernels.py` (6eba349): Beta-binomial golden fixture, log loss/Brier,
  Miller–Sanjurjo exact n=4, undefined streak, Holm, block-bootstrap insufficiency. Pure; no data.
  Rerun (HO): `python -m pytest -v tests/test_kernels.py`. Self-reported (EVIDENCE §6): Beta(10,4)
  moments vs scipy; Miller–Sanjurjo 17/42 exact.
- `HO/tests/test_confirmatory.py` (e7e8857; Linux): `test_shot_rule_minimums_and_undefined`,
  `test_decision_rules_and_holm`.

## G04 Registered adversarial tests (Research; Max for the loop)
- Research: EVIDENCE §6 self-reports PARTIAL ("clutch, spec curve, influence, time replication
  NOT_RUN"); `reports/research/2026-11-07-1633-jone-claims.md` lists attacks without code.
- Max's loop: reviewer 1716 (`reports/review/2026-11-07-1716-agent-loop-and-xfail.md`, 1e8967a) found
  RV-AL3/AL4 (optional attacks not enforced). Fix merged as research/al5-test-fix (0192f5d: RV-AL5
  asserts the Referee-enforced attack set). Rerun: `uv run --frozen pytest -q tests/review/test_rv_agent_loop.py tests/integration/test_agent_loop.py -rs`.
  No reviewer replay of the RV-AL3/AL4 fixes found.

## G05 Harness truth isolation (Research/Max)
- Research: truth joined only by the scorer (EVIDENCE §5/§6), self-reported "PARTIAL (logical only)
  … OS-level access denial NOT_RUN". Idea family: `HO/tests/test_ideas.py` (9c52e0d)
  `test_views_carry_no_truth`, `test_synthetic_cli_writes_truth_only_after_results`; the 2234 report
  self-reports "enforced in code only; Research wrote both the requests and the league choice".
- Experience fixture engine: `apps/web/tests/test_core.py::TestEngineIsolation`,
  `test_api.py::test_full_synthetic_run_reveal_export`; ledger `apps/web/evidence/acceptance_ledger.json`
  "FIXTURE_ENGINE_EVIDENCE_ONLY". Rerun in `apps/web`: `python -m unittest discover -s tests -v`.
- Scenario estimates (Max): what-if numbers never show synthetic truth; none exists there.
- Reviewer: OS isolation "NOT_RUN by design" (1642, 1733).

## G06 Null and power (Research)
- `HO/evidence/harness_report.json`, `harness_league_results.csv`, `null_calibration.json` (6eba349).
  Rerun (HO; needs a build): `python -I scripts/shot_association.py harness data/run1 evidence`.
  Self-reported: 1,000-league null 0.043 [0.032, 0.057]; family C confounder rejection 0.380;
  "500/family target met only for A null".
- Idea family synthetic, one league each: `HO/evidence/idea-family/synthetic_gamma0`, `synthetic_gamma030`
  (d43b29a). Rerun (HO): commands in `HO/evidence/idea-family/RUN_PLAN.md` lines 14–15. Self-reported:
  "Found 1 of 9 planted … 0 false candidates"; replicated scoreboard NOT_RUN.
- Experience fixture engine, 360 leagues: `incoming/experience-20261107/evidence/harness_batch.json`
  (7d7bb86; only under `incoming/`). Self-reported: tuning 3/80 null, power 59/80, held-out 1/40,
  27/40. No rerun command given.
- Max loop: `reports/max/2026-11-07-1641-agent-loop.md`: "10 null and 6 planted leagues are a
  smoke-level" check.

## G07 Calibration separation (Research)
- Disjoint chronological fit/tune/calibration/final splits with `split_manifest_hash`; held-out harness
  family B (EVIDENCE §2/§5). Self-reported G07 "NOT_RUN … calibrator deliberately not fitted (D4)".
- Experience: "PARTIAL_FIXTURE_EVIDENCE" (held-out family ar1_drift); "No trust-score calibration was built".
- Scenario tables (`data/scenario/`, f86d797) use empirical-Bayes shrinkage, not calibration; the page
  labels every number ESTIMATE. A simulated support score is not a calibrated probability.
- Evidence for the gate as defined: **none**.

## G08 Final-data/adaptivity (Max/Research)
- Research custodian: `HO/tests/test_custodian.py` (6eba349), `test_guard_fixes.py` (e7e8857; Linux):
  restart, new ID, retry, concurrency, re-spelled IDs, shot/game exposure keys, seal. Ledger
  `HO/evidence/custodian_ledger.jsonl`.
- Reviewer probes: `HEATCHECK_REVIEW_RESEARCH_SRC=handoff/research-20261107/src uv run --frozen pytest tests/review/incoming/test_rv_research_custodian.py` (Linux).
  Reviewer 1733 (5d3261e): "PASS 10/10"; RV-R1 tamper refused (`python -I scripts/game_prediction.py final <tampered> <copy of evidence>`).
- GP final and amended replay: `HO/evidence/game_prediction_final.json`, `…replay-GP-2023-24-C1-vs-B1-AMEND-1.json` (dfb5d64).
  Rerun on a **copy**: `python -I scripts/game_prediction.py final data/run1 <copy of evidence>`; reviewer 1642/1733: same receipt `3e238d2d`.
- Confirmatory 2024-25 (run once, user-authorised): `HO/evidence/confirmatory-2024-25/` (5f0a432),
  `reports/review/2026-11-07-2232-confirmatory-run.md`, logs `reports/review/logs/2026-11-07-confirmatory/`.
  Operator: "Claude (adviser session), standing in for the independent reviewer" — the same session
  rebuilt, ran and post-checked; no separate replay of `final_result.json` exists. Read-only checks:
  Max's lane `uv run --frozen pytest -q tests/integration/test_confirmatory_lane.py tests/integration/test_recorded_results.py`
  (dry run reports FINAL_DONE; only the `platform` check fails on Windows, by design).
- Do not rerun `confirmatory.py final` (see above).

## G09 Forecast comparison (Research)
- GP final: 300/300 games, 0 fallbacks, B0/B1/C1, log loss/Brier, 7-day block bootstrap, Holm
  (EVIDENCE §3; `HO/evidence/game_prediction_dev.json`, `game_prediction_final.json`). Self-reported
  H2 SURVIVED_PROTOCOL (+0.0644, Holm 0.0458), H1 INSUFFICIENT_EVIDENCE. Reviewer 1642/1733: "PASS, reproduces".
- Live forecast backtest stated in `data/live/forecasts.json` (2024-25: log loss 0.6290, Brier 0.2196),
  script `HO/scripts/live_forecast.py`; no rerun command given; self-reported.
- Market comparison is **not** a forecast-skill comparison: 12 of 13 comparable games had the model
  above the ask (`reports/max/2026-11-08-market-live-recorded/README.md`), which suggests model bias.

## G10 NBA event mapping (Max/Research)
- Research fixtures: `HO/tests/test_quotes_mapping.py` (matched / incompatible / ambiguous blocks).
- Experience: `apps/web/tests/test_core.py::TestMapping`; `tests/experience/test_e001_rv_fixes.py`,
  `tests/experience/test_live_quotes.py` (57 tests). Rerun: `uv run --frozen pytest -q tests/experience`.
- Max mapping verification (16 identity checks per contract): `tools/verify_mappings.py`,
  `data/max/mapping_verifications/`, `tests/contracts/test_mapping_verification.py`. Rerun on the newest
  capture (02:15 UTC, commit 108b581):
  `uv run --frozen python tools/verify_mappings.py <scratch dir> data/experience/quotes/20261108T021507Z/*-pm-*`
  (the first argument is the output directory: use a scratch dir, because writing into
  `data/max/mapping_verifications` rewrites the committed records with a new timestamp), then compare
  the checks with the committed `data/max/mapping_verifications/*-pm-0215.json`
  — author's run: 13/13 Polymarket VERIFIED. Those 13 records first stored `bundle_dir` as an absolute Windows path, which
  broke CI on Linux (runs 42437889459, 42438601883); the field was made repo-relative in the commit
  after 1941cdc, every other byte unchanged, and `tools/verify_mappings.py` now always writes it relative. The 0215 capture's bundle
  provenance text also names the forecast file by an absolute local path (content-hashed raw files,
  so left as captured; not used for loading); later captures use repo-relative paths. Kalshi mappings are not verified (overtime rule UNKNOWN); the
  market check uses only VERIFIED mappings.

## G11 Quote normalization (Research/Experience)
- Research: `HO/tests/test_quotes_mapping.py` (Kalshi derived ask, cents vs dollars, float rejection,
  crossed book, stale/future). Self-reported "Experience's independent fixtures pending".
- Experience: `apps/web/tests/test_core.py::TestQuotes`, `TestComparison`; ledger status
  "EXPERIENCE_FIXTURES_PASS_PENDING_RESEARCH" (author label, not a reviewer pass).
- Reviewer probes: `uv run --frozen pytest -q tests/review -rs` (`test_rv_e001_adapter.py`; 16 deferred
  market probes are strict xfail in `test_rv_validator_probes.py`).
- Max: `tests/contracts/test_eligibility.py` (quote eligibility). Market wording is descriptive only
  ("Worth investigating · Edge unverified"); tested in `tests/integration/test_market_investigation.py`.

## G12 Read-only live adapters (Experience)
- Capture 1: `tests/fixtures/quotes/e001-recorded-0022600189/`; `reports/experience/2026-11-07-1623-live-quote.md`.
  Offline rebuild: `uv run --frozen python -m heatcheck.markets.adapters.capture build tests/fixtures/quotes/e001-recorded-0022600189 --check`.
  Self-reported "PARTIAL_EVIDENCE … rate-limit/429 not exercised".
- Capture 2 (SAMPLE game list): `data/experience/quotes/20261107T222950Z/`; `reports/experience/2026-11-07-2240-live-quotes.md`.
- Max captures on the real list: `data/experience/quotes/20261108T001759Z/`, `20261108T001942Z/`,
  `20261108T021507Z/` (108b581, with `CAPTURE_SUMMARY.json`); report `reports/max/2026-11-08-market-live-recorded/`.
- One-command live rerun (network, read-only GETs): `capture_quotes.cmd` (Windows) or
  `uv run --frozen python tools/capture_quotes.py`. Author's run 02:15 UTC: 24 MATCHED, 4 REJECTED, 188 files,
  no key value in any file.
- Contradiction: `apps/web/HANDOFF.md:98` and the Experience ledger G12 say "BLOCKED"/never ran; the
  reports above document live captures. Reviewer 1642 row 4e passed the recorded bundle; G12 live
  capture itself "NOT_RUN by me".

## G13 Authority/immutability (Max)
- Ledger hash chain: `tests/integration/test_ledger_chain.py`; retry identity and agent loop:
  `tests/integration/test_agent_loop.py`, `tests/integration/test_dialogue.py`.
- What-if confirmation binding (any edit revokes, 409 on stale confirmation, ledger receipt):
  `tests/integration/test_scenario.py` (11772da onward).
- Experience: `apps/web/tests/test_core.py::TestAuthority` (edit revokes, stale hash, retry identity,
  8 concurrent starts → 1).
- Research write-once: `test_write_once_never_overwrites`, `test_gp_replay_rerun_keeps_first_result_file` (HO).
- Rerun (root): `uv run --frozen pytest -q tests/integration/test_ledger_chain.py tests/integration/test_agent_loop.py tests/integration/test_dialogue.py tests/integration/test_scenario.py`.
- Reviewer 1716 found RV-AL1/AL2 (ledger edits/deletions undetected); `docs/SUBMISSION.md` says "Fixed
  with a hash chain"; **no reviewer replay of that fix found**.

## G14 Injection/resource/security (All)
- Experience: `apps/web/tests/test_api.py`, `test_proxy.py` (host rebinding 421, cross-origin 403,
  traversal, 413, non-loopback upstream refused); `tests/experience/test_e001_readonly.py`,
  `test_e001_rv_fixes.py` (exact-path allowlist, GET only). RV-E1 fixed in 602ae1d; Experience ran the
  reviewer probes itself ("43/43"); no reviewer re-replay found.
- Keys: provider keys are read server-side only (`heatcheck/agents/llm.py`, env `META_API_KEY`);
  `tools/capture_quotes.py` refuses if a key value appears in captured files. Secret scans in Research
  reports 1633/1719 (self-reported). Rerun a scan (does not print values):
  `grep -rlF "$(cat ~/balldontlie_key.txt)" . --exclude-dir=.git --exclude-dir=.venv` → expect no output.
- No order capability: no code path places, signs or submits orders; venues are GET only
  (`apps/web/server/venues.py`, `heatcheck/markets/`). Reviewer check suggested:
  `git grep -nE "POST|/orders|place_order|sign" -- heatcheck apps/web/server`.
- Free-text routing and what-if parser accept arbitrary text; input bound tests are in
  `tests/integration/test_scenario.py` (routing/parsing), not a fuzzing campaign.

## G15 Real interface/voice (Experience)
- Original browser runs: `incoming/experience-20261107/evidence/e2e_results.json` (66 passed),
  `extension_results.json` (10 passed), screenshots (only under `incoming/`); fake microphone only.
  Rerun in `apps/web` with the server on 8765: `node tests/e2e_browser.mjs`, `node tests/e2e_extension.mjs`.
  Reviewer 1642 row 4d: "PASS … not a real-microphone test".
- Max's headless Playwright runs (Windows, speech off, no mic): `reports/max/2026-11-07-demo-e2e/`,
  `reports/max/2026-11-08-market-live-recorded/`, `reports/max/2026-11-08-scenarios-routing/` (script
  `shoot_route.py` there; run `demo.cmd --fresh-ledger --no-browser --no-llm --recorded-market`, then
  `uv run --frozen python reports/max/2026-11-08-scenarios-routing/shoot_route.py <out dir>`).
- Real voice and microphone in a real browser session: **none** (NOT_RUN everywhere).

## G16 Separate review/replay (Max)
- Reviewer reports (non-author): `reports/review/REVIEW_PREP.md`, `2026-11-07-1642-r001-e001-replay.md`,
  `2026-11-07-1716-agent-loop-and-xfail.md`, `2026-11-07-1733-research-guard-fixes.md`; raw logs
  `reports/review/logs/`. `2026-11-07-2232-confirmatory-run.md` by a stand-in operator (see G08).
- **No review exists** for anything after ~22:30 on 7 Nov: live forecast, market board and
  investigations, scenario effects and what-if, free-text routing, Heater idea proposer, idea board,
  `capture_quotes`. Those need a replay before any gate covering them is marked.

## G17 Demo and claims (All)
- `docs/SUBMISSION.md` (32bf407) cites evidence per number; Max demo evidence in the report folders
  under G15 and `reports/max/2026-11-07-2059-deterministic-ref-recorded-finals.md`.
- Labels on the page: SAMPLE, RECORDED (quote time on card and in the Ref line), ESTIMATE,
  HYPOTHETICAL, "Edge unverified", "Proposed by Heater … Not run yet" (screenshots in
  `reports/max/2026-11-08-scenarios-routing/`).
- No review of claim-to-evidence linkage found. `docs/SUBMISSION.md` predates scenarios, routing and
  the model-proposed idea family.

## G18 Eligibility/submission (User/Max)
- `ELIGIBILITY.md`: organiser ruling on pre-event plans/code/data/AI reuse NOT_RECORDED;
  `docs/SUBMISSION.md` §9 repeats it. Event rules and submission requirements: **none recorded**.
- Preparation vs event dates are in git history (preparation 7 Nov; event development 7–8 Nov).

## Known contradictions and stale claims (found while compiling this)
- `ACCEPTANCE.json` lists no evidence for any gate; the HO and Experience ledgers carry their own
  author-assigned statuses (e.g. "EVIDENCE_SUBMITTED", "PASS_PENDING_RESEARCH"). Neither is a reviewer mark.
- `DEFECTS.md` still says "No production functionality exists".
- `apps/web/REPORT.md` cites `evidence/test_run.log`, `e2e_results.json`, `harness_batch.json`,
  `screenshots/` that exist only under `incoming/experience-20261107/evidence/`; it describes 68 tests
  (now 104).
- `HO/EVIDENCE.md` §8 says 40 tests; the HO suite now has 100 collected on Windows plus the
  Linux-only files. Its G07/G08/G11 rows predate the seal and RV fixes.
- `incoming/research-20261107/` is the pre-fix copy; review `handoff/research-20261107/`.
- Local data manifest `upstream_revision` defect (see "Before you start").
