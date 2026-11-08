# HeatCheck: telling real effects from lucky patterns in NBA data

## Summary

HeatCheck is an AI researcher that tests its own ideas and separates robust discoveries from lucky findings,
using NBA data. Heater, an AI pundit, proposes; a Challenger attacks; a deterministic Referee decides by
pre-registered rules, explains each verdict from the ledger alone, and records it in a tamper-evident ledger.

- **Elo vs base rate** (2023–24, 300 held-out games): survives, narrowly (Holm p 0.046).
- **Rest/back-to-back:** refused by its own pre-registered rule despite p 0.049, because its confidence
  interval includes zero.
- **2024–25, sealed before any test and tested once:** home advantage survives (Holm p 0.0054); one-shot
  momentum and the hot hand are not shown (p = 1.0 each).

**What review caught:** independent review found that the final step accepted tampered outcome labels as a
"retry" (RV-R1). This was fixed, and the replay reproduced every digit.

**Demo:** `.\demo.cmd` (see README on `max/integrate-r001-e001`).

---

Draft for the judges, 8 November 2026. Every number is copied from a committed evidence file or report,
cited next to it. Nothing here is a projection.

## 1. The problem

Sports data are full of patterns that look meaningful and are not. Search enough splits of enough games and
something will look significant: a hot hand, a rest edge, a clutch player. The usual failures are choosing
the test after seeing the data, testing many things and reporting the winners, peeking at the evaluation
set, and treating confidence as evidence. HeatCheck makes those mistakes hard to commit and easy to detect.
It does not look for betting edges; market comparisons are descriptive only.

## 2. How HeatCheck works

1. **Heater proposes.** Heater is the user-facing name; the internal role is the Discoverer. A proposal must
   be a registered claim or an idea in a fixed grammar. Anything else is refused, never repaired.
2. **Challenger attacks.** It selects registered attacks: ways the claim could be wrong, such as small
   samples, null checks or shot selection. The Referee computes the required attacks. A Challenger can add
   attacks but never remove a required one.
3. **The Referee decides, deterministically.** Plain code applies a fixed rule and returns
   `SURVIVED_PROTOCOL`, `NOT_SUPPORTED`, `INSUFFICIENT_EVIDENCE`, `DATA_INVALID` or `BLOCKED`.
4. **The ledger records it.** Each decision is appended to a hash-chained ledger with the plan, data, code
   and attack results. Edited, deleted or reordered lines are detected on read.

**Heater and the Ref.**
- **Heater** is an AI-generated, original pundit character who improvises hot takes through a language model.
  - He is instructed never to state numbers, contradict the Ref, or imitate a real commentator.
  - A guard refuses any number not in the evidence record; on a failure he falls back to a fixed line.
- **The Ref** never improvises. No model is called. Its verdict and explanation are templates filled only from
  the ledger entry (`reports/max/2026-11-07-2059-deterministic-ref-recorded-finals.md`).

**The language model** (Meta `muse-spark-1.3`) does three constrained jobs, and never decides a verdict:
1. It routes a question to a registered claim.
2. It writes Heater's lines.
3. On the idea board, it turns a fan's message into ideas. Its answer is forced into a JSON schema whose
   values are the grammar's enumerations.

The 2023–24 game-prediction verdicts are in the ledger as **recorded references to custodian receipt
`3e238d2d`** (GP-ELO, GP-REST): copied and hash-bound, not recomputed.

## 3. The protocol

- **Chronological splits by whole game.**
  - The 2023–24 season is split into fit (619 games), tune (185), calibration (126) and final (300 games,
    7 Mar – 14 Apr). Lists were hashed before evaluation.
  - Features use only earlier dates (games) or earlier events (shots). A test flips each shot's outcome and
    checks that earlier rows are unchanged.
- **Pre-registration.** Hypotheses, tests, thresholds, samples and seeds are committed before the results
  (`DECISIONS.md`: D10, D11, D17).
- **A custodian guards final data.**
  - It reserves games before a final evaluation and marks them spent before results leave.
  - It refuses any new evaluation touching them; renamed families and shot-level ids map back to the game.
  - It binds each reservation to a hash of the input data, so changed data cannot pass as a retry.
