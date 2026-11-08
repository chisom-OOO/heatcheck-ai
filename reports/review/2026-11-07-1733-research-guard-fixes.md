# Reviewer report: replay of Research's RV-R1/R2/R4/R5 fixes

Written 2026-11-07 17:33 UTC (container clock). Role: independent reviewer (G16), not the author.

**Candidate:** `research/r001-guard-fixes@dfb5d64`, with code at `c822b55`.
`git diff c822b55 dfb5d64` over `handoff/**/{src,scripts,tests}` is empty: `dfb5d64` adds only
the amendment, one ledger line, the replay result and Research's report.

**Research report reviewed:** `reports/research/2026-11-07-1719-rv-guard-fixes.md`.

**Machine and environment:**
- Linux x86_64, 4 CPUs.
- Python 3.13.18, numpy 2.5.3, pandas 3.0.5, scipy 1.18.1, scikit-learn 1.9.1, pytest 9.1.1.

**Data:** my own Linux build from 7 Nov. Unchanged `build_dataset.py` (`ea15c620`) built it
from the three `shufinskiy/nba_data@46488f0f` archives verified against `SHA256SUMS`, so it is
independent of Research's build. Under the new `store.logical_table_hashes` it matches 7 of 7
of the plan's `data_hashes`.

**Isolation:** all runs used `git archive` copies in scratch. No committed evidence or ledger
was modified. **Raw logs:** `reports/review/logs/2026-11-07-guard/`.

**Also in this round:** the xfail change is pushed at
`870f3fb1d56b712e85f3406600622c4824932e0c`. It applies
`pytest.mark.xfail(strict=True, reason="Deferred: docs/DECISIONS.md")` to the 16 deferred
probes, with assertions unchanged.

## Results

| # | Check | Command (in the `dfb5d64` handoff copy) | Expected | Actual |
|---|---|---|---|---|
| 1 | Handoff test suite | `HC_DATA=<my data> python -m pytest -v -rs` | 63 pass, 0 skip | **PASS** 63 passed, 0 skipped (60 s). Committed evidence unchanged by the run (`handoff_pytest.txt`) |
| 2 | Reviewer custodian probes, new code | `HEATCHECK_REVIEW_RESEARCH_SRC=<dfb5d64>/src pytest tests/review/incoming/test_rv_research_custodian.py` | 10/10 | **PASS** 10/10: the `nba:` prefix, dropped leading zeros, leading space and trailing newline can no longer reopen exposure; fork, spawn and forkserver races; truncated ledger fails closed; retry after spend; subset ≠ retry |
| 2b | Control: same probes, pre-fix code (`5604d36`) | same | 4 fail | **4 failed, 6 passed**: the probes still catch the old bug |
| 3a | RV-R1 tamper, post-fix evidence | `home_win` flipped for the 40 final games `0022300902…0022300941`; `python -I scripts/game_prediction.py final <tampered> <copy of dfb5d64 evidence>` | refused, nothing written | **PASS**: `REFUSED: input data differ from the frozen plan's data_hashes: ['game_labels']`, exit 2; evidence dir byte-identical (`diff -rq`), ledger 3 lines |
| 3b | Same with `python -I -O` (asserts stripped) | | refused | **PASS**: same refusal, exit 2, byte-identical |
| 3c | RV-R1 tamper, pre-fix evidence (2-line ledger, no amendment) | same, on a copy of `5604d36` evidence | refused | **PASS**: same refusal, exit 2, byte-identical, ledger 2 lines; also under `-O` |
| 4a | Amended final replay on committed post-fix evidence | `final <my data> <copy of dfb5d64 evidence>` | receipt `3e238d2d`, same verdicts, ledger untouched | **PASS**: exit 0, receipt `3e238d2d…`, ledger still 3 lines, byte-identical. The result equals Research's replay file in every field except `created_at_utc` |
| 4b | Independent amend + replay from pre-fix evidence | 1. `final` with no amendment; 2. `amend <data> <ev> "reviewer independent replay of c822b55"`; 3. `final`; 4. `final` again | 1. refused; 3. receipt `3e238d2d`, same verdicts; 4. idempotent | **PASS**. Step 1: exit 2 "…no CODE_IDENTITY_ONLY amendment matches… a new experiment". Step 2: my amendment has code hash `656861b1…bfa`, equal to Research's. Step 3: receipt `3e238d2d…`, one `replay` line appended, the original 2 lines byte-identical. Step 4: ledger byte-unchanged. `input_hash dbb4d3e4…` equals Research's, so the data binding agrees across independent builds |

