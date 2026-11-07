# Decisions

- 7 November: proposed name HeatCheck, repo slug heatcheck-ai; user creates remote.
- Statistical arbitrage and the general-market scanner removed by user instruction.
- Retain optional read-only NBA forecast/market-quote comparisons.
- Keep original BreakPoint repository separate; new scaffold has no inherited app/P0 code.
- One Max + two Pro coding sessions on three computers; no automatic remote messaging configured.
- No commits before new repository exists; no push or remote changes yet.

- User supplied heatcheck-ai URL; verified empty origin, initial local checkpoint now authorised. Trailing sentence punctuation omitted from verified URL. Old working tree/history archived before removal; no history concealment or application import.
- 7 November (Max): froze heatcheck-records/1 as the one shared data format. Prices are decimal strings in probability-dollars, timestamps are UTC Z and compared parsed, ids are namespaced nba:/syn: and bound to data_mode, final scores are labels and never GAME fields, bundles are exempt from EOL conversion, and real NBA bundles are git-ignored pending rights. Assigned R-001 and E-001 on owner branches.
- 7 November (Max, user decision): reviewer probes on review/independent-tests@2f36643. Fixed
  now, one commit each: RV-L3, RV-L4, RV-G1, RV-G2, RV-O1, RV-O2, RV-U8, RV-U9. RV-O4 (final
  tie) passes only incidentally via the RV-O1 events check; it is not separately fixed.
  **Deferred, market-related (user instruction):** RV-O5, RV-O7, RV-U2, RV-U3, RV-U7, RV-S1,
  RV-S2, RV-T2, RV-T3, RV-T4. **Not in the user's list, also unfixed:** RV-L5 (target resolves
  to no event), RV-L6 (unknown input hashes), RV-G3 (TEAM_WIN team not in game), RV-O3
  (TEAM_WIN contradicts final score), RV-O4 as a standalone rule. Reviewer tests are not
  modified; two need reviewer update after the RV-U8 fix (see commit b6a8c1f).
- 7 November (Max): quote freshness threshold, fixed before any demo. Historical comparison:
  the selected quote must be received at or before the forecast cutoff and no more than 600 s
  before it. Live display: the quote must be no more than 60 s old at display time. Older
  quotes are STALE and get no numerical comparison. Constants in
  heatcheck/contracts/eligibility.py. Matches Experience's handoff; the reviewer's default of
  60 s is the live value.
- 7 November (Max): GAME tip times. scheduled_tip_utc is nullable; optional observed_tip_utc
  records the actual tip from play-by-play and is never a pre-tip cutoff. Shot target ids are
  required to be <game_id>:shot:<provider_event_id>.
- 7 November (user decisions on the reviewer's questions, reports/review/2026-11-07-1642-r001-e001-replay.md §7;
  recorded by Max):
  - **RV-R1:** yes. The final step must refuse when the recomputed data hashes differ from the
    plan's `data_hashes`. Research is fixing it on research/r001-guard-fixes, which Max merges
    unchanged only after the reviewer confirms.
  - **Free throws are out of scope.** SHOT_ASSOCIATION covers field-goal attempts only.
    `player_prior_attempts_in_game` and `player_prior_makes_in_game` count field goals only
    (docs/tasks/RESEARCH.md amended). The reviewer's recomputation that counts all shots,
    finding 67 in reports/max/2026-11-07-1630-r001-bridge.md, should follow this definition.
    Max's keyword stand-in in the dialogue maps free-throw questions to NONE.
  - **Experience allowlist (RV-E1, RV-E2):** `check_request` matches whole path segments after
    normalisation, and `propose_mapping` matches outcomes by team ID. Experience fixes this
    after 20:00 UTC.
  - **Deferred validator probes:** the user lists 16 probe cases as deferred:
    - RV-O5, RV-O7, RV-U2 (×3), RV-U3, RV-U7, RV-S1, RV-S2, RV-T2, RV-T3, RV-T4;
    - and now also RV-L5, RV-L6, RV-G3, RV-O3, which were "not in the user's list, also
      unfixed" above.

    The reviewer marks them xfail(strict) on review/independent-tests, and Max merges that
    unchanged.
- 7 November: rule 8 of CLAUDE.md/AGENTS.md was replaced (commit f880b69). Sessions push to
  their own branches; nothing goes to main without the user's instruction; no force-push.
