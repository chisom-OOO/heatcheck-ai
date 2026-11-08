# Scenario effects: the current interface (Research ↔ Max ↔ Experience)

Written by Research, 8 November 2026. It replaces the stub-era version (Max, 01:35Z), which described an
`elo_shift` provider that no longer exists. It is based on `max/integrate-r001-e001@11772da`,
`heatcheck/agents/research_scenario.py`, and Research's code at `research/scenario-effects@f86d797`.

**Everything here is an ESTIMATE, not a claim.** No scenario is a tested result, and no scenario is
evidence that the model beats the market.

## 1. Research supplies

**Code:** `handoff/research-20261107/src/heatcheck/scenario.py`. It is pure (no file, network or database
side effects). Max loads it by file path as `research_scenario`.

| Function | Use |
|---|---|
| `scenario_api_answer(game, team_id, team_name, baseline_p_team, forecast_id, absence, schedule, *, source, max_players=3, level=0.90)` | One `GET /api/scenario` answer in Experience's `heatcheck-scenario/1` for one game card |
| `scenario_probability(baseline_p_home, home_team_id, away_team_id, changes, absence, schedule, *, baseline_includes=(), min_n_missed=5)` | Combines changes with a baseline home-win probability; used by free-text what-ifs |
| `ScenarioRefused` | Raised, never repaired, for any change the combiner will not accept |

**Tables** (`data/scenario/`, rebuilt by `scripts/scenario_effects.py`):
- **`player_absence_effects.json`** (`heatcheck-scenario-absence/1`).
  - `effects` is keyed `nba-player:<id>|nba-team:<id>`.
  - Each row has `player_name`, `team`, `seasons`, `n_games_missed`, `n_games_played`,
    `median_events_per_game`, `flags` and `shown_by_default`.
  - `effect_win_prob` and `effect_log_odds` each carry `estimate`, `ci80` and `ci95`. These are the
    **empirical-Bayes-shrunk** values, the default.
  - The unshrunk values sit alongside as `raw_estimate`, `raw_ci80`, `raw_ci95` and `shrinkage_factor`.
  - File-level `shrinkage` records τ² = 0.00647 (τ = 0.080) from 489 well-covered keys, and `coverage`
    records the counts.
- **`schedule_effects.json`** (`heatcheck-scenario-schedule/1`).
  - Entries: `back_to_back`, `three_in_four`, and `rest_diff.by_value["-3".."3"]`.
  - Each carries the same effect blocks, plus `n_condition`.
  - `registered_verdict` is GP-REST INSUFFICIENT_EVIDENCE on the back-to-back and rest-difference entries,
    and `null` on 3-in-4.
- **`scenario_answers.json`:** precomputed `scenario_api_answer()` output for both teams of every game in
  `data/live/forecasts.json`. It is for reference and tests. The server calls the function live.

**Effect definition:** the mean of (team result − frozen B1 Elo expectation) with the condition, minus the
mean without it. The log-odds value is win-probability effect / (pbar × (1 − pbar)).

## 2. GET /api/scenario: what the page receives

`GET /api/scenario?game_id=nba:<id>[&team=<full team name>]`. The team defaults to the home team.

1. Max's `ResearchScenario.api_answer()` takes the card's team and the **exact baseline string**:
   `p_home_win` for the home team, or `1 − p_home_win` in decimal arithmetic for the away team.
2. It calls `scenario_api_answer()` unchanged.
3. It then adds **only** an `evidence` field on absence scenarios: the raw, unshrunk values and the shrinkage
   factor, for the evidence drawer. Experience's reader ignores it.

**What each answer contains** (`heatcheck-scenario/1`, `apps/web/HANDOFF.md`):
- `format`, `status: "OK"`, `game_id`, `team`, `is_sample: false`, `source`;
- `baseline` `{p_team_win, forecast_id}`, echoed unchanged;
- `scenarios`: each has `scenario_id`, `text`, `label: "ESTIMATE"`, `p_team_win`, `range` and `n`.
  - `p_team_win` and the range ends are decimal strings with 3 decimals, in 0–1.
  - `range` is `{low, high, level: "0.90"}`, with low ≤ p ≤ high.
  - `n` is a positive integer, with `n_unit`.
  - Each scenario also carries `caveats` (at least 5) and `method`.

