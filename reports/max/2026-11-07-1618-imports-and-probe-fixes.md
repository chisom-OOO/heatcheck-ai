# Max report: imports and reviewer probe fixes

Written 2026-11-07 16:18 UTC. Branch `max/integrate-r001-e001`. Code state reported:
`fd5d6a3`. This report is committed on top of it; the push hash is given in the commit
that adds this file. Machine: Windows 11 Pro, Python 3.12.10 via `uv run --frozen`.

## 1. Imports (pushed)

| Commit | What | Verification |
|---|---|---|
| `5ba8501` | Research ZIP (sha256 `561cc693…86df`) → `incoming/research-20261107/`: 41 files | Committed blob sha256 equals ZIP member sha256 for 41 of 41 |
| `7d7bb86` | Experience ZIP (sha256 `c646c751…a537a90`) → `incoming/experience-20261107/`: 71 files | 71 of 71 equal |

- The three upstream archives (45.8 MB, redistribution rights unverified) are **omitted**. They
  are listed with sha256 in `incoming/research-20261107.IMPORT.json` and kept locally under the
  git-ignored `data/raw/research-20261107/`.
- `incoming/**` is exempt from EOL conversion (`.gitattributes`) and from ruff.
- Tool used: `tools/import_handoff.py`. Nothing from either ZIP has been reviewed or accepted.

## 2. Reviewer branch

`46ac1dc` merges `origin/review/independent-tests@2f36643` with no changes to its files.
Baseline on this machine at `46ac1dc`: **25 failed, 56 passed, 9 skipped**. That equals the
reviewer's Linux result. Full log: `logs/2026-11-07-probes/baseline_review_at_46ac1dc.txt`.

## 3. Format change

`586bcb3`:
- `GAME.scheduled_tip_utc` is now nullable.
- An optional key `observed_tip_utc` is added, also nullable. It is the actual tip seen in
  play-by-play and is never usable as a pre-tip cutoff.
- At least one of the two tip times must be set.
- The reference bundle bytes are unchanged.
- New contract test: `test_game_tip_times_scheduled_or_observed`.

## 4. Probe fixes, one commit each

| Probe | Commit | Probe result after |
|---|---|---|
| RV-G1 event team not in game | `e4c5e8d` | PASS |
| RV-G2 feature row targets another game's shot | `bd06aec` | PASS |
| RV-L3 cutoff later than its own shot | `02eee62` | PASS |
| RV-L4 target shot's own EVENT among inputs | `8938bb7` | PASS |
| RV-O1 final score home/away vs play-by-play | `74d3e19` | PASS |
| RV-O2 SHOT_MADE label contradicts EVENT | `4179616` | PASS |
| RV-U9 manifest `created_utc` validated | `eef9b6a` | PASS |
| RV-U8 quote raw snapshot outside fetch window | `b6a8c1f` | Validator check added and reference fixture corrected; the probe itself now **FAILS** (see §6) |

Notes on the fixes:
- **RV-G2:** shot target ids are now required to be `<game_id>:shot:<provider_event_id>`. The
  reviewer's own support code already uses this convention.
- **RV-L3 and RV-O2:** these checks apply only when the target id resolves to a shot EVENT.
  Unresolvable targets are RV-L5, which is deferred.
- **RV-O4** (FINAL tie) now passes only **incidentally**: a 2–2 label contradicts the 2–0
  events, so the RV-O1 check refuses it. A tied final score with no events in the bundle is
  still accepted. RV-O4 is not fixed as its own rule.

Deferrals and the freshness threshold are recorded in `docs/DECISIONS.md` (`e768e3b`):
- **Deferred market probes:** O5, O7, U2 (×3), U3, U7, S1, S2, T2, T3, T4.
- **Unfixed non-market probes outside the requested list:** L5, L6, G3, O3.
- **Freshness threshold:** historical comparison, quote received at or before the cutoff and no
  more than 600 s before it; live display, no more than 60 s old.

`fd5d6a3`: a ruff import-spacing fix in `eligibility.py`.

## 5. Checks at fd5d6a3 (complete raw output in `logs/2026-11-07-probes/`)

| Check | Command | Result |
|---|---|---|
| Reference bundle validates | `uv run --frozen python -m heatcheck.contracts.bundle tests/fixtures/contracts/syn_reference_bundle` | **PASS**, `records_sha256=faa3d335…7465` |
| Reference bundle reproducible | `uv run --frozen python tools/make_reference_bundle.py --check` | **PASS** |
| Lint | `uv run --frozen ruff check .` | **PASS** |
| Scaffold | `uv run --frozen python tools/check_scaffold.py` | **PASS** (preparation only) |
| Contract tests | part of `pytest tests` | **PASS**, 45 of 45 |
| Reviewer suite | `uv run --frozen pytest -q tests -rA -p no:cacheprovider` | **FAIL**: 18 failed, 108 passed, 9 skipped (all 18 listed in `pytest_all.txt`) |

The 18 failures break down as:
- **10 deferred market probes:** 12 test cases, because U2 runs ×3.
- **4 unfixed non-market probes outside the list:** L5, L6, G3, O3.
- **2 reviewer tests invalidated by the RV-U8 fix** (§6).

The 9 skips are reviewer candidate tests, which report NOT_RUN because no candidate bundle or
builder is configured yet.

## 6. Reviewer tests that need a reviewer decision (not modified by Max)

- **`test_rv_u8_raw_snapshot_time_outside_fetch_window_rejected`.** It asserts, as a
  precondition, the old defective fixture value (`retrieved_utc == "2026-11-07T12:00:00Z"`) and
  then expects the unmutated reference bundle to be rejected. No correct fix can satisfy it:
  - If the fixture is fixed, the precondition fails.
  - If the fixture is left defective while the validator rejects it, every reviewer test that
    loads the reference bundle fails.
- **`test_rv_checks_selftest.py::test_experience_check_fires[outside fetch]`.** The validator
  now rejects that mutated bundle at load, before the reviewer's semantic check runs.

## 7. Unexecuted

- **R-001 bridge:** not yet built. The reviewer pre-shot harness has not yet run against
  Research's builder (5 skips).
- **Experience `syn:` bundle:** not yet built.
- **Agent loop:** does not exist yet.
- **Research custodian tests (5) and final replay:** NOT_RUN. They need Linux (`fcntl`). No WSL
  is installed and the Docker engine is not running.
- **BALLDONTLIE reconciliation:** NOT_RUN, waiting for the key.
- **Experience end-to-end and browser tests:** NOT_RUN.
- **Gates:** all ACCEPTANCE.json gates G01–G18 remain NOT_RUN.