- 7 November (Max): the Discoverer's display name is "Heater"; its role in code, protocol and
  evidence stays `discoverer`. Free dialogue uses Meta `muse-spark-1.3` with reasoning
  effort `minimal`. The Ref's LLM text is shown only if every number and verdict word is in
  the evidence record; otherwise the template is shown. Every call has an 8 s deadline and a
  deterministic fallback. The Referee's decision is never produced by an LLM.
- 7 November (Max, user-agreed): the UI reads `heatcheck-referee-view/1`, a read-only
  projection of a ledger entry (docs/REFEREE_VIEW_FORMAT.md). Ledger records are not
  reshaped.
- 7 November, 18:00 (user, recorded by Max):
  - **View format withdrawn.** The `heatcheck-referee-view/1` entry above is superseded.
    Experience's UI reads the ledger as-is (experience/referee-ui-integrate@496901c, merged
    unchanged). Max's projection commit 954c0d5 was reverted in 60b5b10.
  - **Experience's questions:**
    - Keep the attack status name `UNSUPPORTED`.
    - STALE is 60 s for live display and 600 s for historical comparison. This was confirmed
      as correct.
    - `EvidenceLedger.open_readonly()` is added (commit c8831e6) for read-only callers such as
      apps/web/server/evidence.py.
    - The UI says "hashes verified" until the ledger hash chain exists. The chain now exists
      (c8831e6), so Experience may change the label once its reader verifies the chain.
  - **Reviewer agent-loop findings, fixed before the LLM wiring:**
    - RV-AL6: strict parsing (b2e6537).
    - RV-AL4/AL5: the Referee enforces mandatory + applicable attacks; the Challenger can add,
      never remove (b2e6537).
    - RV-AL1/AL2: the ledger is hash-chained (c8831e6). The two committed ledgers were
      migrated by adding chain fields only.

- **2026-11-07 18:15 UTC: confirmatory lane wired, dry run only (user instruction, Max).**
  - Research's 2024-25 family (CONF-HA, CONF-MOM, CONF-HH) is merged at 2d277d4. When Heater
    proposes one of these, the Referee hands it to `heatcheck/agents/confirmatory.py` instead of
    Max's attacks. In final mode that calls `scripts/confirmatory.py final` under Research's
    custodian and records each hypothesis in the evidence ledger with `lane: CONFIRMATORY`.
    New development-loop entries carry `lane: DEVELOPMENT`; entries written before this
    change have no lane field and are all 2023-24 development results.
  - Default mode is dry run: plans, Research code hash, seal, registration, exposure state and
    (if a data dir is given) the sealed table hashes are checked read-only. Nothing is run,
    reserved or written. Final mode needs a named authoriser and an all-PASS dry run.
  - The dry run is Max code, not a flag in Research's script, because that script is inside
    the family's frozen code_hash.
  - The final step is not run. It runs once, recorded, after the reviewer verifies the seal.
    It must run on Linux/macOS (Research's custodian uses fcntl) with a rebuilt 2024-25 data
    dir whose bytes match the seal.

- **2026-11-07 ~20:45 UTC: deterministic Ref, recorded Research finals, display titles (user instruction, Max).**
  - The Ref no longer calls a model. Its text is a template built only from the evidence
    entry; numbers appear only verbatim from the record (no rounding). Heater is the only
    model-written text and keeps the number guard. The model is still used for question mapping.
  - Research's 2023-24 GAME_PREDICTION final (receipt 3e238d2d) is recorded in
    `evidence/evidence.jsonl` without recomputation: H1 → GP-REST (INSUFFICIENT_EVIDENCE),
    H2 → GP-ELO (SURVIVED_PROTOCOL). Entries bind the result, plan, amendment and replay
    files and the exact custodian lines (reserve, spend, replay) by sha256. Recording checks
    the plan and amendment self-hashes, the receipt's reserve (with the plan hash) and spend,
    and that the reviewer-verified replay has identical decisions.
  - GP-ELO is a recorded-only claim id. It is not added to the registry, so no registry plan
    hash changes. Its statement is Max's restatement of the H2 estimand in Research's plan,
    and the entry labels it as such. The GP-REST ↔ H1 mapping is Max's.
  - The dialogue prefers a recorded final entry over running the loop for that claim.
  - The confirmatory final goes through the same recorder (`ConfirmatoryLane` →
    `recorded.record`).
  - Display titles (`heatcheck/api/display_titles.py`) are presentation only. They are never
    in a plan, a hash or an identity, and the registry text is unchanged.
  - The endpoint contract for Experience is in `docs/DIALOGUE_API.md`. Max's 8770 console
    page stays as the fallback.
