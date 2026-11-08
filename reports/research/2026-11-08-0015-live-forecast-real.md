# Research status: live forecast rebuilt from 2026-27 results (replaces the fallback)

| | |
|---|---|
| Branch | `research/live-forecast` |
| File | `data/live/forecasts.json` (label `DESCRIPTIVE FORECAST`; not a registered claim). Replaces the FALLBACK of `69158d6`. |
| Validator | Max's `heatcheck.contracts.live_forecast` at `max/integrate-r001-e001@4930adb`: **PASS**, non-sample, 7 games, cutoff 2026-11-07T07:00:00Z |
| Log | `logs/live-forecast/balldontlie_run.log` |

## Data

- **2026-27 results:**
  - Max's raw balldontlie `/v1/games` pages, `max/nba-schedule@eec051d`, fetched 2026-11-08T00:01:33Z to
    00:04:30Z from his machine.
  - Copied unchanged to `data/live/raw/balldontlie/`. All 14 page sha256 values and `manifest.json`
    (`89bc1591…`) match his commit message.
  - `source.sha256` is the sha256 over the per-file hash list, because there are 14 files.
- **Games used:** 132 completed 2026-27 regular-season games on US/Eastern dates before 2026-11-07 (rule D5).
  None of them was postponed.
- **`data_cutoff_utc`** = the last used game's tip plus a 4-hour upper bound on game length,
  2026-11-07T07:00:00Z. balldontlie gives tip times, not end times. It is before every forecast tip.
- **Earlier seasons** are unchanged: 2023-24 and 2024-25 from Research's builds; 2025-26 from
  `nba_data@46488f0f` `cdnnba_2025`. Between seasons, the frozen carry rule 0.75 × rating + 0.25 × 1505
  applies.
- **Game list:** the hand-copied list (`data/live/raw/gamelist_handcopied_20261107.json`), which supplies the
  NBA game ids. It was **checked against balldontlie**: all 7 games match in teams, home/away and tip time.
- **Team mapping:** balldontlie abbreviations map to NBA team ids by tricode. All of them map.
- **Not included:** Sunday's 7 games. They are in balldontlie, but there is no NBA game id for them yet.
- **Neutral sites:** not flagged for 2025-26 or 2026-27, so home court is applied everywhere.
- **cross_check:** `NOT_RUN`. balldontlie is the primary source here, not an independent cross-check.

## Forecasts (pre-tip; DEN@IND tipped at 22:00Z, before this was published)

| Game | Away @ Home | p(home win) | Fallback (no 2026-27 results) |
|---|---|---|---|
| nba:0022600189 | Denver @ Indiana | 0.304 | 0.308 |
| nba:0022600190 | Brooklyn @ Atlanta | 0.864 | 0.859 |
| nba:0022600191 | New York @ Cleveland | 0.662 | 0.645 |
| nba:0022600192 | Washington @ Oklahoma City | 0.936 | 0.941 |
| nba:0022600193 | Orlando @ Golden State | 0.640 | 0.528 |
| nba:0022600194 | Houston @ Phoenix | 0.475 | 0.563 |
| nba:0022600195 | San Antonio @ Portland | 0.501 | 0.444 |

`backtest_2024_25`: 1,230 games, log loss 0.6290, Brier 0.2196.

**Caveat:** this is the registered Elo baseline only, with no injuries, rosters or market information. It is
descriptive, not a claim and not advice.
