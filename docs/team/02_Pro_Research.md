# HeatCheck - research, data and adversarial validation

Version 1.1 - 7 November 2026. For Claude Pro / Research. Latest setup: Max plus TWO Pro coding sessions on THREE computers. Runtime research agents are separate product roles. This is a proposed reproducible method and build brief; no data, calibration, profitable signal or scanner result is claimed tested.

## 01 / What you own and what counts as evidence

Own canonical NBA data/feature validation, pure statistical kernels, attack registry, simulation families, blind truth scoring, probability evaluation and pure market-quote normalisation/comparison math. Max owns orchestration/contracts/API/ledger; Experience owns actual venue adapters and the interface. Freeze typed examples with both before parallel coding. Max independently replays your numerical oracles; you review its DSL, registry/authority and sealed-data boundaries.

Deliver distinct research paths using the shared canonical codes. SHOT_ASSOCIATION tests basketball claims such as hot-hand/clutch under an explicit observational null. GAME_PREDICTION tests whether pre-game information improves forecasts on unseen games. MARKET_COMPARISON displays a supported NBA forecast beside a correctly matched timestamped quote. It is not a trading-opportunity scanner or profit claim. None of these channels is proof of the others.

The Challenger proposes attacks and rival explanations; deterministic functions produce all statistics and evidence plots. A referee interprets the frozen protocol. Preserve NOT_SUPPORTED, INSUFFICIENT_EVIDENCE, DATA_INVALID and SURVIVED_PROTOCOL as different states. Failure to reject a null is not proof it is true; a large plausible effect can still lack data.

Use the Heat Check harness to test the tester: known nulls, known signals, confounders, masked signals, hidden truth and an untouched generator family. Measure both false discoveries and power. A rule that rejects everything gets low false discovery and zero usefulness; a rule that accepts everything fails under nulls.

All numbers below are hand-checkable fixtures or proposed defaults, not observed performance. Record exact method versions, inputs, seeds, effective sample units, missingness and assumptions. No model-written numerical result, fabricated log, calibrated-label shortcut or source-plan feature count closes an acceptance gate.

<!-- PAGE -->

## 02 / Data acquisition and reproducible provenance

First inspect a small actual source slice, not a promise that every field exists. shufinskiy/nba_data advertises bulk play-by-play/shot datasets through 2024/25, with source-specific coverage. Verify files, hashes, completeness and the needed schema. The repository's Apache licence is not independent proof of every upstream data/redistribution right [S3]. Do not publish bulk raw data by default.

nba_api is a client for NBA endpoints, not a guaranteed available historical service [S4]. BALLDONTLIE documents free teams/players/games but paid access for several richer endpoints, including injuries and odds; its free account is rate-limited [S5]. Therefore start game-based studies from actually available results and use bulk shot data for shot questions. Current injuries are not historical injury snapshots. The Odds API's historical endpoint is paid [S18]; do not silently substitute today's odds into old games.

Support a licensed user CSV/Parquet as a first-class adapter with explicit mapping/preview. No fake field inference: distinguish absent, unknown, zero, not applicable and estimated. A provider error or partial page pull blocks dataset readiness. Follow source rate limits and terms; do not evade access controls with fake identities or proxy rotation.

For every raw object store source/URL or file identity, retrieval UTC, provider timestamp if present, date/season scope, schema version, content SHA256, row count, licence/allowed-use note and completeness status. Store revisions as new snapshots. A source says '2024/25' does not prove the entire season was downloaded or every game has shots.

Canonical games: game_id, season, scheduled/actual tipoff UTC, event status, home/away IDs, final scores and result availability, neutral/postseason flags. Canonical shots: event ID/order, player/game/team, pre-shot context, type/distance/zone, made outcome, and source/time availability. Free throws additionally identify trip and attempt order. Reconcile game totals, duplicate IDs, clocks, ties, overtime, corrections and cancellation/postponement policies before analysis.

<!-- PAGE -->

## 03 / Causality of information and frozen splits

Game-level unit is one game, not duplicated home/away rows. The target is home victory in a completed game; one game's labels must not appear in two folds. Predictions bind a specific pre-game cutoff. Features may use only prior completed games whose outcomes were available at that cutoff. Test ordering on same-day fixtures, overtime, postponed games and season boundaries.

Do not use current full-season averages, final standings, corrected rosters, actual minutes, post-game injury labels or closing prices collected after the declared decision time. A date-only file cannot support a precision claim about a one-hour pre-tip cutoff without a documented timing convention. Retrospective admissibility is distinct from proven historical publication timing.