- **Sealed confirmatory data.** A season can be sealed before any claim runs. Only one pre-registered family
  can then open it: whole, once, with exactly the sealed data.
- **Multiplicity.** Hypotheses tested together are corrected with Holm at α = 0.05. Survival also needs a
  confidence interval excluding zero and a minimum practical effect.

## 4. Results, as recorded

All results are **pseudo-out-of-sample**: outcomes are public and may be memorised by language models. Data:
`shufinskiy/nba_data@46488f0f` (NBA CDN play-by-play).

### 4.1 Game prediction, 2023–24 final split (300 games, run once)

Source: `handoff/research-20261107/evidence/game_prediction_final.json`, receipt `3e238d2d…`.

| Model | Log loss | Brier |
|---|---|---|
| B0: fit-split home-win rate (0.582) | 0.7022 | 0.2545 |
| B1: Elo with home advantage, fixed constants | 0.6379 | 0.2221 |
| C1: Elo + rest difference + back-to-backs | 0.6178 | 0.2108 |

| Hypothesis | Mean improvement (nats/game) | 95% CI | Holm p | Verdict |
|---|---|---|---|---|
| H2: Elo beats the base rate | +0.0644 | [+0.0106, +0.1282] | 0.0458 | **SURVIVED_PROTOCOL** |
| H1: rest/back-to-back adds to Elo | +0.0201 | [−0.0043, +0.0438] | 0.0490 | **INSUFFICIENT_EVIDENCE** |

- **Elo vs base rate survives, narrowly.** The 39-day window is exactly the minimum of five 7-day blocks. The
  14- and 28-day robustness checks could not be computed, so the verdict rests on the 7-day analysis alone.
- **Why rest is INSUFFICIENT_EVIDENCE although Holm p = 0.049 < 0.05.** Verbatim from
  `reports/research/2026-11-07-2015-rebuild-and-seal-binding.md` §1:

  > H1 (C1 rest/back-to-back vs B1 Elo) is INSUFFICIENT_EVIDENCE because the registered D10 rule requires all
  > three of "Holm-adjusted p < 0.05 **AND** CI95 lower bound > 0 **AND** mean ≥ 0.002 nats" for
  > SURVIVED_PROTOCOL. Its CI95 lower bound is **−0.00433**, so it fails the second condition even though
  > Holm p = 0.048995 < 0.05. It is not NOT_SUPPORTED either, because that needs the CI95 upper bound
  > (+0.0438) below the 0.002 floor; every other case is INSUFFICIENT_EVIDENCE (D10, `game_prediction.py final()`).

  On development data C1 was slightly worse than Elo; the sign change is not a finding.

### 4.2 Hot hand, development games, and testing the tester

- **Development games** (930 games, 165,710 field-goal attempts): P(make after 3 makes) = 0.4827 vs 0.4777
  after 3 misses. Shuffling within each player's game already produces +0.0190, more than the observed
  +0.0050, so one-sided p = 0.996: not rejected (`evidence/hot_hand_dev.json`).
- **Simulated leagues with known truth** (`evidence/harness_report.json`): false-positive rate 0.043 at
  α = 0.05, and power 0.87 (strong effect) or 0.31 (weak). Within-game form drift with no streak triggers it
  38% of the time, so a rejection shows association, not cause.

## 5. The sealed 2024–25 confirmatory test

Source: `reports/research/2026-11-07-1757-confirmatory-seal.md`.

**Data and seal.**
- 1,230 games from pinned archives (sha256, size and upstream git blob id verified).
- Game `0022400072` failed a score cross-check. Its scores were not inspected; by rule it is quarantined
  (sealed, excluded from every test).
- Sealed at 17:52:37Z (seal `870135b5…`).
- **Reproducible:** a fresh-machine rebuild (fresh clone of `e7e8857`, fresh environment and downloads)
  matched all six sealed tables (**6/6, SEAL MATCH**) in **1 min 57 s**. The script refuses if any byte of a
  sealed table differs.

