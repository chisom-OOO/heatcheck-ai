# Research status: empirical-Bayes shrinkage for player-absence estimates

| | |
|---|---|
| Branch | `research/scenario-effects` |
| Outputs | `data/scenario/player_absence_effects.json` (same format and keys; new fields only), `data/scenario/scenario_answers.json` (heatcheck-scenario/1, unchanged format) |
| Logs | `logs/scenario/build_shrunk.log`, `logs/scenario/worked_example_shrunk.log`, `logs/scenario/scenario_api_format.log` |
| Label | ESTIMATE, not a claim |

## Method

- **Model:** normal-normal, with prior mean 0.
- **Per-estimate noise:** SE_i is the width of the raw 95% bootstrap interval divided by 2 × 1.96.
- **Spread of true effects:** estimated from the 489 well-covered keys (≥5 games missed and no risk flag):
  τ² = max(0, var(raw estimates) − mean SE²) = max(0, 0.01997 − 0.01350) = **0.00647**, so **τ = 0.080** on
  the win-probability scale. The mean raw estimate among these keys is +0.003, which supports a prior mean of 0.
- **Shrinkage:** each estimate × B_i = τ² / (τ² + SE_i²). The interval is the normal posterior,
  B_i · raw ± z · √B_i · SE_i. The log-odds values use the same delta-method factor as before.
- **What the file holds:**
  - `estimate`, `ci80` and `ci95` are now the **shrunk** values, the default;
  - `raw_estimate`, `raw_ci80`, `raw_ci95` and `shrinkage_factor` are added;
  - `shown_by_default` is `false` for any risk flag (small n, team change, low involvement) or fewer than 5
    games missed;
  - the file-level `shrinkage` block records τ² and its inputs.
- **The schedule effects are not shrunk:** they are single pooled estimates with large n.

## Effect

| | Raw | Shrunk |
|---|---|---|
| Keys with ≥5 missed whose 95% interval excludes 0 | 145 of 1,046 (about 52 expected by chance) | **35** (22 among the 489 shown by default) |
| **J. Allen, CLE** (24 games missed) | −0.172, 95% [−0.389, +0.033] | **−0.062, 80% [−0.144, +0.021], 95% [−0.188, +0.065]** (factor 0.358) |

Shown by default: 489 of 1,203 keys.

## NYK @ CLE worked example, recomputed (`nba:0022600191`, baseline 0.662)

| Scenario | Before (raw) | Now (shrunk, default) |
|---|---|---|
| CLE without J. Allen + NYK on a back-to-back | 0.533, 80% [0.384, 0.676], 95% [0.311, 0.742] | **0.649, 80% [0.562, 0.727], 95% [0.513, 0.764]** |
| CLE without J. Allen only | — | 0.599, 95% [0.463, 0.722] |

Cleveland card (`scenario_answers.json`, 90% range):

| Scenario | p_team_win | 90% range | Games missed |
|---|---|---|---|
| without J. Allen | 0.599 | 0.485 – 0.704 | 24 |
| without D. Mitchell | 0.604 | 0.501 – 0.699 | 43 |
| without E. Mobley | 0.645 | 0.556 – 0.726 | 58 |

## Checks

| Check | Result |
|---|---|
| `tests/test_scenario.py` (adds: τ recovered on 400 planted effects with true spread 0.05; shrunk = B × raw; narrower interval; log-odds consistent; flagged small-n key not shown and pulled hard to 0; τ² floored at 0 with all estimates shrunk to 0) | **PASS** 24/24 |
| Real-data rebuild | **PASS**, exit 0 |
| Experience's `readScenarios` / `scenarioProblem` (`c9ef784`) on the regenerated 28 answers | **PASS**: 280/280 shown, 0 refused. The negative control is still refused 5/5. |

## Notes

- Shrinkage needs no change to Max's endpoint: same file, same keys, and `estimate` simply holds the shrunk
  value.
- Absence scenarios now carry the caveat "Shrunk toward no effect (empirical Bayes); the raw estimate is
  noisier."
- **Limits:**
  - τ comes from one pooled population of players. Stars and role players likely differ, and a single prior
    shrinks stars' effects toward zero too much.
  - The SEs come from percentile intervals, which are approximately but not exactly normal.