Shot pitfalls: an actual 'assisted' field is often known only after a made shot, and can encode the label. Exclude it from pre-shot expected-FG models unless a genuinely prior observable is established. Reconstruct margin before the shot, not after its points. Streaks reset at the registered boundary (e.g. player-game); previous-outcome features never include the current shot. Missing clocks/difficulty are not zero values.

Proposed bulk-data split if complete and exposure-audited: exploration through 2021/22, development validation 2022/23, final family on 2023/24 and 2024/25. Use explicit season IDs/dates in a manifest; adjust before seeing final results if availability differs. Any 2025/26 file is another retrospective period, not automatically untouched. Future 2026/27 games count as prospective only after a recorded lock and real outcome arrival.

Historical outcomes are public and LLMs may have memorised them. Audit prior exposure and label pseudo-out-of-sample when necessary. A local vault cannot erase that exposure. Fit transformations, priors, difficulty models and calibration on authorised earlier data. Freeze code/config/feature/baseline/coverage and all analysis choices before protected runs. The same exposure rule applies to simulator truth and held-out generator families. The final_epoch_id registry covers underlying record/group IDs, persists across restarts and forbids new family IDs from reopening exposed partitions; exact retry/replay retains the original identity and exposure receipt.

<!-- PAGE -->

## 04 / Luck-versus-skill kernels and exact fixtures

For a registered binomial proportion with s successes out of n comparable trials and fixed Beta(a,b) prior: posterior is Beta(a+s,b+n-s), mean (a+s)/(a+b+n), variance (a+s)(b+n-s)/[(a+b+n)^2(a+b+n+1)]. Prior fitting uses development data only. n=0 returns the prior with 'no observations', not a measured talent estimate.

Golden fixture: a=b=2, s=8, n=10 gives posterior Beta(10,4), mean 5/7 and variance 2/147. Raw rate is 0.8. Validate against an independently evaluated conjugate calculation and library distribution moments. Intervals are model-based posterior intervals, not proof of player ability or causal effects.

Do not apply a beta-binomial indiscriminately to weighted statistics such as TS%, to changing shot difficulty or to dependent attempts. Introduce a suitable observation model or leave the statistic unsupported. Hierarchical Bayes and dynamic talent remain useful extensions after simpler kernels are checked; no need to train a new language model.

For a fixed population/model, compare raw versus shrunk estimates and evaluate next-period predictive loss. Conditional Binomial sampling variance is p(1-p)/n; the variance decomposition must retain heterogeneity and unequal counts. A universal 'half luck until N shots' claim is invalid without specifying population, observation model and estimation uncertainty.

Split-half reliability: define grouping and construct comparable halves without splitting dependent trip/game structure arbitrarily. Show correlation, clustered uncertainty and sample sizes. The Spearman-Brown transformation assumes parallel halves; negative/unstable reliability is not clipped into apparent confidence. Repeated random splits do not create independent datasets. Low measured reliability can mean insufficient data or changing roles, not absence of skill.

Use simulation-based power/detectability before interpreting absence of effects. Report the assumed effect scale, prevalence, generator, eligible sample, desired power and Monte Carlo uncertainty. 'Need 300 more attempts' is a model-dependent estimate, not a universal guarantee.

<!-- PAGE -->

## 05 / Hot hand, clutch and the attack registry

Each attack has applicability, null/estimand, required fields, dependence assumptions, fixed parameters, compute limit, statistic/interval/p-value method and missing-data behaviour. Challenger may choose optional registered attacks but cannot skip mandatory ones. A missing prerequisite means UNSUPPORTED, not a clean pass.

Hot hand: define within-player/game sequences, streak length, shot type, eligible attempts and the exact conditional estimator. Miller/Sanjurjo identify finite-sequence selection bias in common streak statistics; do not assume the naive null is zero [S8]. Use exact enumeration on tiny cases and a valid design-specific randomisation method that recomputes the statistic/eligibility for each resample. Do not add a universal fixed 'correction'.

Permutation validity requires exchangeability under the declared null. Player/game/zone strata do not automatically preserve fatigue, drift or endogenous difficulty. Overly fine strata can leave almost no legal permutations. A fitted-conditional or parametric-bootstrap alternative must be specified and checked under null generators; random shuffling is not a general cure. Missing conditional denominators return an explicit undefined statistic.

Clutch: predeclare time/margin window, population, difficulty adjustment and trait versus one-season association. Specification curves show sensitivity across defensible definitions; the fraction of significant variants is descriptive unless a valid global test reruns the entire selection procedure. Selection of extreme players must be simulated under the null to test regression to the mean.

