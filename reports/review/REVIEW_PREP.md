# Independent review: preparation and validator findings

Reviewer: independent reviewer session (not Max, Research or Experience).
Branch: `review/independent-tests`, based on `max/integration@8210fda`. Prepared 2026-11-07.
Scope: tests for pre-shot leakage, mismatched games/teams, reversed outcomes, quote units and
timestamps, stale quotes, and incompatible overtime rules. Candidate R-001/E-001 branches have
**not been received yet**, so every candidate gate is NOT_RUN.

## Environment and commands

Linux container, Python 3.13.18 via `uv 0.11.32` (`uv run --frozen`, `uv.lock` unchanged), no network
used by the tests (candidate tests patch `socket.socket`, `create_connection` and `getaddrinfo`).

```
uv run --frozen pytest -q                       # 25 failed, 100 passed, 9 skipped
uv run --frozen pytest -q tests/contracts       # 44 passed (baseline, unchanged)
uv run --frozen pytest -q tests/review -rs      # 25 failed, 56 passed, 9 skipped
uv run --frozen ruff check .                    # All checks passed!
```

The 25 failures are all in `tests/review/test_rv_validator_probes.py`. Each prints
`EXPECTED REJECT, ACTUAL PASS: <reason>` or `DID NOT RAISE RecordError`. They are left failing on
purpose; they are not marked xfail.

## Suite layout (`tests/review/`)

| File | What it does | Runs now? |
|---|---|---|
| `review_support.py` | Synthetic 4-period + overtime game (free-throw trips, assists, same-clock events), the reviewer's own pre-shot feature builder, a leaky negative-control builder, and the flip/invariance harness | n/a |
| `review_checks.py` | Semantic checks on candidate bundles, beyond what the validator proves (DATA_FORMAT §5) | n/a |
| `test_rv_validator_probes.py` | Mutates Max's reference bundle in each of the six categories; asserts that the shared validator rejects it | **yes** – 21 pass, 25 FAIL |
| `test_rv_preshot_invariance.py` | Harness self-tests (positive control passes, leaky control is caught, downstream sensitivity), then runs the same harness against Research's builder | self-tests yes; candidate NOT_RUN |
| `test_rv_checks_selftest.py` | Proves each semantic check fires on a known-bad bundle and stays quiet on a known-good one | **yes** – all pass |
| `test_rv_candidates.py` | Runs `review_checks` on the actual R-001 / E-001 bundles, plus the A1 CLI replay | NOT_RUN |

The harness is stricter than R-001 A4. Flipping shot *k* must leave **every** row for shots at
sequence ≤ *k* byte-identical, not only shot *k*'s row. It also checks that the builder ignores
input list order, ignores `assisted_post_outcome`, and emits one valid row per shot.

## Findings against the shared validator (M-001, `heatcheck/contracts`)

Reproduce any finding with `uv run --frozen pytest -q tests/review/test_rv_validator_probes.py::<test>`.
In each case the expected result is that the bundle or record is rejected; the actual result is
that it is accepted (`PASS`). Severity is the reviewer's judgement.

