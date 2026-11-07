# Reviewer report: agent loop v1 review, xfail of deferred probes, RV-R1/R2 status

Written 2026-11-07 17:16 UTC (container clock). Role: independent reviewer. Branch
`review/independent-tests`, which merges `origin/max/integrate-r001-e001@b0ef0c6`.

**Machine:** Linux x86_64, Python 3.12 via `uv run --frozen`.

**Before starting**, I fetched all branches and read the new reports:
- `reports/max/1641-agent-loop`, `1700`/`1706-meta-api-test`, `1710-rules-update` and
  `1715-main-merge`;
- `reports/experience/1646-app-referee-ui`;
- `reports/research/1633-*` on `research/r001-fixes`.

## 1. Deferred validator probes → `xfail(strict=True)` (commit `265ea39`)

These 16 cases now carry `@deferred(...)`, with the reason quoted from `docs/DECISIONS.md`
2026-11-07 (Max):
- **Not in the user's list, also unfixed:** RV-L5, L6, G3, O3.
- **Market-related, deferred by user instruction:** RV-O5, O7, U2 ×3, U3, U7, S1, S2, T2, T3, T4.

How the marker behaves:
- `strict=True`: if a gap is fixed, the test XPASSes and fails, so the marker has to be removed.
- `raises=(AssertionError, pytest.fail.Exception)`: only the probe's own "accepted bad input"
  failure is expected. A crash or any other new problem still fails.

I demonstrated both behaviours with a throwaway test:
- `[XPASS(strict)] … FAILED` for a simulated fix;
- `KeyError … FAILED` for a simulated crash.

The 20 RV-E adapter findings are deliberately **not** marked.

## 2. Agent loop v1 (`0013e53`, report `cb7320c`), reviewed at `b0ef0c6`

### Replayed

| Check | Command | Result |
|---|---|---|
| Loop on the real game, fresh ledger | `uv run --frozen python tools/run_loop.py data/bundles/r001-nba-0022300061 --ledger <scratch>` | **PASS, cross-OS deterministic**: evidence ids `2c754d04…` (HH-K3, INSUFFICIENT_EVIDENCE), `e87dcfc7…` (HH-K2, NOT_SUPPORTED), `d2c8101c…` (GP-REST, BLOCKED) are **identical** to Max's committed Windows ledger |
| Integration tests | `uv run --frozen pytest -q tests/integration -rA` | **PASS** 14/14. `test_real_game_bundle_rebuilds_byte_identically` needs `data/processed/research-20261107`, which I linked to my verified Research build |
| Reviewer probes | `uv run --frozen pytest -q tests/review/test_rv_agent_loop.py -rs` | 6 pass, **6 FAIL** (below), 19 NOT_RUN (number guard not landed) |

### Findings

| ID | Sev. | Expected | Actual | Test |
|---|---|---|---|---|
| RV-AL1 | **High** | A ledger line whose decision is edited, with both hashes recomputed, is detected ("tampering is detected on read") | **Accepted**: HH-K2 reads SURVIVED_PROTOCOL. `evidence_id` and `entry_hash` are unkeyed content hashes, so anyone who can write the file can recompute them. A hash chain (each entry binds the previous `entry_hash`) plus an externally recorded head (e.g. in the Max report or a commit) would detect this | `test_rv_al1_*` |
| RV-AL2 | Med | Deleting a line is detected | **Accepted**: 2 entries remain and HH-K3 vanishes. The loop's `done` set is read from the ledger, so HH-K3 would then be re-run as a fresh evaluation; forking paths go unrecorded | `test_rv_al2_*` |
| RV-AL3 | **High** (once a model-backed Challenger exists) | The Referee requires every optional attack whose prerequisites hold | `decide()` checks only mandatory attacks. With identical mandatory results, adding a flagged `A-SHOT-VALUE-SELECTION` gives INSUFFICIENT_EVIDENCE, and omitting it gives **SURVIVED_PROTOCOL**. "Selects each optional attack whose prerequisites hold" is a property of the deterministic stand-in only | `test_rv_al4_*` |
| RV-AL4 | Med | `run_once` refuses a selection that omits applicable optional attacks | **Accepted**: `validate_selection` ignores the claim and the view. A mandatory-only Challenger ran without shot-value or split-half checks, and its result is recorded as normal evidence | `test_rv_al5_*` |
| RV-AL5 | Low | `parse_proposal` refuses ambiguous or ill-typed JSON | `{"claim_id":"HH-K3","claim_id":"GP-REST",…}` is **accepted as GP-REST** (plain `json.loads`; last key wins; the raw proposal is not stored). `{"claim_id":["HH-K3"]}` **crashes** with `TypeError` instead of ProposalRefused. Fix: use `records.loads_strict` and type-check | `test_rv_al6_*` (2 of 5 cases) |

