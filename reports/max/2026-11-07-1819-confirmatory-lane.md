# Max report: merge of Research 2d277d4 and the confirmatory lane (dry run only)

Written 2026-11-07 18:19 UTC on branch `max/integrate-r001-e001`.
- Code commit: `ed4f968`. Merge commit: `0f0ada5`.
- Machine: Windows 11 Pro, Python 3.12.10, `uv run --frozen`.
- Raw logs: `logs/2026-11-07-confirmatory-lane/`.

## Merges since the 1805 report

| Commit | What |
|---|---|
| `0f0ada5` | Merged `research/r001-guard-fixes@2d277d4` **unchanged**, on the user's instruction. It seals 2024-25 and registers CONF-HA, CONF-MOM and CONF-HH. No conflicts. `handoff/**` and `reports/research/**` are identical to `2d277d4`. **`c05f540..2d277d4` has not been reviewed yet**: the reviewer's replay covered `dfb5d64` only. |

The earlier merges of `dfb5d64` and `review/independent-tests@5d3261e`, and their suite counts, are in `2026-11-07-1805-merges-and-agent-loop-fixes.md`.

## What was built

**How a proposal is routed.** When the question maps to `CONF-HA`, `CONF-MOM` or `CONF-HH`, the Referee does not run Max's attacks. It hands the claim to `heatcheck/agents/confirmatory.py` (`ConfirmatoryLane`).
- The mapping catalogue and the strict JSON-schema enum now include the three ids, with the claim text read from Research's frozen plans.
- The keyword stand-in maps "home court / home team(s) / home advantage" to `CONF-HA`.
- `DeterministicJone` does not pick confirmatory claims; only an explicit mapping does.

**Dry run (the default).** It reads only. It does not import Research's custodian, runs no test, reserves nothing, and writes to neither ledger. It checks:

| Check | Passes when |
|---|---|
| `family_manifest` | `family.json` matches its own hash |
| `family_hypotheses` | the family contains exactly the three ids |
| `plan:<id>` (×3) | the plan matches its own hash, that hash equals the family's entry, and the id and epoch agree |
| `research_code` | the code hash recomputed over the family's 9 `code_files` equals the frozen `code_hash` (same algorithm as Research's `code_hash()`) |
| `seal` | there is exactly one seal for the epoch, and its seal_id, input_hash, data_hashes and game count equal the family's |
| `registration` | there is exactly one registration for the epoch, with the family hash, code hash, family id and seal id |
| `exposure` | the epoch has no reservation (`UNRUN`), or is reserved, spent and has a result (`FINAL_DONE`) |
| `sealed_data` | given a data dir, Research's own `store.logical_table_hashes` (run in a subprocess) equals the sealed hashes. Without a data dir: `NOT_CHECKED` |
| `platform` | `fcntl` exists. Research's custodian needs it, so `final` cannot run on Windows |

`ready` is true only when every check is PASS.

**Final mode.** Not run, and not reachable from the dialogue server or CLI.
- It needs `mode="final"`, a named `authorised_by`, and a dry run with every check PASS.
- It then runs `python -I scripts/confirmatory.py final <data> <evidence> --authorised-by <name>`.
- It verifies `final_result.json` against the frozen family: lane, phase, family hash, plan hashes, code hash, sealed data hashes, epoch, all three decisions present, and the receipt reserved and spent in the custodian ledger.
- It writes **one entry per hypothesis** with `lane: CONFIRMATORY`. One family run covers all three because Holm is applied across them.
- The entry binds:
  - the plan and its hash, and the family (hash, multiplicity, seal);
  - the data hashes and input hash;
  - the custodian receipt and its history;
  - the authoriser;
  - Max's code hash and Research's `code_hash`;
  - the result file's sha256;
  - Research's result, decision, reason and Holm p, and its caveats as limits.
- If the run has already been done and verified, a later question reuses the existing entries: there is no rerun and no duplicate.

**Development lane.** Entries written by `run_once` now carry `lane: DEVELOPMENT`.
- Already committed ledgers are not rewritten: entries without a lane field are all 2023-24 development results.
- Adding the field changes the evidence ids of new development entries.

