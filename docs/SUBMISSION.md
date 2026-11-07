# HeatCheck: telling real effects from lucky patterns in NBA data

Draft for the judges, 7 November 2026. Every number below is copied from a committed evidence file or report.
The source is given next to each result. Nothing here is a projection.

## 1. The problem

Sports data are full of patterns that look meaningful and are not. Search enough splits of enough games and
something will always look significant: a "hot hand", a rest advantage, a clutch player. The usual failure
is not bad arithmetic. It is choosing what to test after seeing the data, testing many things and reporting
the winners, peeking at the evaluation set, and letting someone's confidence stand in for evidence.

HeatCheck is built to make those mistakes hard to commit and easy to detect. It does not try to find
betting edges. Statistical arbitrage, trade ranking and position sizing are out of scope, and any comparison
with market prices is descriptive only.

## 2. How HeatCheck works

A claim goes through four steps. Only the last two decide anything.

1. **Discoverer (runtime role "Jone") proposes.** It may only propose a claim from a registry of claims
   that have a defined test. A proposal that is not exactly a registered claim id is refused.
2. **Challenger attacks.** It selects the registered attacks: ways the claim could be wrong, such as
   too small a sample, a null-distribution check, or shot selection. The Referee computes the attacks the
   claim requires. A Challenger can add attacks but never remove a required one.
3. **The Referee decides, deterministically.** Plain code applies a fixed rule to the test results and
   returns one of five verdicts: `SURVIVED_PROTOCOL`, `NOT_SUPPORTED`, `INSUFFICIENT_EVIDENCE`,
   `DATA_INVALID` or `BLOCKED`. No language model's opinion or agreement counts as evidence.
4. **The evidence ledger records it.** Each decision is appended to an append-only, hash-chained ledger
   together with the plan, the data identity, the code identity and the attack results. A retry returns
   the original entry. An edited, deleted, inserted or reordered line is detected on read. The chain alone
   cannot detect lines cut from the end; comparing its head with a value recorded elsewhere can.

