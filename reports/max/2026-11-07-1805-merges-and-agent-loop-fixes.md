# Max report: merges (review, Experience, Research), agent-loop fixes RV-AL1/2/4/5/6, dialogue under the new rules

Written 2026-11-07 18:05 UTC on branch `max/integrate-r001-e001`. Raw logs:
- `logs/2026-11-07-review-merge/`
- `logs/2026-11-07-experience-merge/`
- `logs/2026-11-07-al-fixes/`
- `logs/2026-11-07-research-merge/`

## Step by step

| # | Commit | What |
|---|---|---|
| 1 | `e039802` | Recorded the user's decisions on the reviewer's §7 questions: RV-R1 refusal; **free throws out of scope** (SHOT_ASSOCIATION = field goals only, prior attempts/makes count FGs only; `docs/tasks/RESEARCH.md` amended); Experience allowlist rule; the 16 deferred probes. |
| 2 | `a7e3b47` | Merged `origin/review/independent-tests@870f3fb` **unchanged**: 16 deferred probes marked xfail(strict), plus the agent-loop review. |
| 3 | `60b5b10` | **Reverted** `954c0d5` (view format / `fromRecord()`), which the user dropped. |
| 4 | `89d3868` | Merged `origin/experience/referee-ui-integrate@496901c` **unchanged**. No conflicts. `apps/web/web/{referee.js,app.js}` and `tests/referee.test.mjs` are byte-identical to `496901c`, and `git diff 496901c HEAD -- apps heatcheck/markets tests/experience reports/experience` is empty. |
| 5 | `b2e6537` | **RV-AL6** strict parsing and **RV-AL4/AL5** Referee-enforced attack set (below). |
| 6 | `c8831e6` | **RV-AL1/AL2** hash-chained ledger and `EvidenceLedger.open_readonly()` (below). |
| 7 | `7c6c50b` | Dialogue under the new rules (below). |
| 8 | `099cb5a` | 18:00 decisions recorded. The 1705 report's wording is corrected: the status is `UNSUPPORTED`, not "NOT_EXECUTABLE". The 1737 view-format report is marked withdrawn. |
| 9 | `0e6c4e6` | Merged **`dfb5d64`** (Research guard fixes), **after** the reviewer confirmed them (`reports/review/2026-11-07-1733-research-guard-fixes.md`: RV-R1 and RV-R2 FIXED and verified; the replay reproduces receipt `3e238d2d`). It was merged at that exact commit, not at the branch head; `handoff/**` and `reports/research/**` equal `dfb5d64`. The conflicts in `pyproject.toml` and `.gitattributes` were additive: each side excluded its own handoff directory. |
| 10 | `2367d2f` | Merged `origin/review/independent-tests@5d3261e` **unchanged**: the reviewer's replay report of the guard fixes. |
| 11 | `7a2fa28` | **Fix of my own error in step 9.** The conflict markers were committed in the merge. My resolver ran through `uv`, which could not parse the conflicted `pyproject.toml`, and the commit step was chained with `;` instead of `&&`. The commit applies the union resolution by hand. It was caught before any push; no pushed commit contains markers. |

Gaps between the user's instructions and what was done:
- I first started the xfail change myself, against `review/independent-tests` in a worktree.
  The user corrected this (it was meant for the reviewer). The edit was discarded unpushed
  and the worktree removed.
- The view-format work (17:37 report) was built and then reverted, per the user.

## Agent-loop findings

**RV-AL6: strict parsing** (`heatcheck/agents/roles.py`).
- `parse_proposal` uses strict JSON: duplicate keys and NaN are rejected.
- The object must be exactly `{claim_id, rationale}`.
- `claim_id` must be `null` or a string that is exactly a registered id: no case folding, no
  trimming, no lists.
- `rationale` must be a string of at most 500 characters. It used to be silently truncated;
  now it is refused.
- New `parse_selection`: exactly `{"attacks": [...]}`.
- `validate_selection` refuses non-lists, non-strings, duplicates and unregistered ids, and
  no longer de-duplicates silently.
- The dialogue's `parse_mapping` is equally strict. A turn's displayed `claim_id` and
  `verdict` are read from the evidence entry; a mismatch with the mapping raises instead of
  displaying.

**RV-AL4/AL5: the Referee enforces the attack set.**
- `required_attacks(claim, view)` is deterministic: every mandatory attack, plus every
  optional attack whose prerequisites the view meets.
- The loop runs `required ∪ Challenger additions`. **A Challenger can add, never remove.**
- The evidence identity records `selected_attacks` (what the Challenger chose),
  `referee_required_attacks`, `omitted_required_attacks` and `attacks_run`.
- `decide(..., required=)`: optional attacks can only overturn SURVIVED_PROTOCOL, so a
  missing required attack yields INSUFFICIENT_EVIDENCE instead of SURVIVED. Without a
  required set, all registered attacks are required.