| ID | Test | Input | Expected | Actual | Sev. |
|---|---|---|---|---|---|
| RV-L3 | `test_rv_l3_cutoff_after_target_shot_rejected` | Row for shot e3 (seq 3) with `before_sequence=4`, `max_input_sequence=3`, so the shot is its own input | reject | PASS | High |
| RV-L4 | `test_rv_l4_source_hashes_include_target_shot_rejected` | Target shot's own EVENT hash added to `source_record_hashes` | reject | PASS | High |
| RV-L5 | `test_rv_l5_target_id_resolves_to_no_event_rejected` | `target_id` = `…:shot:e999` (no such shot) | reject | PASS | Med |
| RV-L6 | `test_rv_l6_source_hashes_reference_unknown_records_rejected` | `source_record_hashes=["fff…"]` | reject | PASS | Med |
| RV-G1 | `test_rv_g1_event_team_not_in_game_rejected` | EVENT `team_id=syn-team:OTHER` | reject | PASS | High |
| RV-G2 | `test_rv_g2_feature_row_target_from_other_game_rejected` | FEATURE_ROW for G0002 whose target is G0001's shot | reject | PASS | Med |
| RV-G3 | `test_rv_g3_team_win_label_team_not_in_game_rejected` | TEAM_WIN label for a non-participant | reject | PASS | Med |
| RV-O1 | `test_rv_o1_final_score_swapped_against_events_rejected` | GAME_FINAL_SCORE home/away swapped (events say 2–0) | reject | PASS | High |
| RV-O2 | `test_rv_o2_shot_made_label_contradicts_event_rejected` | SHOT_MADE `false` for an EVENT with `made: true` | reject | PASS | High |
| RV-O3 | `test_rv_o3_team_win_contradicts_final_score_rejected` | TEAM_WIN `won` for the team that scored 0 | reject | PASS | Med |
| RV-O4 | `test_rv_o4_final_tie_rejected` | FINAL game, label 2–2 | reject | PASS | Low |
| RV-O5 | `test_rv_o5_quote_level_derived_complement_rejected` | QUOTE level `derivation: DERIVED_COMPLEMENT`; DATA_FORMAT says QUOTE stores venue levels (DIRECT) | reject | PASS | Med |
| RV-O7 | `test_rv_o7_both_outcomes_mapped_to_same_team_win_rejected` | YES and NO of one market both mapped to HOME `TEAM_WINS` | reject | PASS | High |
| RV-U2 | `test_rv_u2_off_tick_price_rejected[0.537/0.0053/0.005]` | Price off the market's 0.01 tick; `0.0053` is cents divided by 100 twice | reject | PASS | High |
| RV-U3 | `test_rv_u3_zero_size_level_rejected` | Level `size: "0"` | reject | PASS | Low |
| RV-U7 | `test_rv_u7_provider_time_after_received_rejected` | `provider_time_utc` 5 h after `received_utc` (local time stored as UTC) | reject | PASS | Med |
| RV-U8 | `test_rv_u8_raw_snapshot_time_outside_fetch_window_rejected` | **Max's reference fixture as committed**: QUOTE fetched `2024-01-01T00:00:00Z`, its raw book snapshot `retrieved_utc` is `2026-11-07T12:00:00Z` | reject | PASS | Med |
| RV-U9 | `test_rv_u9_manifest_created_utc_is_validated` | manifest `created_utc="yesterday afternoon"` | reject | PASS | Low |
| RV-S1 | `test_rv_s1_ok_quote_with_two_hour_old_provider_time_rejected` | `status: OK`, provider time 2 h before receipt | reject or force STALE | PASS | High |
| RV-S2 | `test_rv_s2_ok_quote_with_one_day_fetch_window_rejected` | `status: OK`, fetch started 24 h before receipt | reject | PASS | Med |
| RV-T2 | `test_rv_t2_verified_regulation_only_for_team_wins_rejected` | `VERIFIED`, `REGULATION_ONLY`, `TEAM_WINS` (Research doc §143: different target) | reject | PASS | High |
| RV-T3 | `test_rv_t3_verified_unknown_cancel_postpone_rejected` | `VERIFIED` with `cancel_postpone_convention: "UNKNOWN"` (G10: unknowns block) | reject | PASS | High |
| RV-T4 | `test_rv_t4_verified_without_rules_hash_rejected` | `VERIFIED` mapping, market `rules_text_sha256: null` | reject | PASS | Med |

Probes that passed, so the validator does reject these inputs: `max_input_sequence == cutoff`,
a fractional-second UTC cutoff leak, a non-participant mapping team, a quote/mapping contract
mismatch, a real id in SYNTHETIC mode, a crossed OK book (bid and ask swapped), a cents price
`"53"`, six non-canonical timestamp forms (offset, naive, space, epoch string, 7-digit fraction,
Feb 30), an epoch-millis integer, `received < fetch_start` with fractions, STALE without a reason,
and `VERIFIED` + `UNKNOWN` overtime.

`test_rv_g7_…` is documented as a known limit, not a defect: a mapping to the same teams on
a different date passes. Nothing in the format binds a market to a date. The check is
deferred to candidate review.