**Verdicts** are identical in all four results: the original 15:22Z run, Research's replay, my
replay A and my replay B. `decisions`, `scores` and `counts_coverage` all compare equal.

| | Decision | Mean (nats) | 95% CI | Holm p |
|---|---|---|---|---|
| H2 Elo vs base rate | SURVIVED_PROTOCOL | +0.064378 | [0.010615, 0.128168] | 0.045795 |
| H1 rest/B2B vs Elo | INSUFFICIENT_EVIDENCE | +0.020059 | [−0.004330, 0.043809] | 0.048995 |

## Additional adversarial probes (reviewer's own)

| Probe | Expected | Actual |
|---|---|---|
| Tamper a **public** table instead of labels (`games.neutral_site` flipped for `0022300905`) | refused | **PASS**: `REFUSED: … ['games']`, exit 2, evidence byte-identical |
| Edit the **plan's threshold**: `practical_effect_floor` 0.002 → 0.07, which would turn H2 into INSUFFICIENT. Plan hash recomputed (`a8d81292…` → `4a50909c…`) and a matching amendment re-hashed | refused; no verdict under receipt `3e238d2d` with a different rule | **PASS**: `REFUSED: amended replay needs exactly one original reservation of this plan`, exit 2, ledger unchanged |

## Verdict on the fixes

- **RV-R1: FIXED, verified.** Data changes in labels or in public tables are refused before
  anything is reserved, scored or written. This holds with `-O` and from both pre-fix and
  post-fix ledger states.
- **RV-R2: FIXED, verified** (10/10 reviewer probes; the control still fails on old code).
- **RV-R4:** verified indirectly. The amendment's `code_files` lists the 9 files, including
  `util.py`, `store.py`, `canonical.py` and `build_dataset.py`. Changed code without a
  matching amendment is refused (4b step 1).
- **RV-R5:** not separately re-reviewed beyond the identical sensitivity output; Research
  reports `NOT_COMPUTED` with reasons.
- **The replay reproduces** receipt `3e238d2d` and both verdicts exactly.

## Remaining observations (not blocking)

1. **Low.** Rerunning `final` rewrites the replay result file in place
   (`game_prediction_final.replay-…AMEND-1.json`). Only `created_at_utc` changes and the ledger
   does not, but a committed result file is not write-once. I suggest refusing to overwrite,
   or writing a new file per run.
2. **As Research states, unchanged:**
   - Amendments make repeated code changes visible, but they don't prevent them. Max should
     treat more than one `replay` line per receipt as a review trigger.
   - The binding for the original 15:22Z run can't be proven after the fact
     (`NONE_PREDATES_BINDING`).
   - Exposure is per record ID, so shot-level IDs over the final games wouldn't collide with
     the reserved game IDs. Max to rule.
   - Isolation is logical only.
3. D12 (field goals only, free throws out of scope) closes RV-R6 by decision. The reviewer's
   `test_candidate_builder_covers_free_throws` will be marked to follow D12 once Max merges it.

## Gate status

| Item | Status |
|---|---|
| RV-R1, RV-R2 | **PASS** (fixed and replayed on Linux with independent data) |
| GP final replay under fixed guard | **PASS**, reproduces `3e238d2d` and both verdicts |
| Handoff suite at `c822b55` | **PASS** 63/63 |
| OS-level isolation | NOT_RUN (not implemented) |
