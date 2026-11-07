# Research status: rulings applied, 2024-25 sealed, confirmatory family pre-registered (NOT run)

| | |
|---|---|
| Branch | `research/r001-guard-fixes` (continues from `dfb5d64`) |
| Code commits | `c05f540` rulings, upstream-revision fix, seal/register, confirmatory lane (17:42:17Z) · `491e09e` quarantine rule D19 (17:51:09Z) |
| Evidence commit | the commit containing this report (hash given to Max in chat): seal and registration ledger lines, frozen plans, development results, DECISIONS D20, logs |
| Code hash frozen in the family | `ebf6aaa4c8e69130f85b6b06e2879d57501d383d1cf170f96a0e3dd49702f09e` (code at `491e09e`) |
| Author | HeatCheck-Research, cloud session. Reviewer: not assigned for this change. |

## Stopped as instructed

**No confirmatory test has been run.** The 2024-25 epoch has zero reservations; `final_result.json` does not
exist; `confirmatory.py final` refuses without `--authorised-by <name>` (D18). The frozen family is ready to
run unchanged: the readiness check confirms plan hashes, code hash and sealed data hashes all match
(`logs/confirmatory/readiness.log`).

To run it at the demo, on a machine with the rebuilt 2024-25 data (rebuild is deterministic from the pinned
archives; the seal rejects any other bytes):

```bash
python -I scripts/confirmatory.py final <data_2024-25> evidence --authorised-by <name>
```

## Rulings

| Ruling | Implementation | Test |
|---|---|---|
| Every record id maps to its game before every exposure check; shot-level family over reserved final games refused | `custodian.exposure_key()`: bare/`nba:` ids, `GAME:`, `SHOT:<game>:<seq>`, EVENT `nba:<game>:<event>:r<rev>`, FEATURE_ROW/label ids, `syn:`; no game or two games → refused. Reservations store `exposed_games`; legacy lines are mapped on read | `test_shot_level_family_over_reserved_final_games_is_refused`, `test_game_family_over_reserved_shot_records_is_refused`, mapping/refusal tables (D14) |
| Second amendment on a receipt needs reviewer sign-off before it runs | `Custodian.replay(..., reviewer_signoff)` refuses a second distinct amendment unless a sign-off names that receipt and amendment; recorded in the ledger. `game_prediction.py` reads `claim_plan_GP.amendment-<n>.signoff.json`; `amend` warns for n ≥ 2 | `test_second_amendment_needs_reviewer_signoff`, `test_gp_second_amendment_runs_only_with_reviewer_signoff` (D15) |

Consequence (D15): these code changes alter the GAME_PREDICTION code hash, so amendment-1 no longer matches
current code; re-running that replay now needs amendment-2 **and** reviewer sign-off. The committed
amendment-1 replay (code `c822b55`) stands. Sign-off is recorded, not cryptographically verified.

## 1. `upstream_revision` fix: before/after on a nested checkout

`util.upstream_revision()` reads `raw/repo/COMMIT` first (must be 40 hex). Without it, git is used only if
`git rev-parse --show-toplevel` is the repo itself; a parent repository is refused. Used by
`build_dataset.py` and `build_confirmatory.py`. Log: `logs/confirmatory/upstream_revision_before_after.log`.

Setup: a throwaway git repo `nest/` (HEAD `c7d00e54…`) holding the upstream copy at `nest/raw/repo/` with
`COMMIT` = `46488f0f…` and the verified 2023 archives, no `.git`.

| Case | Code | `upstream_revision` recorded | Table hashes |
|---|---|---|---|
| nested, COMMIT present | **before** (`5604d36`, build_dataset `d05aa567`) | `c7d00e54…` (the **parent** repo, wrong) | 7/7 match evidence |
| nested, COMMIT present | **after** (`c05f540`, build_dataset `cf5e56d0`) | `46488f0f…` (upstream, correct) | 7/7 match evidence |
| nested, COMMIT removed | before | would record `c7d00e54…` | — |
| nested, COMMIT removed | after | **refused**: "no COMMIT file and git resolves to a PARENT repository" | — |

Unit tests: `tests/test_upstream_revision.py` (4).

## 2. Confirmatory season sealed: 2024-25 regular season

**Download and verification** (2026-11-07T17:32:23Z, `raw.githubusercontent.com`, `shufinskiy/nba_data@46488f0f`):
the upstream commit's tree was fetched with `git fetch --depth 1 --filter=blob:none` (no blobs) and each raw
download compared against its tree entry.

