# Research status: rest verdict explained, write-once replay results, 2024-25 rebuild steps, seal binding tested

| | |
|---|---|
| Branch | `research/r001-guard-fixes` |
| Code under test | `e7e885763cc1f787d451b76afc7dafe3d1574a34` (write-once results + seal-binding tests) |
| Report commit | the commit containing this file (hash given to Max in chat) |
| Confirmatory step | **NOT RUN.** No reservation on `EPOCH-CONF-2024-25-001`; frozen family code hash `ebf6aaa4…` still matches the code (confirmatory code files were not touched). |
| Reviewer | Confirmed the RV-R1/R2 guard fixes on its own build (input hash `dbb4d3e4…`). This change is not yet reviewed. |

## 1. Why rest/back-to-back is INSUFFICIENT_EVIDENCE with Holm p 0.048995

H1 (C1 rest/back-to-back vs B1 Elo) is INSUFFICIENT_EVIDENCE because the registered D10 rule requires all
three of "Holm-adjusted p < 0.05 **AND** CI95 lower bound > 0 **AND** mean ≥ 0.002 nats" for
SURVIVED_PROTOCOL. Its CI95 lower bound is **−0.00433**, so it fails the second condition even though
Holm p = 0.048995 < 0.05. It is not NOT_SUPPORTED either, because that needs the CI95 upper bound
(+0.0438) below the 0.002 floor; every other case is INSUFFICIENT_EVIDENCE (D10, `game_prediction.py final()`).

## 2. Write-once replay results

`game_prediction.py` now writes every final/replay result through `_write_once()`. The first run creates the
file; any rerun writes `<name>.rerun-<n>.json` (smallest free n). Exclusive create means an existing result,
including its timestamp, is never rewritten.

| Check | Result |
|---|---|
| `test_write_once_never_overwrites` (unit: first, rerun-1, rerun-2; first file unchanged) | **PASS** |
| `test_gp_replay_rerun_keeps_first_result_file` (real data, evidence copy, amendment-2 with sign-off: run twice → first file byte-identical, rerun in `…AMEND-2.rerun-1.json` with `retry: true` and identical decisions; committed AMEND-1 result untouched) | **PASS** |

**Known limitation, not fixed on purpose:** `confirmatory.py final` still writes `final_result.json` with a
plain write, so a rerun (a custodian retry) would rewrite it. Fixing that edits `scripts/confirmatory.py`,
which is in the frozen family's code hash, and D18 makes a frozen family unamendable: `final` would then
refuse. Mitigation for the demo: run `final` once and copy/commit `final_result.json` immediately. A rerun is
a retry of the same receipt with the same data and decisions, but its `created_at_utc` would change.

## 3. Rebuild 2024-25 on a fresh machine

**Requirements:** Linux or macOS (or WSL on Windows), git, curl, `sha256sum` (macOS: `shasum -a 256`), Python 3.13
and `uv` (or pip). Network access to github.com and raw.githubusercontent.com. Disk ~0.7 GB.
**Windows note:** the build itself is plain Python, but `confirmatory.py final` and the custodian use `fcntl`,
which is not available on native Windows. Run the demo under Linux, macOS or WSL.

The complete script is committed at `reports/research/logs/rebuild/rebuild_2024-25.sh`. It was **executed from
scratch** in an empty directory with a fresh clone, fresh venv and fresh downloads
(`logs/rebuild/fresh_rebuild_run.log`, 2026-11-07T20:12:07Z → 20:14:04Z). Steps:

1. Clone the code at the exact commit:

```bash
git clone --branch research/r001-guard-fixes https://github.com/chisom-OOO/heatcheck-ai repo
```

```bash
git -C repo checkout e7e885763cc1f787d451b76afc7dafe3d1574a34
```

2. Create the pinned environment:

```bash
uv venv -p 3.13 venv
```

```bash
uv pip install -p venv/bin/python numpy==2.5.3 pandas==3.0.5 scipy==1.18.1 scikit-learn==1.9.1 pytest
```

3. Download the two pinned archives into `up/datasets/` and write the upstream commit:

```bash
mkdir -p up/datasets up/extracted && echo 46488f0f8e1cab58fc1256511ea808166a443a15 > up/COMMIT
```

```bash
curl -sSfL -o up/datasets/cdnnba_2024.tar.xz https://raw.githubusercontent.com/shufinskiy/nba_data/46488f0f8e1cab58fc1256511ea808166a443a15/datasets/cdnnba_2024.tar.xz
```

```bash
curl -sSfL -o up/datasets/nbastats_2024.tar.xz https://raw.githubusercontent.com/shufinskiy/nba_data/46488f0f8e1cab58fc1256511ea808166a443a15/datasets/nbastats_2024.tar.xz
```

   Expected sha256 (the build also checks byte count and upstream git blob id, and refuses on any difference):

   | File | sha256 | Bytes |
   |---|---|---|
   | `cdnnba_2024.tar.xz` | `35a82e6b29821adb22b8474dea8c51e08847d8e00690d1d5ffde7d000e0087d1` | 18,886,652 |
   | `nbastats_2024.tar.xz` | `8f370da00ad0a6d4157921bd161d56ea32647a165d906516f2b36384a6a4989a` | 8,583,784 |