### Spec gaps and observations (no test failure)

- **No freshness threshold is configured anywhere.** DATA_PIPELINE §4 step 4 requires one
  before the demo. The reviewer default is `HEATCHECK_REVIEW_STALE_SECONDS=60`. That number is
  the reviewer's choice, not a project rule; Max should set the real value.
- `Shared_Protocol.json` BookSnapshot lists `clock_uncertainty`; the `QUOTE` record has no such field.
- DATA_FORMAT recommends FEATURE_ROW `record_id = <target_id>:<feature_version>`. The reference
  fixture uses `…:shot:e3:v1` with `feature_version: synthetic-preshot-1`.
- FEATURE_ROW leakage screening is name-based (`assist` only). Names like `shot_made_flag` pass.
  The reviewer's candidate check flags outcome-like names, but that is only a heuristic.

## What the candidate checks look for (`review_checks.py`)

- **Research (R-001).** Checks:
  - Mode and id: data mode and a `nba:00223xxxxx` regular-season id.
  - Teams and order: every EVENT team is a participant; no duplicate sequences or revisions.
  - Clock: overtime periods are ≤ 300 s and the clock never rises within a period.
  - Labels: the final-score label equals the made-shot totals with home/away identity (flags
    REVERSED), no FINAL tie, `RECONCILED` (A3), and every SHOT_MADE matches its EVENT.
  - Feature rows: one PRE_SHOT_MAKE row per shot or a manifest exclusion; cutoff equals the shot
    sequence; every input hash exists, is an earlier EVENT and never a label; no outcome-like
    feature names.
  - Values: the five minimum features equal the reviewer's independent recomputation.
- **Experience (E-001).** Checks:
  - Manifest: role and data mode honesty.
  - Mapping: `PROPOSED` only; the outcome label names a team, not NO/HOME/AWAY; one contract per
    team per market; overtime ≠ UNKNOWN requires a rules hash and rules text that mentions
    overtime; REGULATION_ONLY is flagged as not comparable.
  - Levels: DIRECT only, on the tick grid, positive size, no zero price, and every price
    traceable to the raw payload (as dollars, or cents ÷100 under a `cent` field).
  - Timestamps: provider time is not after receipt (2 s tolerance); OK quotes are not stale; the
    fetch window is ≤ threshold; the raw snapshot time lies inside the fetch window; the manifest
    is not created before receipt.
  - Game: an OK quote was received before the scheduled tip, and its game is not
    POSTPONED/CANCELLED/FINAL.

## Gate status

| Gate / criterion | Status | Scope |
|---|---|---|
| Validator probes (six categories) | **FAIL**: 25 of 46 probes accepted malformed input | `max/integration@8210fda`, synthetic reference bundle only |
| Reviewer harness self-tests | PASS | synthetic data only, not an NBA gate |
| R-001 A1–A7 (and the stronger invariance harness) | NOT_RUN | no Research branch received |
| E-001 A1–A6 and semantic checks | NOT_RUN | no Experience branch received |
| Adapter refusal probes (cents, missing `received_utc`, unknown outcome, midpoint/last trade as level, non-GET/off-allowlist) | NOT_RUN | written once the adapter's API is known |
| G01/G02/G10–G12 | NOT_RUN | |

## How to run against the candidates

```
git fetch origin research/r-001-one-game experience/e-001-quote-fixture
git checkout <candidate commit> -- heatcheck/ tests/research tests/experience tests/fixtures/quotes data/manifests reports
HEATCHECK_REVIEW_FEATURE_BUILDER=heatcheck.research.<module>:<function> \
HEATCHECK_REVIEW_RESEARCH_BUNDLE=data/bundles/r001-<game> \
HEATCHECK_REVIEW_RESEARCH_SYN_BUNDLE=<committed synthetic fixture dir> \
HEATCHECK_REVIEW_EXPERIENCE_BUNDLE=tests/fixtures/quotes/e001 \
uv run --frozen pytest -q tests/review -rs
```

The candidate tasks' own acceptance commands are also replayed on their exact commits.