Team/home/rest/coaching: control or compare against strength and schedule where observable. Coaching changes are endogenous; a post-change bump is not automatically a causal coaching effect. The bubble is a useful stress context, not a randomised crowd experiment. Negative controls must be genuinely null by design: jersey number or weekday can correlate with real covariates.

Mandatory families: input/causal leakage; selection/null; difficulty/confounding when supported; multiplicity; time replication; influence/coverage; and uncertainty/power. Record counterexamples, inconclusive results and narrower claims. One rebuttal can clarify; a materially changed estimand is a new registered hypothesis, not a free extra look.

<!-- PAGE -->

## 06 / Planted leagues and hidden truth

Start with two or three explicit mechanisms: shot streak dependence, a clutch shift and game-level home/rest effects. Keep shot probability, game-score points and rating units distinct. For shot i use logit(p_i)=player_zone_intercept + difficulty_terms + gamma_logodds*streak_indicator. A +0.04 coefficient is log-odds, not +4 percentage points. If the desired effect is a probability increment, solve the corresponding logit change and document bounds.

Family A: stable heterogeneous talents with independent outcomes conditional on context. Family B: mixture/heavy-tailed talents and heterogeneous planted prevalence. Family C: time-varying form and schedule dependence. Family D: semi-synthetic contextual resampling with a valid conditional outcome mechanism. Choose one or more families fully held out before tuning. Include null, detectable signal, weak signal and misspecified contexts.

Confounders include firing after poor luck, shot selection after makes, garbage-time roles and opponent strength. Distinguish a planted direct causal effect from induced predictive dependence: slow-moving form can predict next shots even if no causal streak term exists. The truth label must match the registered estimand. A simulator cannot label every dependence outside its preferred mechanism 'false'.

Reuse only development schedules/attempt counts/priors when constructing tuning families; avoid using final NBA distributions to tune the harness. 'Semi-synthetic' is not proof of realism or valid nulls; outcome-dependent variables cannot remain fixed while outcomes are shuffled without checking the generating assumptions.

TruthManifest is accessible only to the scoring process and includes seed, family, planted mechanisms, units, affected groups and null/alternative labels. Do not expose labels through paths, filenames, model prompts, debug text or API responses. Test access denial. Logical separation without actual permissions must be labelled as such.

Run a deterministic/scripted policy across many leagues for speed and budget. Evaluate actual LLM Discoverer/Challenger on a declared sampled subset plus real claims. Report the sample selection and costs; thousands of scripted tests are not thousands of autonomous LLM research runs.

<!-- PAGE -->

## 07 / Calibration: measure the system without overselling it

Split league IDs before fitting: training evidence model; threshold/policy tuning; calibration fitting; untouched final evaluation, including a held-out generator family. Keep claims from one league/seed/group in the same split. Fix null prevalence and also stress different prevalences. A score's meaning changes with base rates and generator assumptions.

Possible score: logistic evidence model followed by isotonic calibration on a separate calibration split. Features must be available before truth reveal and must not identify seed/family labels. Fit no calibrator on the final family. Compare frozen thresholds, uncalibrated and calibrated versions, and simple baselines on identical eligible claims. A change after final is a new experiment.

Name the output 'simulator-conditioned support score'. It may estimate the probability of a planted mechanism under the evaluated simulator mixture; it is not a validated probability that a real NBA finding is true. Until final reliability evidence exists, show the score as unvalidated or omit it. A proposed 90% headline is forbidden merely because it appears in Heat Check.

Per independent league/session j: V_j=false discoveries, R_j=all discoveries, FDP_j=V_j/max(R_j,1). Estimate FDR by mean FDP across replicated families; pooled sum(V)/sum(R) is a different quantity and must be labelled separately. Under a pure null, FDR is the chance of at least one rejection. With no discoveries, precision is undefined even if FDP is defined as zero.

Report power by effect size/prevalence, false-positive rate, FDR, Brier/reliability diagnostics, calibration-bin counts, coverage and abstention. Bootstrap independent leagues/clusters, not dependent claims as independent rows. Display intervals and actual replication counts. Proposed target: at least 500 final leagues per supported family if runtime permits; missing precision is reported, not fabricated. Predeclare an acceptable FDR target AND useful power floor on a stated planted alternative; do not tune them using final results.

Discrete exact/Monte Carlo p-values need super-uniformity checks under the correct null, not mandatory continuous-uniform KS acceptance. Use p=(1+exceedances)/(B+1) for the specified Monte Carlo design, with ties handled conservatively. Test known tiny enumerations, empirical rejection rates/uncertainty and interval coverage across repeated independent simulations. One random failed test is diagnosed statistically, not automatically 'fixed' by loosening thresholds.

