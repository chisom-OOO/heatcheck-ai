# Research status: scenario estimates in Experience's format heatcheck-scenario/1

| | |
|---|---|
| Branch | `research/scenario-effects` |
| Format | `heatcheck-scenario/1`, as defined in `apps/web/HANDOFF.md` on `experience/market-board@c9ef784` |
| Code | `scenario.scenario_api_answer()` (pure); `scripts/scenario_answers.py` |
| Output | `data/scenario/scenario_answers.json`: answers for both teams of all 14 forecast games (28 answers, 280 scenarios) |
| Log | `logs/scenario/scenario_api_format.log`; checker script `logs/scenario/check_with_experience_js.mjs` |

## How Max serves it at /api/scenario

- **Preferred:** call `heatcheck.scenario.scenario_api_answer(game_row, card_team_id, card_team_name,
  card_baseline_string, forecast_id, absence_effects, schedule_effects, source=...)` with the card's own team
  and baseline string. The baseline is echoed unchanged, which satisfies the page's "same team, same baseline,
  same SAMPLE status" rule.
- **Or:** serve `data/scenario/scenario_answers.json` → `answers[game_id][team_id]`. Each baseline there is the
  forecast exactly: `p_home_win` for the home team, and 1 − `p_home_win` (decimal arithmetic) for the away team.

## Format rules met

- `label` is exactly `"ESTIMATE"`.
- Probabilities are decimal strings with 3 decimals, in 0–1. The range is a 90% interval (`level` `"0.90"`),
  with low ≤ p_team_win ≤ high; rounding is monotone, so the order holds.
- `n` is a positive whole number:
  - games missed, for an absence (at least 5);
  - team-games in the condition, for a schedule spot (1,313 back-to-backs; 1,934 3-in-4s).
- Every scenario has `n_unit` and at least 5 caveats.
  - Rest scenarios say the effect is unproven (GP-REST INSUFFICIENT_EVIDENCE).
  - Absence scenarios say absences mix rest and injury, and that the current 2026-27 roster is not verified.
- `is_sample` is `false`. `scenario_id`s are unique within an answer and include the team.

## Which scenarios are offered

- Each team on a back-to-back, and each team on a 3-in-4.
- Each team without one of its players, up to 3 per team (most games played first). A player is offered only
  if:
  - his estimate has at least 5 games missed and no risk flag (small n, team change, low involvement);
  - he has a name;
  - he appeared for that team in 2025-26;
  - he is not on both teams' lists.
- Combinations are not offered: each scenario is one change, and the combiner refuses overlapping rest changes.

## Checks

| Check | Result |
|---|---|
| Experience's own `readScenarios` and `scenarioProblem` (`apps/web/web/market/scenario-model.js` at `c9ef784`, run in Node 22) on all 28 answers | **PASS**: 0 unavailable, 280/280 scenarios shown, 0 refused |
| Negative control: 5 deliberately broken scenarios (label, n = 0, no caveats, a number instead of a string, point outside range) | **all 5 refused** by the same checker |
| `tests/test_scenario.py` (adds format rules for home and away cards, a wrong team refused, ambiguous or stale players skipped, unique ids) | **PASS** 22/22 |

## Defect found and fixed

My first version used scenario ids without the team, and offered any player with an estimate for either team.
A test showed the collision: the same player had estimates for both teams in a game. The fix adds the team to
the id, offers only players seen for that team in 2025-26, and skips players on both teams' lists. All of this
was fixed before this push.

## Example: Cleveland card, NYK @ CLE, baseline "0.661772"

| Scenario | p_team_win | 90% range | n |
|---|---|---|---|
| New York on a back-to-back | 0.707 | 0.689 – 0.725 | 1,313 team-games |
| Cleveland on a back-to-back | 0.613 | 0.592 – 0.633 | 1,313 team-games |
| Cleveland without D. Mitchell | 0.535 | 0.384 – 0.680 | 43 games missed |

These are ESTIMATES, not claims. The Ref's line on the page stays "Edge unverified".
