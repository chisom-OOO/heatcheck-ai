# Live forecast file: heatcheck-live-forecast/1

Agreed 7 November 2026. Research writes `data/live/forecasts.json` on `research/live-forecast`.
Max and Experience build against the hand-made sample
`tests/fixtures/live_forecast/forecasts.SAMPLE.json` until Research pushes the real file.
Sample values are invented and must never be shown as real.

Validator: `heatcheck/contracts/live_forecast.py` (pure, stdlib only).

    uv run --frozen python -m heatcheck.contracts.live_forecast data/live/forecasts.json

API: `tools/serve_dialogue.py ... --live-forecast PATH` serves `GET /api/live-forecast`, which
re-reads and re-validates the file on every request:
`{"status":"OK","is_sample":bool,"file_sha256":str,"forecast":{...}}` or
`{"status":"UNAVAILABLE"|"DATA_INVALID","reason":str}` with no forecast values.

## Shape

```json
{
  "format": "heatcheck-live-forecast/1",
  "label": "DESCRIPTIVE FORECAST",
  "model": "B1 Elo, fixed constants (same code as final run receipt 3e238d2d)",
  "inputs_used": ["elo_rating_home", "elo_rating_away", "home_court"],
  "data_cutoff_utc": "2026-11-07T22:00:00Z",
  "source": {"results": "cdn.nba.com schedule JSON", "fetched_utc": "...", "sha256": "...",
             "cross_check": "balldontlie ... | NOT_RUN"},
  "backtest_2024_25": {"log_loss": 0.0, "brier": 0.0, "games": 0},
  "games": [{"game_id": "nba:00226xxxxx", "tip_utc": "2026-11-08T00:30:00Z",
             "home_team_id": "nba-team:1610612738", "away_team_id": "nba-team:1610612752",
             "home_team": "Boston Celtics", "away_team": "New York Knicks",
             "p_home_win": 0.0, "elo_home": 0.0, "elo_away": 0.0}]
}
```

## Rules the validator enforces

- Exactly these fields at each level; unknown fields are refused (coordinate any addition).
- Strict UTF-8 JSON: no NaN/Infinity, no duplicate keys, at most 2 MB.
- `format` and `label` are the literal strings above. `model` is non-empty text.
- `inputs_used`: 1..64 unique snake_case names. Heater may cite only these inputs.
- Timestamps are UTC with `Z`. `data_cutoff_utc` is strictly before every `tip_utc`.
- `game_id` is `nba:` plus the 10-digit NBA game id, unique in the file. Team ids are
  `nba-team:<NBA team id>`; home and away differ.
- Probabilities and Brier are JSON numbers in [0, 1] (not strings or percentages). Log loss and
  Elo are finite and >= 0. `backtest_2024_25.games` is an integer >= 0. `games` may be empty.
- `source.cross_check` is `NOT_RUN` or a result text starting with `balldontlie`.
- SAMPLE: a file is a sample when `source.results` starts with `SAMPLE`. A sample may put the
  literal `SAMPLE` in `fetched_utc` and `sha256`, so it never carries an invented hash. A
  non-sample file may not contain `SAMPLE` anywhere in `source`, and needs a real UTC fetch time
  and a lowercase sha256.

## Interpretation choices for Research to confirm

1. `cross_check` format: `NOT_RUN` or free text beginning `balldontlie`.
2. `sha256` is the hash of the fetched results payload bytes.
3. No consistency check of `p_home_win` against the Elo values (home-court constant not in file).

PASS means structure, units, namespaces and the cutoff rule hold. It is not a forecast-quality
gate and says nothing about whether any forecast is accurate.