**Dialogue.** `/api/dialogue` responses now include `lane`.
- A confirmatory question in dry-run mode returns `verdict: null`, `evidence_record_id: null`, `confirmatory_status` and the dry-run checks.
- The Ref uses a fixed template: "… Its single final test has not been run, so there is no verdict yet. It runs once, recorded, after the reviewer verifies the seal. Dry run: plans, code and seal match; the sealed data were not checked on this machine."
- In final mode, the Ref and its number guard work from the confirmatory entry. A test shows an invented count is rejected.

**Why the dry run is not in Research's script.** `scripts/confirmatory.py` is one of the files covered by the frozen `code_hash`. Adding a `--dry-run` flag there would make the registration refuse the final run.

## Dry run on the committed evidence

From `logs/2026-11-07-confirmatory-lane/dry_run_committed_evidence.json`:

| Check | Status |
|---|---|
| family_manifest (`684da846…e1f9e0`) | PASS |
| family_hypotheses | PASS |
| plan:CONF-HA `6799901f…dd13`, plan:CONF-MOM `f01ed8cb…4503`, plan:CONF-HH `46cdc536…a8e3` | PASS ×3 |
| research_code: recomputed `ebf6aaa4…f09e` = frozen | PASS |
| seal `870135b5…`, 1230 games | PASS |
| registration | PASS |
| exposure: 0 reservations on `EPOCH-CONF-2024-25-001` | PASS (`UNRUN`) |
| sealed_data | **NOT_CHECKED**: there is no 2024-25 build on this machine |
| platform | **FAIL**: Windows has no `fcntl` |

`ready: false`, as intended on this machine. The evidence directory was byte-identical before and after (tested).

## Checks

| Check | Result |
|---|---|
| New tests `tests/integration/test_confirmatory_lane.py` | **PASS** 20 |
| Full suite at `ed4f968` | **1 failed, 399 passed, 29 skipped, 16 xfailed** (155 s). The one failure is the same unpassable `test_rv_al5_loop_accepts_minimal_challenger` as before. |
| Reviewer agent-loop suite with my guard | **30 passed, 1 failed (AL5)**, unchanged |
| ruff | **PASS** |
| Research's `final` on the real 2024-25 seal | **NOT_RUN by instruction** |
| End-to-end final through Research's real script | **NOT_RUN**. It needs Linux and the rebuilt 2024-25 data. Research's own temporary-ledger end-to-end test covers their side (their report, check 11). |

The new tests cover:
- the dry run on the committed evidence, including that it writes nothing;
- `ready` only when every check passes;
- an edited plan;
- a re-hashed, self-consistent plan that is not in the family;
- edited Research code;
- a tampered seal;
- a missing registration;
- data that differ from the seal;
- an existing reservation;
- dry-run mode never calling the runner;
- final mode refusing without an authoriser, when not ready, and for a non-confirmatory id;
- recording all three entries once, with reuse and no rerun;
- results whose family, code or data hash or lane do not match being refused with nothing written;
- a result with no custodian spend being refused;
- the mapping enum;
- the dialogue dry-run and final turns;
- the `DEVELOPMENT` lane.

**Limit of these tests.** The final-mode tests use an injected runner that writes a **synthetic** result file, labelled as such in the test. They test Max's verification and recording code, not Research's statistics.

## To run the final step later (not done)

1. The reviewer verifies the seal and `c05f540..2d277d4`.
2. On Linux, rebuild 2024-25 with `build_confirmatory.py`. Run the dry run with that data dir; every check must be PASS, including `sealed_data` and `platform`.
3. On the user's word, construct `ConfirmatoryLane(mode="final", authorised_by=<name>, data=<dir>)` and ask a confirmatory question once, recorded. Commit the custodian ledger, `final_result.json` and the evidence ledger.

## Open items

- `c05f540..2d277d4` is merged but not reviewed.
- Experience's UI does not show `lane` or the dry-run checks yet.
- The reviewer's AL5 test needs replacing, as before.
- A live LLM retest is still NOT_RUN: there is no new budget.