**Which scenarios are offered, for each team:**
- on a back-to-back;
- on a 3-in-4;
- without one of up to 3 players. A player is offered only if he has `shown_by_default`, at least 5 games
  missed, no risk flag, a name, and appeared for that team in 2025-26, and is not listed for both teams.
  Players are ordered by games played.

**IDs:** `<game_id>:b2b:<side>`, `<game_id>:3in4:<side>`, `<game_id>:absent:nba-player:<id>:nba-team:<id>`.

**Checks:**
- Experience's own `readScenarios` and `scenarioProblem` (`experience/market-board@c9ef784`) accept all 280
  scenarios in the committed answers and refuse 5 of 5 deliberately broken ones
  (`reports/research/logs/scenario/`).
- Max reports that his endpoint's answers equal `scenario_answers.json` for all 14 games × 2 teams.

## 3. Free-text what-ifs (Max's `heatcheck-whatif/1`)

Max's parser turns a confirmed change into one combiner call against the game's forecast baseline:

| User change | Combiner change |
|---|---|
| a team on a back-to-back | `{"type": "schedule", "effect": "back_to_back", "side": "home"\|"away"}` |
| a team on a 3-in-4 | `{"type": "schedule", "effect": "three_in_four", "side": ...}` |
| a player out | `{"type": "player_absence", "key": "nba-player:<id>\|nba-team:<id>", "side": ...}` (matched by name within the game's teams; ambiguous names are refused) |

- **Interval:** Max converts the result to the live forecast's Elo units (Elo = log-odds × 400 / ln 10) and
  shows Research's **95%** interval (normal approximation). The card's scenarios use **90%**; both come from
  the same estimate.
- **Agreement:** Max's what-if equals `scenario_probability()` to the digit (Max's integration tests).
- **Errors:**
  - A `ScenarioRefused` becomes `NOT_AVAILABLE` with Research's reason.
  - A player with no estimate becomes `NO_DATA`.
  - A player not shown by default becomes `NO_DATA` or `NOT_AVAILABLE` with the reason.
- **Rest difference:** "rest difference" between the two teams is not offered in free text. It needs both
  teams' rest days, which the forecast row does not carry.

## 4. Rules the combiner enforces (refuses, never repairs)

**Refused:**
- unknown fields, types or effects;
- the same player twice;
- a player whose estimate is for the other team;
- fewer than 5 games missed;
- two rest changes for one team;
- `rest_diff` together with any team-level rest change;
- any rest change when `baseline_includes` contains `"rest"`;
- an effect with no estimate (a bucket with no games);
- a baseline outside (0, 1).

**Assumptions** (also returned in the result's `assumptions`):
- Effects are independent and additive on the log-odds scale.
- Each effect's 95% bootstrap interval is treated as normal and combined in quadrature.
- The baseline is treated as fixed.

Real absences and schedule spots co-occur, so combined scenarios can double count partly even when nothing
is refused.

## 5. Verdicts and wording

- Card scenarios always carry `label: "ESTIMATE"`.
- A rest scenario's caveats say the effect is **unproven** (GP-REST INSUFFICIENT_EVIDENCE).
- Absence scenarios say that absences mix rest and injury, that the estimate is shrunk toward no effect, and
  that the 2026-27 roster is not verified.
- Max's overall verdict is "HYPOTHETICAL · Edge unverified". Experience's Ref line ends "Edge unverified:
  nothing shows this model beats the market".

## 6. Updates

- Max re-reads the two tables when their modification time or size changes, so new Research tables need no
  server change.
- A code change to `scenario.py` takes effect on server restart (Max's identity block records its sha256).
- Field names and meanings in this document are stable. Research adds fields only; it never renames or
  removes them without updating this contract.

## 7. Limits (stated in the tables and reports)

- Absence estimates are not injury effects. They mix rest, injury, suspension, illness and coach decisions.
- Shrinkage uses a single pooled prior. Stars' effects are likely pulled toward zero too much.
- Elo partly absorbs long absences.
- Rosters are not verified for 2026-27.
- 2025-26 neutral-site games are not flagged.
- Schedule effects are confounded with travel, opponent and planned rest.