**Pre-registration** (frozen 17:54:40Z; Holm across three):
- **CONF-HA:** home teams win more than half of non-neutral games. It needs Holm p < 0.05, a CI excluding 0,
  an excess of at least 1 point, and 1,000+ games.
- **CONF-MOM / CONF-HH:** a make is likelier after one make (or three) than after a miss (or three), beyond
  within-player-game shuffling. These need Holm p < 0.05 and 100,000+ attempts.

**The run.** Before the run, the custodian ledger held zero reservations on the 2024-25 season; the test was
run once, by a session that wrote none of the code.
- The operator was the adviser Claude session, standing in for the reviewer, with written authorisation.
- An independent rebuild matched the seal 6/6 beforehand. The run appended exactly one reserve and one
  spend, and Max's `verify_final_result` passed.

Source: `final_result.json` on `review/confirmatory-run@5f0a432`, copied exactly; run report
`reports/review/2026-11-07-2232-confirmatory-run.md`.

| Hypothesis | Sample | Estimate | 95% CI | p (one-sided) | Holm p | Verdict |
|---|---|---|---|---|---|---|
| CONF-HA home advantage | 1,224 games (5 neutral-site and 1 quarantined game excluded) | home-win rate 0.5449; mean excess over 0.5 = +0.0449 | [+0.0160, +0.0752] | 0.0018 | 0.0054 | **SURVIVED_PROTOCOL** |
| CONF-MOM one-shot momentum | 219,274 FGA (70 excluded: unresolved order) | P(make after make) 0.4667 vs after miss 0.4709; T = −0.0043, permutation null mean +0.0067 | n/a | 1.0 | 1.0 | **INSUFFICIENT_EVIDENCE** |
| CONF-HH hot hand (3 makes) | 219,274 FGA | P(make after 3 makes) 0.47265 vs after 3 misses 0.47266; T = −0.00001, null mean +0.0175 | n/a | 1.0 | 1.0 | **INSUFFICIENT_EVIDENCE** |

- Receipt `5cbb3222-181d-439d-9202-02a8d8030e4e` (not a retry). Authorised by Leo Nichols.
- Run 2026-11-07, 22:28:06Z – 22:30:38Z.
- Result file sha256 `d16245990d09663917743122d5edb8e032e570c630d979454ecb4c718f626dd3`.

**Meaning.**
- Home advantage met every condition of its rule (174 days, 24 blocks).
- Momentum and the hot hand are "not shown", not "disproved": no equivalence test was pre-registered. In both,
  the observed difference is below what shuffling alone produces, as in 2023–24.

## 6. The market board (descriptive, read-only)

The market board sets HeatCheck's descriptive Elo forecast beside the Polymarket price for tonight's and
Sunday's games. It flags gaps worth a human look; it does not claim an edge.

**The forecast** (`data/live/forecasts.json`, `research/live-forecast@e03629d`):
- **Model:** the registered B1 Elo, the same code as the 2023–24 final run (K 20, home court 100, fixed
  between-season regression).
- **Results:** 2023–24 to 2025–26 from `nba_data@46488f0f`; for 2026–27, the **132 completed games**
  through 6 November from Max's raw balldontlie pages (`eec051d`, hashes verified).
- **Data cutoff:** 2026-11-07T07:00:00Z, the last used tip time plus a 4-hour bound on game length.
- **Games:** 14 (Saturday and Sunday). Ids and game 189's neutral site (Arena CDMX, Mexico City, no home
  court) come from NBA.com and its 2026–27 schedule PDF; every game matches balldontlie on teams and tip
  time.
- **Backtest on 2024–25:** log loss 0.6290 and Brier 0.2196 over 1,230 games.
- **Not used:** injuries, lineups, trades or prices. Not a registered claim.

