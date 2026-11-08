# Research status: live forecast adds Sunday's 7 games and makes game 189 a neutral site

| | |
|---|---|
| Branch | `research/live-forecast` |
| File | `data/live/forecasts.json`: 14 games, `DESCRIPTIVE FORECAST`, cutoff 2026-11-07T07:00:00Z |
| Validator | Max's `heatcheck.contracts.live_forecast` at `max/integrate-r001-e001@4930adb`: **PASS**, non-sample, games=14 |
| Log | `logs/live-forecast/balldontlie_run_with_sunday.log` |

## Sources, verified by Research

**NBA 2026-27 schedule PDF:**
- URL: `https://cdn.nba.com/manage/2026/08/2026-27-NBA-Regular-Season-Schedule-By-Date.pdf`.
- Fetched by Research at 2026-11-08T00:08:42Z (HTTP 200; this path was not blocked).
- sha256 `5e82e37ef1b19e226dee57be69958b95b5694516280d3034aa7c1d64292b3570`; the document is dated "as of
  August 13, 2026". It is not committed (NBA document); only its hash and URL are recorded.

**Checks against the PDF:**
- **Sunday's ids** `0022600196`–`0022600202` (supplied by the user) are the PDF's game numbers 196–202 on
  11/8/26.
  - Each game's teams and ET tip, converted to UTC, match the balldontlie record exactly.
  - Tonight's games 190–195 match the same way, so game number = id suffix.
- **Game 189:** listed as "Denver **vs** Indiana", 4:00 PM local / 5:00 PM ET, note **B: "Game to be played
  in Arena CDMX, Mexico City"**.
  - Its home-court term is removed (`neutral_site`, frozen formula p = 1/(1+10^(−(Elo_h − Elo_a)/400))).
  - Indiana stays the designated home team from the NBA.com game record.
- **Other neutral sites in the PDF:** only games 75 (Paris, 1/14/27) and 76 (Manchester, 1/17/27). None of
  the 132 completed games used was neutral, so the Elo updates are unchanged.

**Game list:** `data/live/raw/gamelist_20261107_08.json` records the PDF source per game. The forecast run
now **refuses** any listed game without an exact balldontlie match (teams, home/away, tip). All 14 match.

## Forecasts

The same ratings price both days: results through 2026-11-06 ET (rule D5). Saturday's results are not used
for Sunday.

| Game | Away @ Home | p(home win) |
|---|---|---|
| nba:0022600189 | Denver vs Indiana (neutral, Mexico City) | 0.197 (was 0.304 with home court) |
| nba:0022600190 | Brooklyn @ Atlanta | 0.864 |
| nba:0022600191 | New York @ Cleveland | 0.662 |
| nba:0022600192 | Washington @ Oklahoma City | 0.936 |
| nba:0022600193 | Orlando @ Golden State | 0.640 |
| nba:0022600194 | Houston @ Phoenix | 0.475 |
| nba:0022600195 | San Antonio @ Portland | 0.501 |
| nba:0022600196 | Philadelphia @ Chicago | 0.364 |
| nba:0022600197 | LA Lakers @ Detroit | 0.676 |
| nba:0022600198 | Utah @ Minnesota | 0.903 |
| nba:0022600199 | Brooklyn @ Dallas | 0.755 |
| nba:0022600200 | Boston @ Milwaukee | 0.267 |
| nba:0022600201 | New Orleans @ LA Clippers | 0.727 |
| nba:0022600202 | Miami @ Sacramento | 0.456 |

## Defect caught by the validator

My first rebuild's `model` text was longer than the format's 512-character limit, and Max's validator
returned **FAIL**. I shortened the text (now 329 characters; the details are in `source.results` and this
report), and the rebuild then passed. The failing file was not pushed.

## Checks

| Check | Result |
|---|---|
| `tests/test_live_forecast.py` (incl. a new "game not in balldontlie → refused" case) | **PASS** 4/4 |
| Max's validator | **PASS** (after the fix above) |
| DEN@IND published before tip | **No**: tipped 22:00Z; this is a pre-tip probability published late |
