# Idea grammar: heatcheck-idea-family/1

Owner: Research. Status: **frozen for building**, written 7 November 2026 before the test code. Max builds
the proposer against this document. If this text and `handoff/research-20261107/src/heatcheck/ideas.py`
disagree once the code lands, the code governs and the disagreement is a defect: report it to Research.

An **idea** is one hypothesis that HeatCheck can test on its own data with a pre-written test. The proposer
(Heater / the Discoverer) may only emit ideas in this grammar. Everything not listed here is refused, never
repaired.

## 1. What a proposer sends

```json
{
  "format": "heatcheck-idea-family/1",
  "ideas": [
    {"template": "GAME_HOME_WIN_SPLIT", "params": {"feature": "away_back_to_back", "level": "yes", "alternative": "greater"}},
    {"template": "SHOT_MAKE_AFTER_CONDITION", "params": {"condition": "after_makes", "level": "2", "alternative": "two_sided"}}
  ]
}
```

**Strict rules** (any violation refuses the whole request; nothing is computed):
- The top level has exactly the keys `format` and `ideas`. `format` is exactly `"heatcheck-idea-family/1"`.
- `ideas` is a list of **1 to 20** ideas.
- Each idea has exactly the keys `template` and `params`. `params` has exactly the keys listed for its
  template.
- Every value is a **string** taken from the enumerations below. Numbers, booleans, null, lists, extra
  whitespace and case variants are refused: `"2"` is valid, `2`, `" 2"` and `"Two"` are not.
- The JSON must have no duplicate keys and no NaN.
- Two ideas with identical canonical form are refused as a duplicate.
- No free text, rationale, data filter, threshold, seed, sample size or test choice can be supplied. Those
  are fixed by the template.

The **canonical form** of an idea is its JSON with sorted keys and no whitespace (UTF-8). Its id is
`idea_hash = sha256(canonical form)`.

## 2. Template GAME_HOME_WIN_SPLIT

**Question:** is the home-win rate different in games that have one feature value than in all other games?

`params`: exactly `feature`, `level`, `alternative`.

| `feature` | allowed `level` | the group is: games where … |
|---|---|---|
| `home_rest_days` | `"0"`, `"1"`, `"2"`, `"3+"` | the home team's rest days equal `level` |
| `away_rest_days` | `"0"`, `"1"`, `"2"`, `"3+"` | the away team's rest days equal `level` |
| `rest_advantage` | `"home_more"`, `"equal"`, `"away_more"` | home rest − away rest is > 0, = 0, < 0 |
| `home_back_to_back` | `"yes"` | the home team played the previous day |
| `away_back_to_back` | `"yes"` | the away team played the previous day |
| `elo_gap` | `"home_fav_100+"`, `"home_fav_0_100"`, `"away_fav_0_100"`, `"away_fav_100+"` | pre-game Elo gap (home + 100 home-court − away) is ≥ 100, in [0, 100), in [−100, 0), < −100 |
| `month` | `"10"`, `"11"`, `"12"`, `"01"`, `"02"`, `"03"` | the game's US/Eastern date is in that month |
| `day_of_week` | `"Mon"`, `"Tue"`, `"Wed"`, `"Thu"`, `"Fri"`, `"Sat"`, `"Sun"` | the game's US/Eastern date is that weekday |

