# Research status: calibration check of the live Elo (descriptive; no model change)

| | |
|---|---|
| Branch | `research/calibration` (from `research/live-forecast@e03629d`) |
| Script | `handoff/research-20261107/scripts/calibration_check.py` |
| Output | `data/calibration/elo_calibration_check.json` (full reliability tables, intervals) |
| Log | `logs/calibration/run.log` |
| Label | **DESCRIPTIVE.** This is not a registered test, and nothing in the model changes before the deadline. |

## What was checked

- **Model:** the live forecast's B1 Elo, with constants frozen since the 2023-24 run (K 20, home court 100,
  carry 0.75 × rating + 0.25 × 1505).
- **Pre-game only:** ratings update only from results on earlier dates, so every probability is pre-game.
- **Out-of-sample:** neither season below was used to set any constant.
- **Seasons:**
  - 2025-26, all 1,230 regular-season games (`nba_data@46488f0f`);
  - 2026-27 to date, 132 completed regular-season games, 2026-10-20 to 11-06 (Max's balldontlie pages,
    `eec051d`).
- **Comparisons:** B0 = 0.582, the registered 2023-24 fit-split home-win rate (frozen), and a 50% coin for
  reference.

## Scores

| Season | n | Elo Brier | Elo log loss | B0 Brier | B0 log loss | Coin Brier | Coin log loss |
|---|---|---|---|---|---|---|---|
| 2025-26 | 1,230 | **0.2136** | **0.6180** | 0.2478 | 0.6887 | 0.2500 | 0.6931 |
| 2026-27 to date | 132 | **0.2210** | **0.6282** | 0.2542 | 0.7018 | 0.2500 | 0.6931 |
| Combined | 1,362 | **0.2143** | **0.6190** | 0.2484 | 0.6900 | 0.2500 | 0.6931 |

Elo still clearly beats the base rate on both seasons, as it did in the registered 2023-24 test.

## Home-win rate: mean predicted vs actual

| Season | Mean predicted home win | Actual home-win rate | Predicted − actual | 95% interval (whole dates resampled) |
|---|---|---|---|---|
| 2025-26 | 0.6236 | 0.5545 | **+0.069** | [+0.045, +0.093] |
| 2026-27 to date | 0.6300 | 0.5152 | **+0.115** | [+0.030, +0.184] |
| Combined | 0.6242 | 0.5507 | **+0.074** | [+0.050, +0.097] |

**Yes: the home win probability is systematically too high.**
- **By how much:** about **7 points on average** in 2025-26 (+6.9, 95% interval +4.5 to +9.3).
- **2026-27 so far:** larger, about 11 points, but on only 132 games, with a wide interval.
- **Context:** the confirmatory run measured an actual home-win rate of 54.5% in 2024-25, in line with
  2025-26's 55.5%.
- **The size of the gap in Elo terms:** a home-court value of about **42 Elo points**, instead of the frozen
  100, would make the mean predicted rate match 2025-26. It is about 38 points over both seasons. These are
  descriptive figures, not a fitted or adopted change.

## Reliability, 2025-26 (10% bins; full tables for both seasons in the JSON)

| Predicted bin | n | Mean predicted | Actual (Wilson 95%) | Predicted − actual |
|---|---|---|---|---|
| 0.1–0.2 | 10 | 0.159 | 0.000 (0.000–0.278) | +0.159 |
| 0.2–0.3 | 54 | 0.261 | 0.167 (0.090–0.287) | +0.095 |
| 0.3–0.4 | 104 | 0.352 | 0.308 (0.227–0.402) | +0.045 |
| 0.4–0.5 | 169 | 0.456 | 0.349 (0.281–0.424) | +0.107 |
| 0.5–0.6 | 177 | 0.549 | 0.446 (0.375–0.520) | +0.103 |
| 0.6–0.7 | 232 | 0.652 | 0.621 (0.557–0.681) | +0.031 |
| 0.7–0.8 | 249 | 0.752 | 0.679 (0.618–0.734) | +0.073 |
| 0.8–0.9 | 192 | 0.845 | 0.797 (0.734–0.848) | +0.048 |
| 0.9–1.0 | 43 | 0.921 | 0.860 (0.727–0.934) | +0.060 |

**Every bin over-predicts the home team.** That pattern is a shift, a home edge that is too large, rather than
probabilities that are too extreme in both directions. The 2026-27 bins (n 3–33 each) show the same direction
in 6 of 8 bins.

## What this means for the live demo

- **Max's 12-of-13 home-side observation is consistent with this.** Elo gives the home team about 7 points
  too much on average, so the forecast-vs-market gap on a home team is partly the model's own bias, not
  information the market lacks.
- **The board should say so.** The existing caveat ("gaps most likely reflect what Elo doesn't know") now has
  a measured component: Elo's home edge is too large by about 7 points.
- **No model change before the deadline,** as instructed. A home-court recalibration would need its own
  pre-registered plan and an evaluation on games not used to choose it.

## Assumptions and limits

- Neutral-site games are not flagged in 2025-26 or 2026-27, so home court is applied to all of them. Removing
  a handful of neutral games would not move a 7-point average gap materially.
- The 2026-27 sample is small: 132 games over 18 days.
- The interval resamples whole calendar dates; it does not model dependence across teams over time.
- The "implied home court" is computed on the same games it describes, so it is a descriptive measure only.
