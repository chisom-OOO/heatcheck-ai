# Research status: live forecast pushed as a labelled FALLBACK

| | |
|---|---|
| Branch | `research/live-forecast` |
| File | `data/live/forecasts.json` (format `heatcheck-live-forecast/1`, label `DESCRIPTIVE FORECAST`; not a registered claim) |
| Validator | Max's `heatcheck.contracts.live_forecast` at `max/integrate-r001-e001@4930adb`: **PASS**, non-sample, 7 games, cutoff 2026-04-13T03:05:51Z |
| Log | `logs/live-forecast/fallback_run.log` |

## Why this is a fallback (instruction by the user, 23:1x UTC)

- `cdn.nba.com` returned Akamai "Access Denied" (HTTP 403) to this cloud container, even after the host was
  allowed. It also refused Max's Windows machine (curl and PowerShell, 22:57Z) and Experience's browser.
- So **no 2026-27 results were used**. The ratings are the 2025-26 end ratings carried once into 2026-27 by
  the frozen rule: 0.75 × rating + 0.25 × 1505.
- `data_cutoff_utc` is the end of the last completed game used, 2026-04-13T03:05:51Z (the last 2025-26
  regular-season game).
- **The game list is hand-copied, not fetched** (`data/live/raw/gamelist_handcopied_20261107.json`, with
  provenance per game):
  - six games copied by Experience from the NBA.com schedule page at about 22:30Z;
  - DEN@IND from Experience's E-001 GAME record;
  - Sunday's slate is **not included**, because no copy exists in the repository;
  - all seven games are assumed not to be at a neutral site.

## Model and sources

- **Model:** the B1 Elo exactly as in the 2023-24 final run (receipt `3e238d2d`): K 20, home court 100.
  Ratings are rolled 2022-23 → 2023-24 → 2024-25 → 2025-26 and carried into 2026-27.
- **Results sources:**
  - 2023-24 and 2024-25 from Research's builds;
  - 2025-26 from `shufinskiy/nba_data@46488f0f` `datasets/cdnnba_2025.tar.xz` (sha256
    `a5d1bed30778430816b755676649cb2e3690ea62df5d96f4d9d6e9a8b8839339`, git blob `5770f0a2…` matching the
    upstream tree, fetched 2026-11-07T22:53:11Z).
  - The 2025-26 neutral-site games are not flagged, so home court was applied to every game that season.
- **backtest_2024_25:** 1,230 games, log loss 0.6290, Brier 0.2196.
- **cross_check:** `NOT_RUN`.

## Forecasts (pre-tip; DEN@IND had already tipped at 22:00Z when this was published)

| Game | Away @ Home | p(home win) |
|---|---|---|
| nba:0022600189 | Denver @ Indiana | 0.308 |
| nba:0022600190 | Brooklyn @ Atlanta | 0.859 |
| nba:0022600191 | New York @ Cleveland | 0.645 |
| nba:0022600192 | Washington @ Oklahoma City | 0.941 |
| nba:0022600193 | Orlando @ Golden State | 0.528 |
| nba:0022600194 | Houston @ Phoenix | 0.563 |
| nba:0022600195 | San Antonio @ Portland | 0.444 |

**Caveat:** these probabilities ignore everything since April 2026: off-season moves, injuries and this
season's results. They are a descriptive output of the registered baseline, not a prediction claim and not
betting advice.

## Max's three format choices: confirmed

1. `cross_check` is `NOT_RUN` or free text beginning `balldontlie`. Confirmed; here it is `NOT_RUN`.
2. `sha256` is the hash of the fetched results payload bytes. Confirmed; here it is the cdnnba_2025 archive.
3. There is no check of `p_home_win` against the Elo values. Confirmed; home court (100) is stated in `model`.

## Next

If Max's balldontlie (or cdn.nba.com) data arrives, the forecast will be replaced by the full version, with
2026-27 results to date, a fetched game list and Sunday's slate.