| Archive | Bytes | sha256 | git blob (download = tree) |
|---|---|---|---|
| `datasets/cdnnba_2024.tar.xz` | 18,886,652 | `35a82e6b29821adb22b8474dea8c51e08847d8e00690d1d5ffde7d000e0087d1` | `4ff09ac1…` = `4ff09ac1…` |
| `datasets/nbastats_2024.tar.xz` | 8,583,784 | `8f370da00ad0a6d4157921bd161d56ea32647a165d906516f2b36384a6a4989a` | `acda11af…` = `acda11af…` |

The same tree check also confirms the three 2023 archives. Pins are in `scripts/build_confirmatory.py`
(`PINNED`), and the build refuses on any difference. Archives are not committed (D9).

**Build** (`build_confirmatory.py`, code `491e09e`; log `logs/confirmatory/build_2024-25.log`; manifest committed
as `evidence/confirmatory-2024-25/season_manifest_2024-25.json`):
- 1,230 games, 686,008 events, 219,529 FGA, 0 duplicate ids, 0 exclusions, points check 0 mismatches,
  2 clock-regression steps.
- 5/5 listed neutral-site games flagged (D16; sources below). Cup final not present.
- Reconciliation against nbastats: **MATCH 1229, SCORE_MISMATCH 1**, game `0022400072`. The scores were
  deliberately **not inspected**, so no sealed outcome was opened. By rule (D19) the game is **quarantined**:
  it is kept in the seal but listed in a hashed `quarantine` table and excluded from every confirmatory
  sample. The first build (`c05f540`, `logs/confirmatory/build_2024-25_first_c05f540.log`) found the same;
  the rebuild reproduced its five table hashes exactly.
- Output: counts, hashes and reconciliation status counts only. No outcome statistic was computed or printed.
  The builder reads outcome fields mechanically to derive labels and reconcile.

**Seal** (`confirmatory.py seal`; log `logs/confirmatory/seal_2024-25.log`), appended to the live ledger
`evidence/custodian_ledger.jsonl`:
- seal `870135b5-07a2-4748-b580-d99d7cebee7c`, epoch `EPOCH-CONF-2024-25-001`, at 2026-11-07T17:52:37Z,
  1,230 games, input hash `3540dfe1…88f4`, 6 table hashes (games `46f24f26…`, events `6dccbadc…`,
  exclusions `1f3cd453…`, quarantine `1504334c…`, game_labels `f2663cc1…`, shot_labels `5f46f736…`).
- Repeating the seal is a retry. The earlier 3 ledger lines are byte-identical.
- Probes on a copy of the ledger: a shot-level id of a sealed game (`SHOT:0022400500:12`) and a bare
  sealed game id from another family are **refused**; a spent 2023-24 final game is **refused**.

## 3. Pre-registration (2023-24 development data, before any 2024-25 analysis)

Order, from commit times and ledger timestamps: design D17 in code `c05f540` (17:42:17Z) → quarantine rule
D19 (`491e09e`, 17:51:09Z) → seal (17:52:37Z) → development run → plans frozen and registered (17:54:40Z).

**Development run** (`confirmatory.py dev`, 930 development games, no spent final game read; log
`logs/confirmatory/dev_2023-24.log`; committed `dev_results_2023-24.json`, sha256 `3d343e56…`).
Exploratory, same code and parameters:

| Hypothesis | Development result (2023-24 dev games) | Rule applied (information only) |
|---|---|---|
| CONF-HA home advantage | 926 non-neutral games, home-win rate 0.5529, mean +0.0529, CI95 [0.0172, 0.0883], p 0.0015 | INSUFFICIENT_EVIDENCE: 926 < the 1,000-game minimum (2024-25 has 1,224 eligible) |
| CONF-MOM one-shot momentum | 165,710 FGA; P(make\|made) 0.4746 vs P(make\|missed) 0.4781; T −0.0035; null mean +0.0071; p 1.0 | INSUFFICIENT_EVIDENCE |
| CONF-HH hot hand (k=3) | 12,666 / 15,295 opportunities (identical to the original D11 run); T +0.0050; null mean +0.0191; p 0.998 | INSUFFICIENT_EVIDENCE |

**Frozen plans** (`evidence/confirmatory-2024-25/`; log `logs/confirmatory/freeze.log`). Re-freezing is refused.