<!-- PAGE -->

## 08 / Pre-game forecasting and finite-family confirmation

This lane is separate from shooting folklore. Begin with B0 training-only home-win base rate and B1 a frozen strength/home baseline such as Elo with documented update timing. Candidate features include prior-game rest differential, back-to-back indicators and rolling prior results. No current-game points or player outcomes. Compare stronger frozen baselines where justified; beating a deliberately weak one is insufficient evidence of useful discovery.

Score the identical full eligible game stream for baseline and candidate. If the candidate cannot predict, use its preregistered baseline fallback and report raw coverage; do not drop hard games after seeing outcomes. Fit preprocessing/calibration/hyperparameters on earlier data only. Record neutral venues, postseason policy and exceptional-season handling in advance.

For y in {0,1}, log loss is -[y log(p)+(1-y)log(1-p)]; Brier is (p-y)^2. Clip probabilities with one frozen disclosed epsilon for both models. Fixture y=[1,0], baseline p=[0.5,0.5], candidate p=[0.8,0.2]: mean losses 0.6931471806 and 0.2231435513; improvement 0.4700036292. Brier improves from 0.25 to 0.04. These are arithmetic fixtures, not NBA results [S6].

Primary paired difference d=loss_baseline-loss_candidate, so positive means improvement. Register a practical minimum delta and an interval criterion, not just a p-value. Proposed block inference resamples whole calendar-time blocks with pairing intact; examine predeclared 1/2/4-week and season sensitivities. Shared teams and drift can persist beyond a week. A centred block-bootstrap p-value is approximate under assumptions, not an exact permutation guarantee. Too few usable blocks returns INSUFFICIENT_EVIDENCE.

Freeze at most five final hypotheses before opening final labels; apply Holm to their valid primary p-values at the registered level [S7]. Keep all results and the winner-selection caveat. The full development ledger count is disclosed but is not a substitute for defining the tested final family. Unsupported tests, broken assumptions or an exposed holdout block confirmatory language. A post-hoc final sensitivity analysis is exploratory unless predeclared.

<!-- PAGE -->

## 09 / NBA quote comparison and exact unit fixtures

Market comparison remains read-only and descriptive. It needs a separately evaluated GAME_PREDICTION for the exact event plus a trusted contract mapping. Display model p and the observed quote type/time, not a generic 'true probability'. An exchange price and a model forecast can differ for many reasons; neither is automatically ground truth.

Use Decimal or integer tick/minor-unit representations for venue prices; model/statistical probabilities remain floating point. Preserve the raw field name/unit and transform exactly once. Do not divide a fixed-point dollar string by 100 or interpret a cents integer as dollars. Normalise and sort independently of provider order.

Kalshi's public book supplies YES/NO bids. For ordinary complementary quotes, a YES ask is derived from 1 minus the opposite NO bid at the same quantity [S14]. Fixture: NO bid '0.3700' for 12 gives YES ask 0.6300 for 12. Empty opposite-side depth produces an unavailable ask, never zero. Retain raw-side provenance so the UI can identify a derived quote.

If a display includes a signed difference, define it literally as model probability minus the selected normalised quote. Fixture: p=0.60, YES ask=0.55 gives +0.05 in probability units (5 percentage points). It is not expected profit, a strategy, a recommendation or a significance test. Show forecast calibration scope and uncertainty separately.

Validate p in [0,1], nonnegative finite prices, valid units and quantity grids, matching outcome direction, quote timestamps and market status. Unknown units, ambiguous rule mapping, stale/paused books or unsupported event targets block the comparison. No portfolio-payoff enumeration, fee optimisation, general-market search, trading-return backtest or position sizing is required.

<!-- PAGE -->

## 10 / Event mapping and limits of market evidence

Keep MarketSpec, BookSnapshot and EventMapping identities. Match NBA game ID, participants/date, regulation/overtime, cancellation/postponement, correction/dispute, authoritative outcome source and payout convention. Title similarity is candidate discovery only. A trusted review and rule/source hashes bind the mapping. If model and contract concern different events/outcomes, do not display their probabilities as comparable.

Example: the model predicts a team's full-game win including overtime; the contract concerns regulation only. Those are different targets even if their titles share both team names. A postponed game may retain a team ID while the contract voids. Report the exact mismatch and leave the comparison unavailable until resolved.

Live current quotes can demonstrate ingestion and current context; they do not validate past trading returns. A historical comparison needs archived quotes available at the original prediction cutoff and an honest exposure analysis. Midpoint/last trade is not necessarily a price someone could buy at; clearly label it. Do not market a forecast-price gap as guaranteed value.

