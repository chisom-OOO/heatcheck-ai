# HeatCheck-Research: evidence packet (first handoff)

Protocol `heatcheck-nba/1` · produced 2026-11-07 ~15:40 London · author: HeatCheck-Research (Pro coding session)
All numbers come from executed code in this repo. Raw output is in `evidence/`. Decisions and pre-registrations are in `DECISIONS.md`, written before the results they govern.
**Research cannot self-accept.** Every gate below is marked `EVIDENCE_SUBMITTED` and still needs replay by Max, the reviewer (G16).

## 1. Frozen dataset — 2023–24 regular season

| Item | Value |
|---|---|
| Upstream | `shufinskiy/nba_data` @ `46488f0f8e1cab58fc1256511ea808166a443a15` (commit 2026-11-06) |
| Provider | `cdnnba` (NBA CDN play-by-play). `nbastats` used only as a same-org consistency check |
| Archive SHA-256 | cdnnba_2023 `33d49fef…6101b`; nbastats_2023 `ec0029c0…a913`; cdnnba_2022 `de895e34…b41f` |
| Games | 1,230 included / 0 excluded (IDs 0022300001–0022301230 contiguous) |
| Events | 674,937. 0 duplicate `orderNumber`, 0 duplicate `actionNumber` |
| Field-goal attempts | 218,693 |
| Points check | made-shot points = final score in 1,230/1,230 games |
| Reconciliation vs stats.nba.com | home team + final score MATCH 1,230/1,230 (not an independent source) |
| BALLDONTLIE cross-check | **NOT_RUN**: no user key. Coverage `UNVERIFIED_EXTERNAL` |
| Ordering | `orderNumber` used. `actionNumber` has 6,152 inversions, so it is not a sequence. 7 clock-regression steps → 210 FGAs get ordering-dependent features set missing |
| Neutral sites flagged | 4 (Mexico City, Paris, 2× Las Vegas IST semis) |
| Replay determinism | two independent builds → all 7 logical table hashes identical. Retrieval timestamps differ, as they should (`evidence/replay_determinism.txt`) |

Leakage audit of shot fields: `block_person_id` predicts miss with certainty, assist fields exist only on makes, and `descriptor` is a scorer annotation correlated with outcome (alley-oop 81% made). All three are banned from pre-shot features, and the banned-column assertion is tested.

## 2. Splits (whole games, chronological, cut on ET dates; hashed before evaluation)

| Split | Games | ET dates |
|---|---|---|
| fit | 619 | 2023-10-24 → 2024-01-19 |
| tune | 185 | 2024-01-20 → 2024-02-13 |
| calibration | 126 | 2024-02-14 → 2024-03-06 |
| final | 300 | 2024-03-07 → 2024-04-14 |

`split_manifest_hash = 30fded21be74e8b4fe0992908a402b8ef471c18414c5674ad7c90d1291508fcf`

## 3. GAME_PREDICTION: final family run once through the custodian

Plan `a8d81292…12cf8`, epoch `EPOCH-GP-2023-24-001`, receipt `3e238d2d-030e-45b4-aae7-db0787ecb873` (spent). Identical retry returned the same receipt and the same decisions. A renamed-family probe over 40 of the final games was **refused**. Coverage: 300/300 games, 0 fallbacks, 0 dropped.

| Model (final, n=300) | Log loss | Brier |
|---|---|---|
| B0 home-win rate (0.582) | 0.7022 | 0.2545 |
| B1 Elo (carry-over, fixed constants) | 0.6379 | 0.2221 |
| C1 Elo + rest diff + back-to-backs | 0.6178 | 0.2108 |

| Hypothesis | Mean improvement (nats) | 95% CI (7-day moving blocks) | p (1-sided) | Holm p | **Decision** |
|---|---|---|---|---|---|
| H2: B1 beats B0 | +0.0644 | [+0.0106, +0.1282] | 0.0229 | 0.0458 | **SURVIVED_PROTOCOL** |
| H1: C1 beats B1 | +0.0201 | [−0.0043, +0.0438] | 0.0490 | 0.0490 | **INSUFFICIENT_EVIDENCE** |

