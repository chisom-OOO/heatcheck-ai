# Scenario effects: the final format (for Research's research/scenario-effects)

Prepared by Max, 8 November 2026 (updated 01:35Z). Code: `heatcheck/agents/scenario.py`.
Until Research's branch is merged, the server uses `ResearchStub` and every game card says "no
scenarios for this game (Research's scenario functions (research/scenario-effects) are not merged
yet)". Switching to the real functions is one adapter class implementing the three calls below.

## 1. What the page receives: Experience's `heatcheck-scenario/1`, adopted unchanged

`GET /api/scenario?game_id=nba:0022600191[&team=<full team name>]` (team defaults to the home team,
the same team as the card's market comparison). The format is the one in `apps/web/HANDOFF.md`:

```json
{"format": "heatcheck-scenario/1", "status": "OK", "game_id": "nba:0022600191",
 "team": "Cleveland Cavaliers", "is_sample": false, "source": "...",
 "baseline": {"p_team_win": "0.661772", "forecast_id": "live-forecast:<sha256 of forecasts.json>"},
 "scenarios": [{"scenario_id": "...", "text": "The Knicks are on a back-to-back", "label": "ESTIMATE",
   "p_team_win": "0.69...", "range": {"low": "...", "high": "...", "level": "0.90"},
   "n": 1224, "n_unit": "games", "caveats": ["..."], "method": "...", "verdict": "NOT_TESTED",
   "change": {...}}],
 "failed_tests": [], "not_quantified": [], "verdict": "HYPOTHETICAL · Edge unverified"}
```

Max's additions, all ignored by Experience's current reader, so nothing it shows changes:
- `verdict` on each scenario: Research's own test result for that effect.
- `failed_tests`: effects whose own test FAILED. They are kept out of `scenarios` so they are
  never shown as a plain estimate.
- `not_quantified`: `{scenario_id, text, reason}` for a change with no number.
- `status: "UNAVAILABLE"` + `reason` when there is nothing to show.

Max computes `p_team_win` and `range` from your Elo shift with the live forecast's own formula
(p = 1/(1+10^(-(Elo_h - Elo_a + H)/400)), H = 100, or 0 at a neutral site), so the baseline and
scenario come from one model. Your function never returns a probability.

## 2. What Max calls: three methods

```python
provider.menu(ctx) -> list[change] | None        # the scenarios worth showing for this game
provider.estimate(change, ctx) -> dict           # one change
provider.points_to_elo() -> float | None         # Elo per game point, for user adjustments
provider.identity -> {"name", "version", "commit"}
```

`ctx = {"game": <forecast row: game_id, tip_utc, home_team(_id), away_team(_id), p_home_win,
elo_home, elo_away>, "home_court_elo": 100 or 0, "as_of_utc": "...Z"}`.

A change is `{"kind": "REST" | "PLAYER_OUT", "team": <full name>, "text": <one plain sentence>,
"detail": "back-to-back" ...}` or `{"kind": "PLAYER_OUT", "player": "...", ...}`. `menu` returns
the changes you can estimate from the schedule or your data. Free-text questions send the user's
confirmed change to `estimate` the same way.

`estimate` returns:

```json
{"status": "ESTIMATE", "elo_shift": -30.0, "elo_shift_range": [-55.0, -5.0], "level": 0.90,
 "n": 1224, "n_unit": "games", "verdict": "SURVIVED | INSUFFICIENT_EVIDENCE | FAILED | NOT_TESTED",
 "data_through_utc": "2026-11-06T07:00:00Z", "caveats": ["at least one"], "method": "one line"}
```

- `elo_shift` is for `change["team"]`: negative means that team gets worse. Same Elo units as
  the live forecast.
- **Required for an ESTIMATE:** `level` (the interval's coverage, in 0..1), an integer `n` ≥ 1, and at
  least one caveat. Without any one of them, the change goes to `not_quantified` with the reason;
  Max never invents a level or a caveat.
- `{"status": "NO_DATA", "reason": "..."}`, e.g. a player with no missed games, gives "No data"
  and no number.
- `{"status": "NOT_AVAILABLE", "reason": "..."}` gives "Can't quantify this with the current
  model" and no number.

## 3. Max's checks on top
- **SAMPLE_SIZE:** `n` < 30 adds a caveat on the card and a flag in the what-if.
- **ESTIMATE_STALENESS:** `data_through_utc` older than 400 days adds the same caveat and flag.
- **DOUBLE_COUNT:** a free-text what-if that combines a user adjustment with a PLAYER_OUT or REST
  estimate for the same team is flagged.
- **Verdict:** always "HYPOTHETICAL · Edge unverified" (Experience's Ref line ends "Edge unverified:
  nothing shows this model beats the market").

## 4. Free-text what-ifs (Max's POST endpoints, format `heatcheck-whatif/1`)
- `POST /api/route {message}` returns OPEN_BOARD, OPEN_CARD, SCENARIO or DIALOGUE.
- `POST /api/scenario {message[, game_id]}` returns the parsed changes for confirmation; no number.
- `POST /api/scenario/estimate` takes the confirmed interpretation, recalculates or estimates it,
  checks it, records it in the ledger, and returns baseline vs scenario.
- Changes the parser understands:
  - Neutral floor and home/away swap: the forecast's own Elo, exact.
  - Hypothetical market price.
  - User adjustments: "Your assumption, not modelled".
  - PLAYER_OUT and REST: your `estimate`.

## Stamp rule (8 Nov 2026, user's instruction; one rule for the API and the page)

| What the shown number depends on | Stamp |
|---|---|
| Data only: Research's estimates (preset `GET /api/scenario`, or typed player-out / rest) or the forecast's Elo model (neutral site, home/away swap) | **ESTIMATE** |
| Any number the user supplied: their own adjustment ("assume it costs Boston 5%") or a hypothetical market price, alone or combined with data | **YOUR ASSUMPTION** |
| A SAMPLE forecast | **SAMPLE** |
| Nothing could be quantified | **NO NUMBER** |

`POST /api/scenario/estimate` returns it as `stamp` (`heatcheck.agents.scenario.stamp_for`); preset
scenarios carry `label: "ESTIMATE"`. The page never decides the stamp: `whatifStamp(est)` in
`apps/web/web/whatif/whatif.js` shows the server's value (unknown values show NO NUMBER). The Ref
line keeps the verdict "HYPOTHETICAL · Edge unverified". Tests: `tests/integration/test_scenario.py`
(`test_stamp_rule_…`), `apps/web/tests/whatif.test.mjs` (fixture generated from the server code).