**Market data and verdicts** (Max `57e07fd`; Experience's read-only adapters):
- Polymarket mappings are VERIFIED against the stored rules text (16 checks each: teams, tip, overtime,
  cancellation, token).
- Kalshi mappings stay PROPOSED, because their rules text does not state how overtime counts. Kalshi cards
  therefore always show **"Can't compare"**.
- **The Ref has only two verdicts,** both deterministic templates:
  - **"Worth investigating · Edge unverified"** when the card is matched and the quote fresh;
  - **"Can't compare"** otherwise.

  It never says "bet" or "edge found".
- Heater may cite only the forecast's inputs; injuries and the like only as questions.
- Each investigation is recorded with timestamps, so it can be scored after the game.

**Example, live before tip:**
- Cleveland: model 0.662, Polymarket bid/ask 0.36/0.37.
- Oklahoma City: model 0.936, Polymarket 0.82/0.83.

Research checked Polymarket's raw payload: the Cleveland contract really is the Cavaliers' token.

**Read the gaps plainly:**
- A large forecast-vs-market gap most likely reflects what Elo does not know: injuries, lineups, trades and
  this season's changes.
- **No evidence shows this model beats the market.** No such evaluation has been run.

**What-if scenarios (ESTIMATE, not claims;** `research/scenario-effects`**).**

- **Player absence:**
  - Estimated from 2023–24 to 2025–26 as the team's result minus the Elo expectation, with and without the
    player.
  - Coverage: 1,203 player–team keys, 1,046 with at least 5 games missed.
  - Raw per-player intervals are noisy: 145 of the 1,046 exclude zero, where about 52 would by chance.
- **Shrinkage:** empirical-Bayes shrinkage toward zero.
  - The spread of true effects is τ = 0.080 in win probability (from 489 well-covered players), and it
    leaves **35 of 1,046** intervals excluding zero.
  - The shrunk value is the default; the raw value appears only in the evidence drawer.
  - Players with a risk flag (small n, team change, garbage-time appearances) are not shown.
- **Schedule:** back-to-back −0.053 (95% −0.079 to −0.028), 3-in-4 −0.029; both shown as **unproven**
  (registered rest test: INSUFFICIENT_EVIDENCE).
- **Combination:** on the log-odds scale, assuming independence; overlapping rest changes are refused.
- **Example:** Cleveland without J. Allen is −0.062 (raw −0.172). With New York also on a back-to-back,
  Cleveland's 0.662 becomes **0.649** (95% 0.513–0.764).
- **Limits:** absences mix rest and injury; 2026–27 rosters are unverified; one pooled prior likely **pulls
  stars' effects toward zero too much**.

## 7. The idea board: HeatCheck testing its own ideas

Grammar: `docs/IDEA_GRAMMAR.md`; runner and results: `research/idea-family` (report
`reports/research/2026-11-07-2234-idea-family.md`).

**How it works.**
- Heater's proposer (Max, `heatcheck/agents/idea_proposer.py`) turns a fan's message into hypotheses from two
  templates:
  - home-win rate split by one game feature;
  - make rate after a shot condition.

  Parameters are enumerated values only. Invalid output is refused, never repaired.
- Research's runner **registers every idea before computing**, runs fixed permutation tests, and applies
  **Holm across every idea in the family**.
- A survivor is a `CANDIDATE`, never `SURVIVED_PROTOCOL`; only development games are read.

**Results so far.**
- **Heater-proposed, keyword fallback** (same question, Max `e1c2dc3`): two ideas, both NOT_A_CANDIDATE
  (away team more rested: raw p 0.030, Holm 0.060).
- **Heater-proposed, model** (one `muse-spark-1.3` call, Max `c15abf7`; Research checked the raw model text
  matches the request): five rest ideas, all **NOT_A_CANDIDATE**.
  - The strongest, away team more rested, had p 0.043 and Holm 0.215.
  - Two of the five ideas were the same condition under different names; the grammar does not yet catch that.
  - Both Heater families agree with the registered rest verdict: not shown.

The families below were written by Research to exercise the machine.
- **Development data, 12 ideas:**
  - Both planned positive controls became CANDIDATE: strong Elo favourites win more, and 3-pointers go in less
    (Holm p 0.012 each).
  - Two period effects were also CANDIDATE: 4th-quarter shots go in less, and 1st-quarter shots more, than
    shuffling predicts. These are associations only; shot difficulty is not controlled.
  - No streak idea came close.
- **Planted-truth league** (hot-hand effect γ = 0.30, 13 ideas, truth revealed only after results):
  - **1 of 9** planted effects found, **0 false candidates**.
  - The directly planted after-3-makes idea had raw p 0.020. **Holm across 13 ideas** raised it to 0.24, so
    it was missed.
  - Testing many ideas at once costs power; a proposer should send few, focused ideas.
- **Null league:** 12 of 12 nulls correctly not flagged, 0 false candidates.
- These are single leagues, so the figures are counts, not rates.

## 8. Independent review and what it caught

A reviewer who wrote none of the code replayed milestones on their own data build, with adversarial tests.

**RV-R1 (high): the final evaluation was not bound to its data**
(`reports/review/2026-11-07-1642-r001-e001-replay.md`).
- **The defect:** with 40 final-game labels flipped, the custodian accepted the run as a "retry", and Elo's
  verdict changed to INSUFFICIENT_EVIDENCE. The final step copied the data hashes from the plan instead of
  recomputing them.
- **The fix** (code `c822b55`):
  - The final step recomputes all seven table hashes from the inputs, and refuses before reserving if any
    differs.
  - The custodian binds each reservation to its data.
  - The plan was replayed through a recorded code-only amendment on the same data. It reproduced the receipt
    and both verdicts to every digit.
- **Confirmed independently** (`reports/review/2026-11-07-1733-research-guard-fixes.md`): tampered labels or
  tables and an edited threshold are all refused, and the replay matched exactly.

**Also caught:**
- RV-R2: re-spelled game ids could reopen spent games. Fixed and confirmed.
- RV-AL1/AL2: ledger lines could be edited or deleted undetected. Fixed with a hash chain.
- RV-E1…E8: market-adapter robustness findings, handled by Experience.

## 9. How this was built

- **Four Claude coding sessions:**
  - integration ("Max"): orchestration, API, ledger;
  - Research: data, statistics, custodian, pre-registration;
  - Experience: UI, Heater character, read-only market adapters;
  - independent reviewer, who wrote none of the code it reviews.

  They coordinated through GitHub branches and committed reports (commit, commands, raw output,
  PASS/FAIL/NOT_RUN).
- **Models:** Meta `muse-spark-1.3`, for the three jobs in §2. Heater's art is AI-generated with Google
  Gemini; the credit is recorded on `experience/heater-character@1560525` (`apps/web/web/heater/states.html`
  header and `README.md`).
- **Prepared before the event.** These were committed on 7 November:
  - the repository scaffold and tooling configuration, derived from a 6 November preparation scaffold;
  - the three role specifications (commit `5be39a7`, 12:07 UTC);
  - the data pipeline specification (`c1944de`, 15:04 UTC).

  An earlier Discoverer plan is dated 14 October. The organisers' ruling on pre-event reuse is not recorded
  (`ELIGIBILITY.md`).
- **HeatCheck replaced an earlier idea, BreakPoint.** Its working tree was archived separately. None of its
  code or results is used here.

## 10. Known limits

- **One game bridged.** Only `nba:0022300061` is in the shared record format that the agent loop reads.
  Season-level analyses run in Research's own tables, and the loop cannot compute game-prediction claims
  itself.
- **Isolation is logical, not enforced by the operating system,** and reviewer sign-offs are not
  cryptographically verified.
- **The 15:22 run's inputs cannot be proven after the fact.** It only copied the plan's data hashes. What is
  proven: today's data match the plan, and replaying on them reproduces every output bit for bit
  (`NONE_PREDATES_BINDING` in the ledger).
- **Data rights.** The upstream repository is Apache-2.0 licensed, which does not establish rights to the
  NBA data. Raw files and built tables are not redistributed, with one exception: the raw balldontlie pages
  committed for the live forecast, whose terms are not reviewed here.
- **Other limits:**
  - The score reconciliation's second source is from the same organisation, and no independent cross-check
    has been run.
  - Free throws are out of scope.
  - Results come from a single season with public outcomes.
  - Holm applies within a family, not across all families ever tried.
  - Scenario shrinkage uses one pooled prior, so stars' absence effects are likely understated.
  - Research's confirmatory script would rewrite its result file on a rerun; Max's lane refuses to run it
    again.
