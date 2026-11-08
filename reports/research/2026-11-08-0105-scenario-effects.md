# Research status: scenario effect ESTIMATES (player absence, schedule) and a scenario combiner

| | |
|---|---|
| Branch | `research/scenario-effects` (from `research/live-forecast@e03629d`) |
| Code | `src/heatcheck/scenario.py` (pure), `scripts/scenario_effects.py`, `tests/test_scenario.py` (18 tests) |
| Outputs | `data/scenario/player_absence_effects.json`, `data/scenario/schedule_effects.json` |
| Label | **ESTIMATE, not a claim.** No registered test was run. These are descriptive effects with bootstrap intervals. |
| Logs | `logs/scenario/build.log`, `logs/scenario/worked_example.log` |

## Data (no new feeds)

- Three regular seasons: 2023-24 and 2024-25 from Research's builds, and 2025-26 from `cdnnba_2025`. All are
  pinned at `shufinskiy/nba_data@46488f0f`, giving 3,690 games and 7,380 team-games.
- The 2023-24 final and 2024-25 sealed epochs are already spent; they are read here for description only.

## Method

- **Residual.** For a team in a game: the result (1 for a win, 0 for a loss) minus the frozen B1 Elo pre-game
  win probability for that team. Home court applies unless the game is at a neutral site. Elo seeds roll from
  season to season by the frozen carry rule, exactly as in `live_forecast.py`.
- **Effect.** The mean residual with the condition minus the mean residual without it. It reads as the change
  in win probability beyond what Elo expected.
- **Log-odds effect.** By the delta method: effect / (pbar × (1 − pbar)), where pbar is the mean Elo
  probability over the games behind the estimate.
- **Player absence.**
  - "Appeared" means the player has at least one play-by-play event for that team in that game. Substitution
    events carry the player id, so starters and bench players are both captured.
  - Games missed are the team's games between the player's first and last appearance for it in a season, in
    which he did not appear. Seasons are pooled per player and team.
  - Interval: a bootstrap resampling absent and present games separately (B = 2000), reporting 80% and 95%
    percentile intervals.
  - The output is keyed `nba-player:<id>|nba-team:<id>`.
- **Schedule.**
  - Back-to-back means the team's rest days = 0. 3-in-4 means the team's 3rd game within 4 days.
  - Rest difference is home rest minus away rest, each capped at 3, compared with equal-rest games.
  - Rest days come from the frozen feature code.
  - Interval: a bootstrap resampling whole games (B = 2000), so both team rows of a game move together.
  - The registered verdict is attached where one exists.

## Coverage

| Player-team keys | With ≥5 games missed | ≥10 | ≥20 | Distinct players |
|---|---|---|---|---|
| 1,203 | **1,046** | 903 | 660 | 796 |

- **Flags:** 301 keys are low-involvement (median below 8 play-by-play events per game). 489 keys have at least
  5 games missed and none of the three specific risk flags (small n, team change, low involvement).
- **Names:** 38 keys have no name in the raw play-by-play.
- **Multiplicity:** 145 of the 1,046 keys with ≥5 missed (13.9%) have a 95% interval excluding 0. There is no
  multiplicity adjustment, and about 52 would do so by chance alone.

## Schedule estimates (win-probability scale)