**What is built today** (Max's branch `max/integrate-r001-e001`):
- The proposer in the loop is a deterministic stand-in.
- A model-backed Challenger exists, but it can only add attacks. Under the current registry every applicable
  attack is already required, so it is not called.
- A language model (Meta `muse-spark-1.3`) is used in the live dialogue for two things only: mapping a
  user's question to a registered claim, and phrasing the explanation. A guard checks that every number
  in the model's text appears in the evidence record.
- In a live end-to-end test, the model mapped 6 of 6 questions correctly, and every verdict equalled the
  committed ledger entry (`reports/max/2026-11-07-2009-live-e2e-and-demo.md`).
- The model never changes a verdict.

## 3. The protocol

The safeguards are there so that a result reported at the end is the result that would have been reported
whatever the data had shown.

- **Chronological splits by whole game.** The 2023–24 regular season is cut on calendar dates:
  - fit: 619 games, 24 Oct – 19 Jan;
  - tune: 185 games;
  - calibration: 126 games;
  - final: 300 games, 7 Mar – 14 Apr.

  Game lists were hashed before any evaluation. Features for a game use only games played on earlier dates.
  Features for a shot use only earlier events in the same game. A test flips each shot's outcome and checks
  that the earlier rows do not change.
- **Pre-registration.** Hypotheses, test, null, thresholds, sample rules and seeds are written down and
  committed before the results they govern. This is in `handoff/research-20261107/DECISIONS.md` (D10, D11
  for 2023–24; D17 for 2024–25). The log is append-only: corrections are added, never edited in.
- **A custodian guards the final data.** It keeps a persistent ledger of which games have been used for
  final evaluation.
  - Before any final evaluation it reserves the games. It marks them spent before results leave.
  - It refuses any new evaluation that touches those games: renamed families, re-spelled ids and
    shot-level ids all map back to the same game.
  - It binds the reservation to a hash of the input data, so a run with changed data is not accepted as a
    "retry".
- **Sealed confirmatory data.** A whole season can be sealed before any claim is run on it. Only one
  pre-registered family can then open it: in full, once, and with exactly the sealed data.
- **Multiplicity correction.** Hypotheses evaluated together are corrected with the Holm method at α = 0.05.
  For survival, the decision rule also requires a confidence interval that excludes zero and a minimum
  practical effect.

## 4. Results so far, as recorded

All 2023–24 results are **pseudo-out-of-sample**. The outcomes are public and may be memorised by language
models. They come from one season of retrospective data (`shufinskiy/nba_data@46488f0f`, NBA CDN
play-by-play).

### 4.1 Game prediction, 2023–24 final split (300 games, run once)

Source: `handoff/research-20261107/evidence/game_prediction_final.json`, receipt `3e238d2d…`, plan `a8d81292…`.

| Model | Log loss | Brier |
|---|---|---|
| B0: home-win rate from the fit split (0.582) | 0.7022 | 0.2545 |
| B1: Elo with home advantage, fixed constants | 0.6379 | 0.2221 |
| C1: Elo + rest difference + back-to-backs | 0.6178 | 0.2108 |

| Hypothesis | Mean improvement (nats/game) | 95% CI | Holm p | Verdict |
|---|---|---|---|---|
| H2: Elo beats the base rate | +0.0644 | [+0.0106, +0.1282] | 0.0458 | **SURVIVED_PROTOCOL** |
| H1: rest/back-to-back adds to Elo | +0.0201 | [−0.0043, +0.0438] | 0.0490 | **INSUFFICIENT_EVIDENCE** |

- **Elo vs base rate survives, narrowly.** Its Holm-adjusted p is 0.046, just under 0.05. The final window
  spans 39 days, which is exactly the pre-registered minimum of five 7-day blocks. The 14- and 28-day
  robustness checks could not be computed: the window gives 2 and 1 blocks, below the minimum. So the
  verdict rests on the 7-day analysis alone.
- **Why rest is INSUFFICIENT_EVIDENCE although Holm p = 0.049 < 0.05.** Verbatim from
  `reports/research/2026-11-07-2015-rebuild-and-seal-binding.md` §1:

  > H1 (C1 rest/back-to-back vs B1 Elo) is INSUFFICIENT_EVIDENCE because the registered D10 rule requires all
  > three of "Holm-adjusted p < 0.05 **AND** CI95 lower bound > 0 **AND** mean ≥ 0.002 nats" for
  > SURVIVED_PROTOCOL. Its CI95 lower bound is **−0.00433**, so it fails the second condition even though
  > Holm p = 0.048995 < 0.05. It is not NOT_SUPPORTED either, because that needs the CI95 upper bound
  > (+0.0438) below the 0.002 floor; every other case is INSUFFICIENT_EVIDENCE (D10, `game_prediction.py final()`).

  On the development data C1 was slightly *worse* than Elo (−0.0047 nats on tune, −0.0009 on calibration).
  The sign change is not a finding.

### 4.2 Hot hand, 2023–24 development games only (exploratory)

Source: `handoff/research-20261107/evidence/hot_hand_dev.json`.
- 930 games, 165,710 field-goal attempts.
- P(make after 3 makes) = 0.4827; P(make after 3 misses) = 0.4777.
- Under the registered null (shuffling outcomes within each player's game and shot value), the expected
  difference is +0.0190. The observed +0.0050 is below that, with one-sided p = 0.996: **not rejected**.
- The naive +0.5 point gap is smaller than what shuffling alone produces.

### 4.3 Testing the tester (synthetic leagues)

Source: `handoff/research-20261107/evidence/harness_report.json`, `null_calibration.json`.

On simulated leagues where the truth is known, the hot-hand test:
- has a false-positive rate of 0.043 at α = 0.05 (1,000 null leagues);
- has power of 0.87 for a strong planted streak effect and 0.31 for a weak one.

It also fires 38% of the time when there is **no** streak but players' form drifts within a game. So a
rejection on real data would show an association, not a causal hot hand.

### 4.4 The agent loop on one real game

Source: `reports/max/2026-11-07-1641-agent-loop.md`. Max's loop ran on one bridged game (DEN–LAL,
`nba:0022300061`, 181 field-goal attempts):

| Claim | Verdict | Reason |
|---|---|---|
| Hot hand, 3 makes | INSUFFICIENT_EVIDENCE | 14 and 18 opportunities, fewer than the required 30 each |
| Hot hand, 2 makes | NOT_SUPPORTED | p = 0.239 |
| Rest | BLOCKED | no season view implemented |

This demonstrates the pipeline. It is not an NBA research result.

## 5. The sealed 2024–25 confirmatory test

To get a result that cannot have been tuned on the data, the whole 2024–25 regular season was sealed
**before** any claim was run on it. Source: `reports/research/2026-11-07-1757-confirmatory-seal.md`.

**The data.**
- 1,230 games, built from pinned archives (sha256, size and upstream git blob id verified).
- One game (`0022400072`) failed a score cross-check. Its scores were not inspected. By rule it is
  quarantined: still sealed, excluded from every test.
- Sealed at 2026-11-07T17:52:37Z under the custodian (seal `870135b5…`).

**Three pre-registered hypotheses**, frozen at 17:54:40Z and corrected together with Holm:
- **CONF-HA, home advantage:** in non-neutral games, home teams win more than half of the time.
  - Survives only if Holm p < 0.05, the CI excludes 0, and the excess is at least 1 percentage point.
  - Needs at least 1,000 games.
- **CONF-MOM, one-shot momentum:** a field goal is more likely after a made field goal than after a miss,
  beyond what shuffling within a player's game produces.
  - Survives only if Holm p < 0.05.
  - Needs at least 100,000 attempts.
- **CONF-HH, hot hand:** the same with three straight makes vs three straight misses.

**Development check on 2023–24** (exploratory, same code):
- home-win rate 0.553 over 926 games, which is below the 1,000-game minimum;
- momentum p = 1.0;
- hot hand p = 0.998.

**Reproducible from scratch.** The sealed season was rebuilt on a fresh machine: an empty directory, a fresh
clone of commit `e7e8857`, a fresh Python environment and fresh downloads of the pinned archives. All six
sealed tables matched the seal (**6/6, SEAL MATCH**). The whole rebuild took **1 min 57 s** on a 4-CPU Linux
machine with a warm package cache. Source: `reports/research/2026-11-07-2015-rebuild-and-seal-binding.md` §3;
script `reports/research/logs/rebuild/rebuild_2024-25.sh`; log `reports/research/logs/rebuild/fresh_rebuild_run.log`.

The confirmatory script refuses to run if a single byte of the sealed tables differs. It refuses before
reserving anything, and a test tampers each table in turn to check this (same report, §4).

**Results: NOT YET RUN.** Everything between the markers below is a placeholder. The confirmatory test is
reserved for the live demo and needs explicit authorisation. It will be replaced with the recorded output of
`confirmatory.py final` (`evidence/confirmatory-2024-25/final_result.json`), unchanged.

<!-- BEGIN PLACEHOLDER: 2024-25 confirmatory results — do not fill by hand -->

| Hypothesis | Sample | Estimate | 95% CI | p (one-sided) | Holm p | Verdict |
|---|---|---|---|---|---|---|
| CONF-HA home advantage | [PLACEHOLDER] | [PLACEHOLDER] | [PLACEHOLDER] | [PLACEHOLDER] | [PLACEHOLDER] | [PLACEHOLDER] |
| CONF-MOM one-shot momentum | [PLACEHOLDER] | [PLACEHOLDER] | n/a | [PLACEHOLDER] | [PLACEHOLDER] | [PLACEHOLDER] |
| CONF-HH hot hand | [PLACEHOLDER] | [PLACEHOLDER] | n/a | [PLACEHOLDER] | [PLACEHOLDER] | [PLACEHOLDER] |

Exposure receipt: [PLACEHOLDER] · Authorised by: [PLACEHOLDER] · Run at (UTC): [PLACEHOLDER] ·
Result file sha256: [PLACEHOLDER]

<!-- END PLACEHOLDER -->

## 6. Independent review and what it caught

A reviewer other than the authors replayed each milestone against the exact committed bytes, on their own
machine and their own data build. They wrote adversarial tests that should fail if a guarantee is false.

**RV-R1 (high severity): the final evaluation was not bound to its data.** Found in
`reports/review/2026-11-07-1642-r001-e001-replay.md`.
- **The defect.** The reviewer flipped the outcome labels of 40 final-split games and re-ran the final
  step. The custodian accepted the run as a harmless "retry" of the original receipt, and the Elo result
  changed from `SURVIVED_PROTOCOL` to `INSUFFICIENT_EVIDENCE`. The cause: the final step checked the split
  and the code, but copied the data hashes from the plan instead of recomputing them.
- **The fix** (`research/r001-guard-fixes`, code `c822b55`):
  - The final step now recomputes all seven table hashes from the actual input files. It refuses before
    reserving or scoring anything if any differs from the frozen plan.
  - The custodian binds each reservation to its input data.
  - Because the fix changed code inside the frozen code hash, the original plan was replayed through a
    recorded amendment that carries only the new code identity. The replay ran on the same data. It
    reproduced the same receipt and both verdicts to every digit.
- **Independent confirmation** (`reports/review/2026-11-07-1733-research-guard-fixes.md`). On their own
  build, the reviewer confirmed:
  - the tampered runs are refused, including with Python's assertions disabled;
  - a tampered public table is refused too;
  - an edited threshold is refused;
  - the replay matches exactly.

The same review process also caught:
- **RV-R2:** re-spelled game ids could reopen spent final games. Fixed, and confirmed with the reviewer's
  probes, which fail on the old code and pass on the new.
- **RV-AL1/AL2:** an evidence-ledger line could be edited and re-hashed, or deleted, without detection.
  Fixed with a hash chain on Max's branch.
- **RV-E1…E8:** robustness findings in the read-only market-quote adapter, handled on the Experience
  branches.

## 7. Known limits

- **Only one game is bridged into the shared record format.** The season-level analyses run in Research's
  own table format. Only `nba:0022300061` has been translated into the shared `heatcheck-records/1` bundle
  that the agent loop and the UI read. The game-prediction "season view" for the loop is not implemented,
  so the rest claim is `BLOCKED` there.
- **Isolation is logical, not enforced by the operating system.** The custodian and the evaluator run as the
  same user. A determined insider with file access could bypass them. The custodian also needs `fcntl`, so
  the confirmatory step runs on Linux, macOS or WSL, not native Windows. Reviewer sign-offs are recorded,
  not cryptographically verified.
- **The original 15:22 final run's inputs cannot be proven after the fact.** At the time it only copied the
  plan's data hashes. What is proven is weaker: today's data match the plan exactly, and replaying on them
  reproduces every output bit for bit. The ledger records this as `NONE_PREDATES_BINDING`.
- **Data rights.** The upstream repository is Apache-2.0 licensed, but that does not establish rights to the
  underlying NBA data. Raw files and built tables are not redistributed. Only fetch instructions, hashes and
  derived summaries are committed.
- **Other limits stated in the evidence:**
  - The second "source" for score reconciliation is from the same organisation. The independent
    BALLDONTLIE cross-check has not been run because no key was supplied.
  - Free throws are out of scope for shot claims.
  - Results come from a single season, and outcomes are public.
  - A rerun of the confirmatory step would rewrite its result file. The script is frozen, so the result
    must be committed immediately after the run.