Read this carefully:
- H1's p-value is below 0.05, but the CI crosses zero, and the pre-registered rule needs both. Not a pass.
- In development, C1 was **worse** than B1 (tune −0.0047, calibration −0.0009 nats). The sign flip between dev and final points to instability, maybe late-season rest/load management. It is not a finding.
- The 14- and 28-day block sensitivities have too few blocks (2 and 1). The final span is 39 days, exactly 5 non-overlapping 7-day blocks, the pre-registered minimum.
- Pseudo-out-of-sample: 2023–24 outcomes are public.

## 4. SHOT_ASSOCIATION: hot hand, development games only (930 games, 165,710 FGAs)

| | Value |
|---|---|
| P(make \| previous 3 in player-game made) | 0.4827 (6,114/12,666) |
| P(make \| previous 3 missed) | 0.4777 (7,306/15,295) |
| Observed T | +0.0050 |
| Permutation null mean ± sd (within player-game-shot value, B=999) | +0.0190 ± 0.0048 |
| One-sided p (hot hand) | 0.996 → **NOT_REJECTED** |

The naive +0.5pp "hot hand" is **below** the design-valid null. Pooling counts across player-games inflates T under the null, because hot nights produce most of the after-3-makes opportunities. That's why the null isn't zero (Research §05). The observed value sits in the lower tail. That is an **exploratory** observation outside the registered one-sided test: it could reflect harder shots or tighter defence after makes. A crude difficulty attack (mean distance 13.9 vs 13.8 ft, 3pt share 37.8% vs 38.5%) shows little selection on those two measures. Final shot games were not opened.

## 5. Planted-truth harness: testing the tester (`data_mode=SYNTHETIC`)

150 leagues per condition, ~12k shots per league, B=99, α=0.05. γ is log-odds. Family B (heavy-tailed talents, volume mixture) is held out: no test parameter was chosen after seeing it.

| Family | Condition | Metric | Rate | Wilson 95% |
|---|---|---|---|---|
| A | null | false-positive rate | 0.007 | [0.001, 0.037] |
| A | γ = 0.30 | power | 0.867 | [0.803, 0.912] |
| A | γ = 0.12 | power | 0.307 | [0.238, 0.385] |
| B (held out) | null | false-positive rate | 0.013 | [0.004, 0.047] |
| B (held out) | γ = 0.30 | power | 0.880 | [0.818, 0.923] |
| C | no streak, within-game form drift | confounder rejection | **0.380** | [0.306, 0.460] |

- The A-null false-positive rate looked too low for an exact permutation test, so I diagnosed it rather than reported it as is. A **1,000-league** null calibration gives **0.043** [0.032, 0.057] at α=0.05 and 0.098 at α=0.10. The test is valid at nominal level, and the 150-league figure was a low draw. Nothing was changed (`evidence/null_calibration.json`).
- **Family C is the important product caveat.** Slow within-game form with *no* causal streak term triggers the test 38% of the time. A rejection on real data therefore can't separate a hot hand from form drift.
- Derived FDR (computed from the rates, not from replicated mixed families): with the 1,000-league false-positive rate 0.043 and power 0.867, **FDR ≈ 31% at 10% prevalence** and ≈ 5% at 50%. Low-prevalence claim streams generate many false discoveries even with a valid test. The harness's own derived numbers (6.5%/0.8%) use the low-draw rate and understate this.
- These are scripted runs of the test procedure, not autonomous LLM research runs. Truth/test separation is logical (same OS user).

## 6. Gate status (Research-owned or shared)

