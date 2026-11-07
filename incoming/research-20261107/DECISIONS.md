# HeatCheck Research — decision log

Protocol `heatcheck-nba/1`. Decisions taken by HeatCheck-Research on 2026-11-07 ~15:15 London, **before any target-season outcome analysis**. Each overrides the conflicting text in `02_Pro_Research` or `DATA_PIPELINE.md` where noted. Changes after this point are appended with a timestamp, never edited in place.

## D1 — Season scope (overrides Research §03 multi-season split)
- Single target season: **2023–24 NBA regular season** (`shufinskiy/nba_data` files suffixed `_2023`; suffix = season start year per repo README).
- 2022–23 regular season used **only** as game results for Elo initial ratings. No 2022–23 features, labels or tuning beyond the frozen Elo constants in D6.
- Reason: Research §03 makes 2023–24 the final family, but DATA_PIPELINE §1 makes it the plumbing season. Plumbing on it would burn the final partition. With a ~20 h deadline a single season with a pre-registered within-season chronological split is the only feasible honest option.
- Consequence: final-set sample is small (see D4). All 2023–24 results are **pseudo-out-of-sample**: outcomes are public and may be memorised by any LLM role. Every output carries `data_mode=REAL_NBA_RETROSPECTIVE` and this caveat.

## D2 — Play-by-play provider
- Single provider for the first pass: **`cdnnba`** (NBA CDN live play-by-play). It has a per-game unique `orderNumber` sequence, wall-clock `timeActual`, `scoreHome/scoreAway` per action, and an `edited` timestamp.
- `nbastats_2023` (stats.nba.com v2) is used **only** as a reconciliation cross-check of home/away and final score. It is the same upstream organisation (NBA), so this is a consistency check, **not** an independent source.
- BALLDONTLIE cross-check: **not run** (no user key supplied in this session; outbound to that host not established). Coverage status: `UNVERIFIED_EXTERNAL`.
- No shot is ever stitched from `nbastats` into a `cdnnba` game.

## D3 — Event ordering
- Canonical sequence = `orderNumber` within game. `actionNumber` is **not** a sequence (6,152 inversions observed in 2023–24 under `orderNumber` sort).
- Steps where the game clock runs backwards under `orderNumber` are flagged; a shot whose pre-shot features depend on a flagged step gets those features set to missing (DATA_PIPELINE §3), not imputed.

## D4 — Splits (whole games, chronological by tip time)
- Order games by first `period start` `timeActual` (UTC), tie-break `gameId`.
- Fractions: **fit 50% / tune 15% / calibration 10% / final 25%** of games, cut on calendar-date boundaries so no date spans two splits.
- Game prediction does **not** fit a separate isotonic calibrator (~120 games would overfit). The calibration slice is used for reliability diagnostics only. For shot research it serves as an extra development slice.
- Game-ID lists are written and SHA-256 hashed before any model is evaluated. The final list goes into the custodian exposure ledger (D8).

## D5 — Game-prediction target and cutoff
- Canonical target: **home team wins** (incl. overtime), one row per game. A named-team probability for markets is p or 1−p, derived at display time with `outcome_direction` recorded. Never a second row.
- Cutoff convention: features use only games whose **US/Eastern calendar date is strictly earlier** than the target game's US/Eastern date. NBA teams never play twice on one date, so this is conservative and needs no exact tip-time claim. Declared cutoff UTC = 00:00 US/Eastern on game date.
- Neutral-site games keep a `neutral_site` flag. Home advantage is not applied to them in the Elo baseline.

## D6 — Baselines (frozen before final)
- B0: fit-split home-win rate.
- B1: Elo with carry-over: K=20, home advantage 100 Elo points, season carry-over = 0.75·rating + 0.25·1505, no margin-of-victory term. Constants are the conventional FiveThirtyEight-style defaults, **fixed a priori, not tuned**.
- Candidate C1: logistic regression on [Elo logit, rest differential (days, capped at 3), home back-to-back, away back-to-back], fitted on fit split, L2 C=1.0. Probability clip ε = 1e-6 for both models.