| Condition | n | Estimate, 80% interval, 95% interval | Registered verdict |
|---|---|---|---|
| back-to-back (team) | 1313 | -0.053 | [-0.070, -0.036] | [-0.079, -0.028] | GP-REST INSUFFICIENT_EVIDENCE (unproven) |
| 3-in-4 (team) | 1934 | -0.029 | [-0.043, -0.014] | [-0.051, -0.006] | none registered |
| rest diff -3 (home minus away) | 13 | -0.179 | [-0.334, -0.014] | [-0.408, +0.071] | GP-REST INSUFFICIENT_EVIDENCE (unproven) |
| rest diff -2 (home minus away) | 126 | -0.044 | [-0.102, +0.011] | [-0.132, +0.046] | GP-REST INSUFFICIENT_EVIDENCE (unproven) |
| rest diff -1 (home minus away) | 627 | -0.051 | [-0.077, -0.025] | [-0.090, -0.010] | GP-REST INSUFFICIENT_EVIDENCE (unproven) |
| rest diff 1 (home minus away) | 687 | +0.021 | [-0.005, +0.047] | [-0.019, +0.064] | GP-REST INSUFFICIENT_EVIDENCE (unproven) |
| rest diff 2 (home minus away) | 143 | +0.119 | [+0.069, +0.166] | [+0.043, +0.194] | GP-REST INSUFFICIENT_EVIDENCE (unproven) |
| rest diff 3 (home minus away) | 24 | -0.132 | [-0.250, -0.029] | [-0.302, +0.021] | GP-REST INSUFFICIENT_EVIDENCE (unproven) |

- **Back-to-backs** are associated with about 5 points lower win probability than Elo expects. 3-in-4 is
  associated with about 3 points lower.
- **The registered test (GP-REST) could not establish that rest adds to Elo out of sample.** The UI must call
  the effect unproven. The extreme rest-difference values (±3) rest on 13 and 24 games.

## Scenario combiner: `scenario_probability()` (pure)

- **Inputs:** a baseline home-win probability, the home and away team ids, and a list of changes:
  - player absence: `key` and `side`;
  - back-to-back or 3-in-4: `side`;
  - rest difference: `value` from −3 to 3.
- **Combination:** effects are added on the log-odds scale. A home-team effect adds; an away-team effect
  subtracts.
- **Interval:** each effect's 95% bootstrap interval is approximated as normal and combined in quadrature. The
  baseline is treated as fixed.
- **Refuses, never repairs:**
  - unknown fields or effects;
  - the same player twice;
  - a player whose estimate is for the other team;
  - fewer than 5 games missed, unless `min_n_missed` is lowered explicitly;
  - more than one rest-family change per team;
  - rest difference together with any team-level rest change;
  - any rest change when `baseline_includes` contains `"rest"` (e.g. a baseline from a model with rest
    terms);
  - an effect with no estimate (a bucket with no games).
- **Independence assumption, stated:** effects are assumed independent and additive on the log-odds scale.
  Real absences and schedule spots co-occur (stars rest on back-to-backs), so combined scenarios can double
  count partly even when not refused.
- **Worked example** (`logs/scenario/worked_example.log`), NYK @ CLE `nba:0022600191`:
  - baseline 0.662;
  - with "Cleveland without J. Allen" (24 missed, effect −0.172, 95% [−0.389, +0.033]) and "NYK on a
    back-to-back": **0.533**, 80% [0.384, 0.676], 95% [0.311, 0.742];
  - adding a 3-in-4 for NYK on top is refused as double counting.

## Limits

- **Absences mix rest, injury, suspension, illness and coach decisions,** and the data cannot tell them apart.
  An absence estimate is not "the effect of an injury".
- **Garbage-time bias:** low-involvement players appear mostly once a game is decided, so their appearance
  depends on the outcome. They are flagged; their estimates should not be used.
- **Elo partly absorbs long absences,** shrinking estimates toward zero. Absences after a player's last
  appearance for a team are not counted.
- **Team changes:** players traded within a season are flagged. Their pooled estimate mixes contexts.
- **No multiplicity adjustment and no shrinkage** across players; small-n estimates are noisy.
- **2025-26 neutral-site games are not flagged,** so home court is applied to all of them.

## Checks

| Check | Result |
|---|---|
| `tests/test_scenario.py` (planted absence effect recovered within its 95% interval; tenure window; flags; game-clustered schedule bootstrap; 3-in-4; combiner arithmetic; 11 refusal cases; empty bucket refused), with `-W error::RuntimeWarning` | **PASS** 18/18 |
| Real-data build | **PASS**, exit 0, about 76 s |
| Independent review | **NOT_RUN** |

During development: one test expectation was wrong (the tenure window correctly excludes a game before the
first appearance), and empty rest buckets produced NaN. Both were fixed before the real-data run was
committed.