| File | Canonical hash | Test, null, threshold, sample |
|---|---|---|
| `CONF-HA.plan.json` | `6799901f…` | mean(home_win − 0.5) over non-neutral, non-quarantined games; 7-day moving-block bootstrap, B=10000, seed 20261108; null ≤ 0; SURVIVED iff Holm p<0.05, CI lower>0, mean ≥ 0.01; NOT_SUPPORTED iff CI upper < 0.01; needs ≥1000 games and ≥5 blocks |
| `CONF-MOM.plan.json` | `f01ed8cb…` | k=1 streak difference, FGA only, ordering-resolved, non-quarantined; permutation within (player, game, shot value), B=999, seed 20261109; null exchangeability; SURVIVED iff Holm p<0.05, else INSUFFICIENT_EVIDENCE; needs ≥100000 FGA and ≥1000 per conditioning set |
| `CONF-HH.plan.json` | `46cdc536…` | as CONF-MOM with k=3, seed 20261110 |
| `family.json` | `684da846…` | Holm over 3 at α=0.05; binds seal `870135b5…`, the sealed data hashes and code hash `ebf6aaa4…` |

Registered with the seal: `register` `e71f8aa8-643d-49cd-99da-4ec1210f9bfc` (17:54:40Z). Registration is now
closed for this epoch, and only this family can reserve the sealed games, whole and with the sealed data.

## Checks

| # | Check | Result | Log |
|---|---|---|---|
| 1 | Handoff test suite (`HC_DATA=$DATA2023 python -m pytest -v -rs`) | **PASS** 93 passed, 0 skipped | `logs/confirmatory/pytest_handoff_all.log` |
| 2 | Reviewer custodian probes (`test_rv_research_custodian.py` from `8226407`) | **PASS** 10/10 | `logs/confirmatory/rv_custodian_probes.log` |
| 3 | Repo scaffold / ruff / tests | **PASS** / **PASS** / **PASS** 44 | `logs/confirmatory/{check_scaffold,ruff,pytest_repo}.log` |
| 4 | 2023-24 rebuild with changed `canonical.py`/`build_dataset.py` | **PASS** 7/7 table hashes = evidence | `upstream_revision_before_after.log` |
| 5 | Upstream-revision before/after | **PASS** (table above) | same |
| 6 | 2024-25 archives verified | **PASS** sha256/bytes/git blob | `build_2024-25.log` |
| 7 | 2024-25 build deterministic | **PASS** 5 shared table hashes identical across two builds | both build logs |
| 8 | Seal, idempotent retry, refusal probes | **PASS** | `seal_2024-25.log` |
| 9 | Freeze, re-freeze refused, readiness | **PASS** | `freeze.log`, `readiness.log` |
| 10 | Confirmatory final on 2024-25 | **NOT_RUN by instruction (D18)** | — |
| 11 | Confirmatory final code path | **PASS** on a temporary ledger over 62 development games (`test_end_to_end_seal_freeze_final_on_temporary_ledger`: reserve → spend, retry, quarantine exclusion) | `pytest_handoff_all.log` |
| 12 | Review by someone other than the author | **NOT_RUN** | — |

Defects found and fixed during this work, before any freeze:
- `canonical_record_id` refused valid EVENT-style ids (`nba:<game>:<event>:r<rev>`). Fixed in `c05f540`, test added.
- Adding the `quarantine` table changed the default table list of the GAME_PREDICTION data guard. Caught by
  4 failing tests and fixed in `491e09e` (default pinned to the 2023-24 build's tables).
- Two of my new tests had wrong expectations (synthetic timestamp formats; a hand-counted streak value). The tests
  were corrected; the code was right.
- The approximate times in D14–D19 were later than the actual commit times. Erratum D20 is appended; entries
  are not edited.

## Open / for Max

- **Quarantined game `0022400072`:** the mismatch is unexamined by design. Someone not running the claims
  could inspect it; the confirmatory samples exclude it either way.
- **Data custody:** the 2024-25 build lives in this ephemeral container. The demo machine must rebuild it
  (`build_confirmatory.py`, ~1 min). The seal accepts only identical bytes.
- **Pseudo-out-of-sample:** 2024-25 outcomes are public and may be memorised by LLM roles. This is labelled
  in every output.
- Neutral-site sources (D16): [NBA Mexico City Game 2024](https://pr.nba.com/heat-wizards-nba-mexico-city-game-2024),
  [NBA Paris Games 2025](https://www.nba.com/news/what-to-know-as-spurs-pacers-meet-in-nba-paris-games-2025),
  [2024 NBA Cup semifinals](https://olympics.com/en/news/nba-cup-2024-recap-giannis-antetokounmpo-leads-bucks-final-shai-gilgeous-alexander-thunder).
- Still open: BALLDONTLIE independent cross-check (no key), OS-level custodian isolation, and the R-001 bundle
  deliverables.