`alternative`: `"two_sided"`, `"greater"` (the group's home-win rate is higher than the rest) or `"less"`.

**Definitions.**
- Rest days and the Elo gap come from the frozen `features.pregame_features` (the code of the 2023–24 final run).
  - Rest days = days since the team's previous game, minus 1, capped at 3; a season opener counts as `"3+"`.
  - Elo uses the fixed constants (K 20, home court 100, carry-over 0.75), seeded from 2022–23.
  - Elo is updated only from **development-game** outcomes.

**Data:**
- Included: 2023–24 regular-season **development** games only (fit + tune + calibration, 930 games).
- Excluded: neutral-site games.
- Never used: the 300 spent 2023–24 final games and the sealed 2024–25 season.

**Statistic:** T = home-win rate (group) − home-win rate (all other eligible games).

**Null and test:**
- Null: the home result is independent of the feature value.
- Test: a permutation test. Home results are shuffled across eligible games, B = 999, and T is recomputed
  each time.
- Seed: the first 8 hex digits of `idea_hash`, read as an integer.
- p-values:
  - `greater`: p = (1 + #{T* ≥ T}) / (B + 1).
  - `less`: p = (1 + #{T* ≤ T}) / (B + 1).
  - `two_sided`: with c = mean(T*), p = (1 + #{|T* − c| ≥ |T − c|}) / (B + 1).

**Minimum sample:** at least 30 games in the group **and** 30 in the rest. Otherwise the verdict is
`INSUFFICIENT_EVIDENCE` and there is no p-value.

**Assumption, stated:** games are treated as exchangeable. Within-day or within-team dependence is not
modelled.

## 3. Template SHOT_MAKE_AFTER_CONDITION

**Question:** is a field-goal attempt more or less likely to go in when a condition holds than when it does
not?

`params`: exactly `condition`, `level`, `alternative`.

| `condition` | allowed `level` | condition true when … | eligible shots | permutation strata |
|---|---|---|---|---|
| `after_makes` | `"1"`, `"2"`, `"3"`, `"4"` | the previous `level` FGA by the same player in the same game were all made | shots with ≥ `level` earlier FGA in the player-game | player × game × shot value (as D11) |
| `after_misses` | `"1"`, `"2"`, `"3"`, `"4"` | the previous `level` FGA in the player-game were all missed | as above | player × game × shot value |
| `shot_value` | `"3"` | the attempt is a 3-pointer (vs a 2-pointer) | all eligible shots | player × game |
| `period` | `"1"`, `"2"`, `"3"`, `"4"`, `"OT"` | the attempt is in that period (`"OT"` = any overtime) | all eligible shots | player × game × shot value |

`alternative`: `"two_sided"`, `"greater"` (the make rate is higher when the condition holds) or `"less"`.

**Data:**
- Field-goal attempts only; free throws are out of scope (D12).
- The shooter must be known and the event order resolved (shots in a period with a clock regression are
  excluded, D3).
- Included: 2023–24 development games only. Never used: the spent final games or 2024–25.

**Statistic:** T = pooled make rate (condition true) − pooled make rate (condition false), over eligible
shots.

**Null and test:**
- Null: outcomes are exchangeable within the strata.
- Test: a permutation test, B = 999, with the same seed rule and p-value formulas as §2.
- For the streak conditions the condition depends on earlier outcomes, so eligibility and the condition
  are **recomputed after every shuffle**, as in D11.
- The null is not centred at 0 for streak conditions (pooling across player-games), which is why the test
  compares against the permutation distribution, not against 0.

**Minimum sample:** at least 200 shots with the condition true **and** 200 with it false. Otherwise
`INSUFFICIENT_EVIDENCE`.

**Limit, stated:** a difference is an association under within-stratum exchangeability, not a cause. In
Research's harness, within-game form drift with no streak triggered the k = 3 streak test 38% of the time.

## 4. The family: register, freeze, run, correct

Given one request with N ideas:

1. **Validate** the whole request (§1). A single invalid idea refuses the request.
2. **Register and freeze before computing.**
   - Write `registration.json` (write-once; refuses to overwrite). It contains:
     - every idea's canonical form and `idea_hash`, in submitted order;
     - the mode;
     - the data identity: logical table hashes and the split manifest hash, or in synthetic mode a hash of
       the league view;
     - the code hash of the idea code;
     - B, α and the seed rule;
     - `created_utc`.
   - Its own sha256 is the `registration_hash`. Computation starts only after re-reading the file and
     checking that hash.
3. **Run** every idea with its template's fixed test.
4. **Correct:** Holm across **all N** at α = 0.05. An idea without a p-value
   (`INSUFFICIENT_EVIDENCE`) counts as p = 1 in the correction, so it never makes others easier to pass.
5. **Write** `results.json` (write-once), bound to the `registration_hash`.

**Verdict per idea** (never `SURVIVED_PROTOCOL`: that label belongs to pre-registered, sealed confirmatory
tests only):

| Verdict | When |
|---|---|
| `CANDIDATE` | test executed, minimum sample met, Holm-adjusted p < 0.05 |
| `NOT_A_CANDIDATE` | test executed, minimum sample met, Holm-adjusted p ≥ 0.05 |
| `INSUFFICIENT_EVIDENCE` | minimum sample not met, or the statistic is undefined |

A `CANDIDATE` is an exploratory finding on development data. To become a claim it needs its own
pre-registration and a sealed confirmatory test. The sealed 2024–25 season already has its registered
family and is closed to new families.

**Output per idea in `results.json`:** `idea_hash`, `template`, `params`, `n_condition`, `n_rest`,
`rate_condition`, `rate_rest`, `T`, `null_mean`, `p_raw`, `p_holm`, `verdict`. The file also carries the
family-level `registration_hash`, `mode`, N, α, B, `label: "EXPLORATORY"` and the data scope.

## 5. Synthetic mode (testing the idea machine)

The same family procedure runs on a planted-truth simulated league from `simulate.generate` (Research §06).
This shows how often the machine finds real effects and how often it raises false candidates.

**The league and its truth.**
- The runner (not the proposer) chooses the league: simulator family, planted streak effect γ (log-odds)
  and seed. These and the truth stay in the runner. The proposer sees only that the mode is synthetic.
- Only `SHOT_MAKE_AFTER_CONDITION` is available. The simulator has no games, home teams or calendars, so
  `GAME_HOME_WIN_SPLIT` is refused in synthetic mode.
- `period` labels in a synthetic league are drawn uniformly from {1, 2, 3, 4} by a separate random stream,
  independent of everything else. Every `period` idea is therefore a **planted null**.
- Synthetic leagues have no overtime, so a `period` idea with level `"OT"` is **refused** in synthetic mode
  (the whole request is refused, as for any invalid idea). It is valid in development mode.

**Truth hiding.**
- The family function receives only the league view: outcomes, player-game ids, shot values, synthetic
  periods.
- The truth (γ, simulator family, seed) is written to `truth.json` **after** `results.json`.
- A scorer then joins truth to results.

**Truth per idea in a league with planted γ ≠ 0:**

| Idea | Truth | Why |
|---|---|---|
| `after_makes`, any level | EFFECT, make rate higher | the planted term raises the make probability after 3 straight makes; levels 1, 2 and 4 overlap that state |
| `after_misses`, any level | EFFECT, make rate lower | those shots are never in the planted state, while the rest include it |
| `shot_value` `"3"` | EFFECT, make rate lower | simulated 3-point talent is lower than 2-point talent by construction |
| `period`, any level | NULL | random labels |

With γ = 0, the streak ideas are NULL as well. Only the k = 3 term is planted directly. The effects at other
levels follow from overlap and may be small.

**Scoreboard (`scoreboard.json`):**
- planted effects found: CANDIDATE on an EFFECT idea, in the true direction for one-sided ideas;
- planted effects missed;
- nulls correctly not flagged;
- false candidates: CANDIDATE on a NULL idea, or in the wrong direction.

## 6. Interfaces

- **Python:** `heatcheck.ideas`:
  - `validate_request(obj) -> list[Idea]`, which raises `IdeaRefused`;
  - `run_family(request, mode_view, out_dir)` writes `registration.json` then `results.json`.
- **CLI:**
  - Development data:
    `python -I scripts/idea_family.py dev <data_2023-24> <request.json> <out_dir>`
  - Synthetic, with the runner's choice:
    `python -I scripts/idea_family.py synthetic <request.json> <out_dir> --family A --gamma 0.30 --seed <n>`
  - Refusals print `REFUSED: ...` and exit 2.
- **Data access is fixed in code:**
  - the development loader accepts only the 2023–24 build and only its development split;
  - no code path in this module reads the sealed 2024–25 data or the custodian ledger.