Passing probes:
- Extra `params`, a case change and trailing space in `claim_id` are refused.
- A naive edit, without rehashing, is detected.
- 12 concurrent `put()`s of one identity gave 1 line in 6 of 6 runs. I could not reproduce a
  race, although `put()` holds no lock between reading and appending. That is a static
  observation only.

### Observations (no test)

- **Multiplicity:** HH-K3 and HH-K2 are evaluated on the same view, each at α = 0.05, with
  no family correction. Research used Holm for the game-prediction pair. The family-wise
  rate was not quantified: NOT_RUN.
- **Code identity is partial:** `code_identity()` hashes the 5 agent files and Research's
  `kernels.py`. It omits `heatcheck/ledger/evidence.py`,
  `heatcheck/contracts/research_bridge.py` (which builds the view) and
  `heatcheck/contracts/records.py`. This is the same pattern as RV-R4.
- The data identity is sound: `view.identity()` hashes the arrays, unlike RV-R1.

## 3. Meta model wiring and the Ref's number guard: NOT_RUN (not landed)

- Max's 1706 report states that Heater/Ref LLM wiring is NOT_RUN: `muse-spark-1.3` returned
  `content: null`.
- No number-guard code exists at `b0ef0c6`; a grep of `heatcheck/agents` and
  `heatcheck/ledger` finds none.

**Staged attack suite, ready for when it lands:** `tests/review/test_rv_agent_loop.py::test_rv_ref*`.
Set `HEATCHECK_REVIEW_REF_GUARD=module:function`, taking `(text, evidence_entry)` and
returning allowed/refused. Against the committed HH-K3 entry:
- **2 controls must pass:** n=14/18/30 and p=0.061.
- **16 smuggling attempts must be refused:**
  - invented (62.5%)
  - a sum (32 = 14+18)
  - p re-expressed (6.1%, 93.9%)
  - a sign flip
  - another record's number (0.239)
  - digits inside the evidence hash (754)
  - the claim-id digit (3)
  - spelled-out ("Fourteen")
  - scientific notation, leading dot, rounding (0.07)
  - a thousands separator (1,230)
  - Arabic-Indic and full-width digits
  - "Half"
- **Laundering test:** a number that appears only in Jone's free-text rationale must not count
  as being "in the evidence record". `test_rv_al7` shows that the rationale is stored verbatim
  in the evidence identity, so a guard that scans the whole record would be fooled.

## 4. RV-R1 / RV-R2: not yet fixed, re-verification pending

`research/r001-fixes@5604d36` (report 16:33, before my 16:42 report) does not change the
custodian or the final step:
- `custodian.py` sha256 is `66074d69…`, the same as the import;
- `game_prediction.py` is `2565b42e…`, the same as the import.

Its fix for RV-R3 is noted: the recorded `build_dataset.py` `a933df4e…` was reconstructed
exactly. When Research pushes a fix, I will rerun:
- RV-R2: `HEATCHECK_REVIEW_RESEARCH_SRC=<fix>/src pytest tests/review/incoming/test_rv_research_custodian.py`;
- RV-R1: the label-flip replay from my 1642 report, §2.

## 5. Suite at this report's commit

- `uv run --frozen pytest -q tests`: 26 failed, 228 passed, 30 skipped, 16 xfailed.
  - The 26 failures are the 20 RV-E adapter findings and the 6 RV-AL findings.
  - The 30 skips are the 19 staged guard tests plus candidate and env-gated tests (NOT_RUN).
- `uv run --frozen ruff check .`: PASS.

## 6. Questions

1. **Max (RV-AL1, RV-AL2):** add a hash chain and record the ledger head hash in each report?
2. **Max (RV-AL3, RV-AL4):** should the Referee or `validate_selection` require every optional
   attack whose prerequisites hold before a model-backed Challenger is wired?
3. **Max:** which function will the Ref number guard expose, so I can point
   `HEATCHECK_REVIEW_REF_GUARD` at it?