No general-purpose prediction-market scanner is in this scope. Non-NBA contracts stay unsupported for model comparison. No trading account, wallet signature, order submission, sell/short operation or funding flow is implemented. Research validates the quote/target semantics; Experience implements the public adapters; Max integrates the matched evidence.

This simplification preserves the direct research objective: can the system propose a claim, expose failure modes, measure null/power behaviour and report supported NBA forecasts? Market data enrich the evidence view without turning the product into a trading system.

<!-- PAGE -->

## 11 / Test matrix, delivery and research bootstrap

Required tests: input schema/domain/finite JSON; duplicate game and event reconciliation; pre-shot and pre-game feature availability; future-perturbation invariance; season/trip boundaries; tiny exact null/streak enumerations; shrinkage moments; weak/strong/null controls; drift/selection/confounder cases; truth/final access denial; family/group split isolation; calibration fit separation; zero-discovery semantics; candidate fallback/paired scoring; market quote-side/unit/event/freshness fixtures; replay/hash stability and resource caps.

Future-perturbation test: alter outcomes strictly after the registered cutoff and assert earlier feature values, fitted state and predictions remain unchanged. A leakage fixture intentionally violating this must fail. This proves the implemented dependency boundary for the fixture, not absence of every latent data or model-memory leak.

Deliver pure functions plus small frozen fixtures first, then adapters/harness scripts, actual reports and raw outputs. Max reviews on your exact commit/source hash and independently derives key cases. Review Max's plan interpreter, gate semantics, full retry identity, ledger immutability and protected-data access. You cannot self-accept the kernel because your own tests pass.

Copy as first prompt: 'You are HeatCheck-Research, a Pro session on a separate computer. Read this entire document and Shared_Protocol.json. Inspect the actual source/tools; no result in the pack is an executed experiment. Own data/statistics/attacks/simulator/calibration and market math. Freeze schemas with Max and Experience before edits. Use deterministic registered methods; never ask a model for p-values or quote-unit arithmetic. Implement the declared oracles and null/planted controls, execute real checks, preserve evidence and send a bounded source-linked packet. Keep hidden truth/final splits separate, label simulation versus NBA calibration, and do not claim betting returns without dated execution data. Work through authorised repairs; do not weaken tests, fabricate passes or invoke absent workers. No paid signup, trading, publication or outside messages from this prompt. Follow actual user permissions and event rules.'

<!-- PAGE -->

## 12 / Research references and definitions

Primary sources checked 7 November 2026; full links in Sources.md. [S3] shufinskiy/nba_data (bulk source/coverage); [S4] swar/nba_api (client/reference); [S5] BALLDONTLIE NBA documentation (tiers/schema); [S6] scikit-learn model evaluation/calibration; [S7] statsmodels multipletests; [S8] Miller and Sanjurjo, Econometrica 2018, doi:10.3982/ECTA14943; [S9] reusable-holdout/adaptive analysis author explanation; [S13] Polymarket public market data/order books; [S14] Kalshi public market/orderbook; [S15] Kalshi fixed-point representation; [S16] Polymarket fees; [S17] Kalshi fee schedule; [S18] The Odds API historical documentation. Exact external data coverage, entitlement and API behaviour remain to be tested locally.

Terminology: alpha as a user-facing aspiration means useful incremental research/predictive information unless a separate return study supports more. Hypothesis-testing alpha is an error-budget parameter, a different concept. A statistical testing e-value differs from an observational confounding E-value; neither is adopted casually here. A calibrated forecast probability, a simulation support score, a posterior talent distribution and a p-value are four different objects.

Do not transplant the original Jone's financial deflated-Sharpe gate into every sports question. The primary prediction task uses proper scores; shot questions use their own estimands/nulls. Online FDR/e-processes, full hierarchical dynamic models, learned attack policies and automatic cross-sport replication remain optional research modules requiring their own checked assumptions.

The merge adopts Heat Check's goals while correcting its overclaims: a realism plot is not proof of sim-to-real transfer; persistence is not the definition of all skill; a natural experiment label is not randomisation; 'no significant effect' is not 'lucky'; and '500 leagues' is a target, not a result. The user expects an ambitious working product; every capability still earns its own acceptance evidence.

At release report actual counts: raw/eligible games and shots, tested hypotheses/variants, failed/undefined attacks, simulated leagues/families, final exposures, calibration-bin support, same-game prediction coverage, market comparisons available/blocked and reason, and NOT_RUN gates. A clean negative result and a blocked event-mismatch example are valuable product behaviour.