## D7 — Status enums
- Claim decision states: exactly `Shared_Protocol.decision_states` (SURVIVED_PROTOCOL, NOT_SUPPORTED, INSUFFICIENT_EVIDENCE, DATA_INVALID, BLOCKED).
- `AttackResult.status` (separate enum): `EXECUTED`, `UNSUPPORTED` (missing prerequisite), `UNDEFINED` (statistic undefined, e.g. zero denominator), `ERROR`. Any `UNSUPPORTED` mandatory attack forces the claim to BLOCKED or INSUFFICIENT_EVIDENCE, never a pass.
- Comparison status: `AVAILABLE`, `BLOCKED` + reason codes.

## D8 — Custodian ownership
- Research implements the **custodian library** (`heatcheck.custodian`): a persistent, file-backed, record-level exposure ledger with atomic reserve → spend, idempotent retry by job identity, and refusal of overlapping partitions under new family IDs. Max owns integration and access control around it (who may call it, process isolation). Until Max wraps it, isolation is **logical only** and labelled so (Research §06).

## D9 — Raw data redistribution
- The `nba_data` repo is Apache-2.0, but that does not establish upstream NBA data rights (Research §02). Raw CSVs are **not** redistributed. The deliverable ships a fetch manifest (repo URL, commit, file paths, SHA-256) plus derived tables for internal use only.

## D10 — Pre-registered final family for GAME_PREDICTION (appended 2026-11-07 ~15:25 London, before any model fit)
- Neutral-site games 2023–24 (source: Wikipedia 2023–24 NBA season / 2023 In-Season Tournament pages, checked 2026-11-07): 2023-11-09 ATL–ORL (Mexico City), 2024-01-11 BKN–CLE (Paris), 2023-12-07 both IST semifinals (Las Vegas). Spurs' Austin games stay home games (alternate site, not neutral).
- Final family (Holm at α=0.05 across both):
  - **H1**: C1 improves mean log loss over B1 (d = loss_B1 − loss_C1 > 0).
  - **H2**: B1 improves mean log loss over B0.
- Inference: paired per-game loss differences, **moving-block bootstrap on calendar days, block length 7 days**, B=10,000, seed 20261107. Percentile 95% CI. One-sided p = (1 + #{d*_centred ≥ d̄}) / (B+1).
- Usable-block rule: if the final span contains fewer than 5 non-overlapping 7-day blocks → INSUFFICIENT_EVIDENCE. Sensitivity (exploratory, reported, non-decisive): 14- and 28-day blocks.
- Practical floor: 0.002 nats mean log-loss improvement.
- Decision: SURVIVED_PROTOCOL iff Holm-adjusted p < 0.05 AND CI lower > 0 AND d̄ ≥ floor. NOT_SUPPORTED iff CI upper < floor. Otherwise INSUFFICIENT_EVIDENCE. Coverage loss for either model → that game uses its preregistered fallback (B0 for C1/B1 if a feature is missing) and is counted.
- Brier score reported alongside as a secondary metric, non-decisive.

## D11 — Pre-registered SHOT_ASSOCIATION development check (hot hand)
- Estimand: within player-game, P(make | previous 3 FGA in same player-game all made) − P(make | previous 3 all missed), pooled counts over all eligible player-games.
- Null: outcomes exchangeable within (player, game, shot value 2pt/3pt) strata. Permutation recomputes streak eligibility each draw. B=999, seed 20261107. One-sided p = (1+#{T* ≥ T})/(B+1).
- Known limitation, stated up front: within-stratum exchangeability ignores within-game difficulty drift and shot selection after makes. A rejection is therefore an association under this null, **not** evidence of a causal hot hand. Run on development games (fit+tune+calibration) only. Final shot games are not opened in this pass.
