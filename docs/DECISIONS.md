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