4. Extract both archives:

```bash
for f in up/datasets/*.tar.xz; do tar -xJf "$f" -C up/extracted; done
```

5. Build. It prints counts and hashes only, and writes `data2024/`:

```bash
venv/bin/python -I repo/handoff/research-20261107/scripts/build_confirmatory.py up data2024 up/extracted
```

6. Compare with the frozen seal (step 5 of the script). It reads hashes only and reserves nothing.

7. Optional: run the seal-binding tests against this build:

```bash
cd repo/handoff/research-20261107 && HC_DATA_2024=../../../data2024 ../../../venv/bin/python -m pytest -q -rs tests/test_confirmatory.py -k real_2024
```

**Expected table hashes** (= `sealed_data_hashes` in `evidence/confirmatory-2024-25/family.json`; seal input hash
`3540dfe18eca85697e0c3ec6f0f7f35de2b84368e39ddf4d5f769f1556c388f4`):

| Table | Logical hash |
|---|---|
| games | `46f24f26360809d6a2f5f89881988a543f23df0d1ef8648acef21fb9d860b193` |
| events | `6dccbadc16cb7462463b04e2b6a092776240ee972727e614319a8be7e44fbada` |
| exclusions | `1f3cd453680b613d1856d0f1eb5619d38cf876b0bda601d50283ed5b9ff92eeb` |
| quarantine | `1504334cb3991403bce0bf28ee4a48fe9a9320fd8b0efc9b3f663e3d680151ca` |
| game_labels | `f2663cc1caa8aaf0cb2952cecab8d9746ebbe1d0dc665667c4c4b71dc047edf2` |
| shot_labels | `5f46f73629d15065e615b211218baf5d4b03386cb0c0e72447dd74ba9fd3670f` |

Expected build counts: 1,230 games, 686,008 events, 219,529 FGA, 0 exclusions, 5 neutral sites flagged,
reconciliation `MATCH 1229, SCORE_MISMATCH 1`, quarantined `0022400072`.

**Measured time** (4 CPUs, Linux x86_64, warm uv package cache): total **1 min 57 s**.

| Step | Time |
|---|---|
| clone | 1 s |
| venv + install | 1 s (cached; a cold install adds the package downloads) |
| downloads | 2 s |
| extraction | 2 s |
| build | **58 s** |
| seal comparison | 18 s |
| tests | 35 s |

Result of the fresh run: all six tables **MATCH**, `SEAL MATCH`; both real-2024 tests passed.

The confirmatory command itself, for the demo only and **not run**:

```bash
venv/bin/python -I repo/handoff/research-20261107/scripts/confirmatory.py final data2024 repo/handoff/research-20261107/evidence --authorised-by <name>
```

## 4. Confirmatory refuses unless the data match the seal exactly

`confirmatory.py final` recomputes all six table hashes from the SQLite files and refuses before reserving if
any differs from the family's `sealed_data_hashes`. The custodian also refuses a reservation whose input hash
differs from the seal. Tests in `tests/test_confirmatory.py`:

| Test | What it does | Result |
|---|---|---|
| `test_final_refuses_unless_data_match_the_seal_exactly[...]` × 7 | Temporary seal over 62 development games; tamper one table at a time (games tricode, one event's shot distance, a duplicated event row, an added exclusion, an emptied quarantine, one game label, one shot label) → `Refused: ... sealed data`; ledger byte-identical; no `final_result.json` | **PASS** 7/7 |
| `test_real_2024_build_matches_frozen_seal` | Real 2024-25 build hashes == frozen family's sealed hashes | **PASS** (this container's build, and the fresh rebuild) |
| `test_real_2024_tampered_copy_is_refused_on_a_ledger_copy` | REAL frozen family on a **copy** of `evidence/`; one game label flipped in a copy of the 2024-25 data → refused before reserve; copied ledger byte-identical; no result | **PASS** |
| Positive control: `test_end_to_end_seal_freeze_final_on_temporary_ledger` | Untampered data on the temporary seal runs through reserve → spend | **PASS** |

## Checks

| # | Check | Command | Result | Log |
|---|---|---|---|---|
| 1 | Handoff suite incl. real-2024 tests | `HC_DATA=<2023-24 build> HC_DATA_2024=<2024-25 build> python -m pytest -v -rs` | **PASS** 104 passed, 0 skipped | `logs/rebuild/pytest_handoff_all.log` |
| 2 | Frozen confirmatory code hash unchanged | `code_hash()` vs `family.json` | **PASS** `ebf6aaa4…` | (in commit `e7e8857` message and this report) |
| 3 | Fresh-machine rebuild | `bash logs/rebuild/rebuild_2024-25.sh` | **PASS** SEAL MATCH 6/6, 2 tests passed | `logs/rebuild/fresh_rebuild_run.log` |
| 4 | Confirmatory final on 2024-25 | — | **NOT_RUN by instruction** | — |
| 5 | Rebuild on macOS / WSL / cold package cache | — | **NOT_RUN** (Linux only, warm cache) | — |
| 6 | Independent review of this change | — | **NOT_RUN** | — |

Waiting for instructions. No confirmatory step will be run until the user says so.