**RV-AL1/AL2: hash chain** (`heatcheck/ledger/evidence.py`).
- Each line adds `prev_chain_hash` and `chain_hash = sha256(prev:entry_hash)`; the first
  line's prev is 64 zeros.
- Every read verifies the chain. Edited-and-rehashed, deleted, inserted, reordered and
  duplicated lines all fail.
- `head()` returns the chain head.
- **Limits (documented):** the chain alone cannot see lines removed from the end, or a
  fully rebuilt chain. Comparing `head()` against a value recorded elsewhere detects those.
- Writers serialise on a `.lock` sidecar (gitignored).
- Legacy unchained lines are refused with a pointer to the migration tool.

**`EvidenceLedger.open_readonly(path)`** never creates, touches or locks anything, and its
`put()` raises. Experience's `apps/web/server/evidence.py` still works unchanged; its 75 tests
pass.

**Migration of the two committed ledgers** (`tools/migrate_ledger_chain.py`).
- It first verifies each line under the old rules, then adds **only** the two chain fields.
- The identity, `evidence_id`, `entry_hash` and `created_at_utc` are unchanged. A test checks
  this field by field against the bytes at `cb7320c`.

| File | Old sha256 | New sha256 | Head |
|---|---|---|---|
| `logs/2026-11-07-loop/evidence_real_game.jsonl` (3 lines) | `7cee6938…f612` | `a48b6d83…771d` | `5dc3341e…3fe4` |
| `logs/2026-11-07-dialogue-live/evidence_live_turn.jsonl` (1 line) | `5d3983c4…51dc` | `ee83331b…af52` | `bb3e42e2…c399` |

**Real game rerun under the new rules** (`logs/2026-11-07-al-fixes/run_loop_real_game.txt`,
fresh ledger `evidence_real_game_v2.jsonl`, head `00505921…efcec`):
- The decisions are unchanged: HH-K3 INSUFFICIENT_EVIDENCE (n=14/18 < 30), HH-K2
  NOT_SUPPORTED (p=0.2390), GP-REST BLOCKED.
- The evidence ids are new (`8c66d64b…`, `f2277b9f…`, `4004ce39…`), because the identity now
  records the required and run attack sets.
- Required attacks for HH-K3 and HH-K2 are all five, with none omitted.

## Dialogue under the new rules (`7c6c50b`)

- **LLM Challenger is add-only.** Under heatcheck-registry/1 every applicable attack is
  already required, so nothing is addable and **the model is not called**. Each turn makes 3
  calls instead of 4 and saves about 0.5–1.5 s. It becomes active once the registry has
  attacks that are registered but not required.
- **Ref guard hardened** against the reviewer's staged smuggling suite. Refused unless the
  record supports them:
  - unit suffixes, "%" and "times", must match the record;
  - scientific notation;
  - non-ASCII digits;
  - fraction words, unless the verdict reason or claim statement uses them;
  - spelled-out numbers above ten (a style rule: quote counts as digits from the record).
- `ref_guard_allows(text, entry)` is the reviewer's interface.
- **What the guard cannot do:** it checks numbers, not what they refer to. "14 of them went
  in" in digits passes (14 is in the record, as attempts, not makes). The spelled form is
  caught only by the style rule.

## Checks

| Check | Result |
|---|---|
| Full suite at `7a2fa28` (`uv run --frozen python -m pytest -q`) | **1 failed, 379 passed, 29 skipped, 16 xfailed** (159 s) |
| The one failure | `test_rv_al5_loop_accepts_minimal_challenger`. **It cannot pass as written.** After `run_once` it calls `pytest.fail(...)` unconditionally, so it fails whether `run_once` returns or raises. The behaviour it targets is fixed: the omitted attacks are run and recorded. The reviewer should change it to assert this; I did not edit `tests/review/`. |
| Reviewer's agent-loop suite with my guard (`HEATCHECK_REVIEW_REF_GUARD=heatcheck.agents.dialogue:ref_guard_allows`) | **30 passed, 1 failed (AL5)**. That covers AL1, AL2, AL3, AL4, all 5 AL6 cases, AL7, both allowed texts (REF1), **all 16 smuggling cases (REF2)** and rationale laundering (REF3). |
| Experience's 20 adapter findings (`tests/review/test_rv_e001_adapter.py`) | **PASS**: all pass on `496901c`, as the user stated |
| Experience app unit tests | **PASS**: 75 OK |
| `node --test tests/referee.test.mjs` | **PASS**: 12/12. A directory-wide `node --test tests/` also picks up the browser e2e scripts, which need a server URL, and reports 1 fail. Not a regression. |
| ruff | **PASS** |
| Live provider call after these changes | **NOT_RUN** (no new budget approved) |

## Open items

- The reviewer should replace the AL5 assertion.
- Experience may change "hashes verified" to "chain verified" once their reader shows chain
  status.
- Research `c05f540..2d277d4` was not merged at this point. The user instructed the merge in
  the next message; see the next report.