| Gate | Status | Evidence | Not covered |
|---|---|---|---|
| G01 Data/provenance | EVIDENCE_SUBMITTED | manifest, hashes, reconciliation, exclusions (none), rights note | external cross-check NOT_RUN; paginated-API interrupt/resume NOT_RUN (no API ingestion in this pass); upstream-revision handling NOT_RUN |
| G02 Temporal correctness | EVIDENCE_SUBMITTED | real-data future-perturbation (pre-game + pre-shot), leakage fixture fails as intended, withheld-label raises | model-memory exposure (only labelled) |
| G03 Statistical oracles | EVIDENCE_SUBMITTED | Beta(10,4) moments vs scipy, log-loss/Brier fixtures, Miller–Sanjurjo 17/42 exact, undefined cases | — |
| G04 Registered attacks | PARTIAL | leakage, multiplicity (Holm), block sufficiency, selection/null (permutation), difficulty crude | clutch, spec curve, influence, time replication NOT_RUN |
| G05 Harness truth isolation | PARTIAL (logical only) | truth joined only by scorer after test | OS-level access denial NOT_RUN (needs Max) |
| G06 Null and power | EVIDENCE_SUBMITTED | §5 plus 1,000-league calibration | 500/family target met only for A null |
| G07 Calibration separation | NOT_RUN | no support score built; game-prediction calibrator deliberately not fitted (D4) | — |
| G08 Final-data/adaptivity | PARTIAL | custodian library: persistence, restart, new-ID, retry, edited-code, concurrency probes | Max integration/process isolation |
| G09 Forecast comparison | EVIDENCE_SUBMITTED | identical 300 games, fallback rule, proper scores, block bootstrap, coverage | — |
| G10 Event mapping (Research part) | EVIDENCE_SUBMITTED (fixtures) | reversed outcome, same teams different date, OT mismatch, league, teams, ambiguous → blocked | no real venue metadata mapped yet |
| G11 Quote normalisation | EVIDENCE_SUBMITTED (fixtures) | Kalshi derived ask (both fixtures), cents vs dollars, float rejection, missing side, crossed book, stale/future quote | Experience's independent fixtures pending |

## 7. Interfaces for Max and Experience

- `heatcheck.features.pregame_features(games, labels, seed_ratings, target_ids)` raises `LabelUnavailable` if any needed earlier label is withheld. `preshot_features(events)` never reads the current shot's outcome fields.
- `heatcheck.custodian.Custodian(path).reserve(family_id, epoch_id, plan_hash, code_hash, record_ids)` → receipt. `.spend(receipt_id)` must be called before results leave. **Max:** run it in a separate process/user so isolation stops being logical-only.
- `heatcheck.quotes.kalshi_yes_book(yes_bids, no_bids, unit)` and `polymarket_book(token_id, bids, asks)` take provider **strings/ints** with an explicit unit (floats rejected). `eligible_quote(observations, cutoff, max_age)` and `compare(p, book, quote_type, mapping_status)` → `AVAILABLE`/`BLOCKED` + reasons.
- `heatcheck.mapping.map_contract(ForecastTarget, ContractSpec)`. **Experience** must fill every `ContractSpec` field from venue rules. Any `None` → AMBIGUOUS → comparison blocked.
- The model target is home win. A named-team display uses p or 1−p with `outcome_direction` recorded.

## 8. Reproduce

```
python -I scripts/build_dataset.py raw/repo data/run1 raw/extracted     # ~1 min
python -m pytest -v                                                     # 40 tests
python -I scripts/game_prediction.py dev    data/run1 evidence
python -I scripts/game_prediction.py freeze data/run1 evidence
python -I scripts/game_prediction.py final  data/run1 evidence          # custodian; retry-safe
python -I scripts/shot_association.py nba     data/run1 evidence        # ~40 s
python -I scripts/shot_association.py harness data/run1 evidence        # ~2 min on 2 cores
```
`raw/repo` is a clone of the upstream at the pinned commit, and `raw/extracted` is the untarred season CSVs. Raw files and derived SQLite are not redistributed (D9). Environment: Python 3.13, numpy 2.5.3, pandas 3.0.5, scipy 1.18.1, scikit-learn 1.9.1 (`evidence/test_run.txt`).
