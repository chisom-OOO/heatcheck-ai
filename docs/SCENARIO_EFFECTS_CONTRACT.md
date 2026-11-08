# Scenario effects: what Max's scenario code expects from research/scenario-effects

Prepared by Max, 8 November 2026 (01:10Z). Code: `heatcheck/agents/scenario.py` (`EffectsProvider`).
Until Research's branch is merged, the app uses `ResearchStub`, which answers every PLAYER_OUT and
REST change with NOT_AVAILABLE and no number. Switching to the real functions is one adapter class.

## Calls

```python
provider.estimate(change: dict, ctx: dict) -> dict
provider.points_to_elo() -> float | None     # Elo points per game point, or None
provider.identity -> dict                    # name, version, commit
```

`change` is one confirmed change, exactly as the user confirmed it:

| kind | fields |
|---|---|
| `PLAYER_OUT` | `player` (as typed, e.g. "Donovan Mitchell"), `team` (full name or null), `source_text` |
| `REST` | `team` (full name or null), `detail` (e.g. "back-to-back", "2 days rest", "rested"), `source_text` |

`ctx` = `{"game": <forecast row: game_id, tip_utc, home_team(_id), away_team(_id), p_home_win,
elo_home, elo_away>, "home_court_elo": 100 or 0, "as_of_utc": "...Z"}`.

## Return value

```json
{"status": "ESTIMATE",
 "elo_shift": -40.0,
 "elo_shift_range": [-70.0, -10.0],
 "interval": "90% bootstrap",
 "n": 212,
 "verdict": "SURVIVED | INSUFFICIENT_EVIDENCE | FAILED | NOT_TESTED",
 "data_through_utc": "2026-11-06T07:00:00Z",
 "caveats": ["..."],
 "method": "one line"}
```

- `elo_shift` is for `change["team"]` (negative = that team gets worse), in the same Elo units as
  the live forecast. Max converts to the home-team side and to a probability with the forecast's own
  formula, so the baseline and scenario use one model.
- `status: "NO_DATA"` with `reason` (e.g. "no games without this player since 2023"): shown as
  "No data", no number.
- `status: "NOT_AVAILABLE"` with `reason`: shown as "Can't quantify this with the current model",
  no number.
- `verdict: "FAILED"`: shown with that verdict and left out of the scenario number.

## What Max's Challenger checks on top
- `n` < 30: SAMPLE_SIZE flag.
- `data_through_utc` more than 400 days before the scenario: ESTIMATE_STALENESS flag.
- The same team has a user adjustment plus a PLAYER_OUT or REST estimate: DOUBLE_COUNT flag.
- The verdict is always "HYPOTHETICAL · Edge unverified".

## Open request
`points_to_elo` lets "assume it costs Boston 3 points" become a number. Without it, a game-points
adjustment gives no number. Percentage-point and Elo-point adjustments already work.
