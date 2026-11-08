# Research tasks

Owner: HeatCheck-Research (Claude Pro, separate computer). Assigned by Max on 7 November 2026.
First read: `CLAUDE.md`, `docs/team/02_Pro_Research.md`, `docs/DATA_PIPELINE.md` §1–3 and §5,
`docs/DATA_FORMAT.md`, `contracts/Shared_Protocol.json`. Example bundle:
`tests/fixtures/contracts/syn_reference_bundle/`.

---

## R-001: one reproducible NBA game, reconciled, with pre-shot invariance

**Status:** READY. **Branch:** `research/r-001-one-game` from the commit that
contains this file (`max/integration`, or `main` after Max merges it). **Gates touched:** G01 (one-game scope), G02 (one-game scope). The
season-wide gates stay NOT_RUN. **Reviewer:** Max.

### Goal

Produce one real 2023–24 regular-season NBA game end to end in `heatcheck-records/1`.
Take it from a pinned upstream snapshot, reconcile its final score against a second
independent source, and show by test that changing a shot's outcome cannot change that
shot's pre-shot features.

### Deliverables

1. **Ingestion code** in `heatcheck/data/`. Its input is a pinned `shufinskiy/nba_data`
   commit plus one play-by-play provider. Use the same provider for the whole pass and
   record which one and why. Its output is a bundle at `data/bundles/r001-<game>/`
   (git-ignored) that the Max validator accepts. Records: `RAW_SNAPSHOT` (with
   `bundle_path: null` unless redistribution is allowed), `GAME`, every `EVENT` for the game,
   one `FEATURE_ROW` per shot attempt (`PRE_SHOT_MAKE`), and `RESTRICTED_LABEL`s
   (`GAME_FINAL_SCORE`, and `SHOT_MADE` per shot). `data_mode = REAL_NBA_RETROSPECTIVE`.
   Choose the game, record its NBA game id and say why.
2. **Fetch manifest** at `data/manifests/r001.json` (committed). It holds the upstream repo
   URL, commit SHA, file path(s), the byte count and sha256 of each raw file, retrieval UTC,
   the rights note, the bundle `records_sha256` and the exact command that rebuilds the bundle.
3. **Pure feature builder** in `heatcheck/research/` (no I/O). Its input is the game's
   `EVENT` records; its output is the `FEATURE_ROW` records. Minimum features:
   `pre_shot_margin_shooting_team`, `player_prior_attempts_in_game`,
   `player_prior_makes_in_game`, `period`, `clock_seconds_remaining`.
   **Free throws are out of scope (user decision, 7 November; docs/DECISIONS.md).**
   SHOT_ASSOCIATION covers field-goal attempts only. `player_prior_attempts_in_game` and
   `player_prior_makes_in_game` count the player's earlier **field-goal** attempts and makes
   in the game. Free throws are excluded from both counts and are never shot targets.
   (Max clarification, not part of the user decision: `pre_shot_margin_shooting_team` is the
   score margin and so still includes free-throw points. Research may challenge this.) The
   current shot's
   `made`, its points and `assisted_post_outcome` are never inputs to its own row. When the
   event order is unresolved, emit `missing_reason` or exclude the row and record why in the
   manifest's `exclusions`.
4. **Reconciliation report** at `reports/r001_reconciliation.md` (committed). Source A is the
   final score derived by summing made-shot points in the play-by-play. Source B is a second
   independent source: the BALLDONTLIE games API with the **user's** key held server-side,
   or another documented source if the user provides none. Compare home team, away team, game
   date or tip time, home points and away points. For each source include the raw-response
   sha256 and retrieval UTC. Any mismatch → set the label `reconciliation: QUARANTINED` and
   report FAIL. Do not edit values to make them agree.
5. **Tests** in `tests/research/test_r001_*.py` (see acceptance).

### Acceptance criteria (each must be replayable by Max on the exact commit)

| # | Criterion | How it is checked |
|---|---|---|
| A1 | The bundle is valid | `uv run python -m heatcheck.contracts.bundle data/bundles/r001-<game>` exits 0 and prints PASS with `modes=['REAL_NBA_RETROSPECTIVE']` |
| A2 | Reproducible | Run the rebuild command from the fetch manifest twice from a clean `data/bundles/`. Both runs print the same `records_sha256`, and it equals the value in `data/manifests/r001.json` |
| A3 | Final score reconciled | `reports/r001_reconciliation.md` shows Source A = Source B for home/away teams and both point totals, with both raw hashes. The `GAME_FINAL_SCORE` label has `reconciliation: RECONCILED`. If Source B could not be fetched, A3 is **NOT_RUN** and R-001 is not complete |
| A4 | Pre-shot invariance on the real game | `uv run pytest tests/research/test_r001_preshot_invariance.py` passes. For **every** shot in the game: flip `made` (and therefore the points scored), rebuild the features, and the canonical bytes of that shot's `FEATURE_ROW` are identical before and after |
| A5 | The test can fail | The same test file includes a negative control: a deliberately leaky builder that reads the current shot's outcome. Asserting the invariance property against it must **fail**, and the test checks that it fails |
| A6 | The test is sensitive downstream | For at least one flipped shot, a later shot's features by the same team or player change. This shows the flip actually propagated |
| A7 | Offline and clean | A4–A6 run without network access; patch `socket.socket` to raise in the test. `uv run ruff check .` passes. No key, token or `.env` content appears in any committed file or test output |

A4–A6 also run on a small committed `SYNTHETIC` fixture (with `syn:` ids) so that the property
is checked on machines without the real data. The real-game run is still required for A4.
Report a skip of the real-data test as NOT_RUN, never as a pass.

### Out of scope for R-001

Other games, season splits, models, attacks, simulator and quote normalisation. Also: any
change to `heatcheck/contracts/`. File a schema change request in `docs/tasks/README.md` instead.

### Constraints

Follow the provider's terms and rate limits; do not bypass access controls. Keys stay in
private configuration and are never printed. Do not commit raw bulk data. Do not push:
hand the branch to Max as a `git bundle` or patch through the medium the user authorises,
or push only if the user explicitly releases pushing.

### Checkpoint log

(append entries using the template in `docs/tasks/README.md`)
