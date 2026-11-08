# Current project state

Prepared 7 November 2026; event development 7–8 November 2026. Updated 8 November 2026,
~02:20 UTC, by Max, on branch `max/integrate-r001-e001` (not on `main`; nothing goes to `main`
without the user's instruction). The scaffold text that stood here before is superseded.

Every acceptance gate G01–G18 in `ACCEPTANCE.json` is still **NOT_RUN** as a gate: no reviewer
has marked one. `docs/GATES_EVIDENCE.md` lists, per gate, the evidence that exists and the exact
commands to rerun it, for an independent reviewer to judge on a `review/` branch. Results below
are the authors' own (Max, Research or Experience) unless a separate review is named.

## Product as built

HeatCheck: a fan asks an NBA question by voice or text. Heater (the character, the Discoverer
role) proposes; the Challenger selects registered tests; the deterministic Referee decides. The
page shows the Ref's verdict as a stamp (SURVIVED / NOT ENOUGH EVIDENCE / NOT SUPPORTED / BLOCKED)
with the evidence behind it. Read-only extras: tonight's market board (forecast vs a venue
quote, "Edge unverified"), what-if scenarios (ESTIMATE / HYPOTHETICAL) and an idea board.
Removed by scope: statistical arbitrage, opportunity scanning, ranking, sizing, execution.
No order capability exists anywhere.

## Implemented (code in this branch)

| Area | Owner | What | Main paths |
|---|---|---|---|
| Shared data format | Max | `heatcheck-records/1` bundles + stdlib validator; SYNTHETIC reference bundle | `docs/DATA_FORMAT.md`, `heatcheck/contracts/` |
| Evidence ledger | Max | Append-only, hash-chained; retry identity; historical entries immutable | `heatcheck/ledger/`, `tests/integration/test_ledger_chain.py` |
| Agent loop | Max | Discoverer → Challenger → deterministic Referee on a real game bundle | `tools/run_loop.py`, `heatcheck/agents/` |
| Dialogue API | Max | `/api/dialogue`; Heater and claim mapping via the Meta model (key server-side), Ref wording deterministic; sample/fixed lines when no key | `heatcheck/api/dialogue_server.py`, `tools/serve_dialogue.py` |
| Confirmatory lane | Max | Dry run, authorised single final, `verify_final_result`, records without re-running | `tests/integration/test_confirmatory_lane.py` |
| Research data + tests | Research | 2023-24 play-by-play rebuild (1,230 games); game-prediction final; hot-hand claims; custodian/exposure ledger; 2024-25 sealed season | `handoff/research-20261107/` |
| Idea machine | Research | Families of ideas tested together (permutation, Holm); synthetic leagues with planted truth | `handoff/research-20261107/scripts/idea_family.py`, `docs/IDEA_GRAMMAR.md` |
| Live forecast | Research | Elo forecasts for 2026-27 games (14 games, 7–9 Nov) | `data/live/forecasts.json`, `docs/LIVE_FORECAST_FORMAT.md` |
| Scenario effects | Research | Player-absence (empirical-Bayes shrunk) and schedule ESTIMATE tables, combiner, `scenario_api_answer` | `data/scenario/`, `handoff/research-20261107/src/heatcheck/scenario.py` |
| Venue adapters | Experience | Read-only Polymarket (Gamma + CLOB) and Kalshi capture; quote normalisation | `apps/web/server/venues.py`, `quotes.py`, `heatcheck/markets/live_quotes.py` |
| Mapping verification | Max | 16 identity checks per venue contract before `/api/investigate` uses it | `tools/verify_mappings.py`, `data/max/mapping_verifications/` |
| Market investigation | Max | `/api/investigate` LIVE (60 s quote limit) or RECORDED (as of capture, labelled); verdict "Worth investigating · Edge unverified" at most | `heatcheck/agents/market_investigation.py` |
| Scenarios + routing | Max | `/api/route` (board / card / what-if / dialogue); what-if parse → confirm → estimate on Research's functions; GET `/api/scenario` = Research's answers | `heatcheck/agents/scenario.py`, `research_scenario.py` |
| Idea proposer | Max | Heater turns a question into 3–6 ideas via the model, strict-parsed; keyword fallback | `heatcheck/agents/idea_proposer.py`, `tools/propose_ideas.py` |
| Demo page | Experience (+ Max wiring) | Heater character, Ref card, stamps, evidence drawer, market board, idea board, what-if view, mic button | `apps/web/web/` |
| One-command runs | Max | `demo.cmd` (servers + page), `capture_quotes.cmd` (fresh read-only quotes + verification) | `tools/demo.py`, `tools/capture_quotes.py` |

## Verified (with scope; author's check unless a review is named)

- **Separately reviewed and replayed** (reviewer branch `review/independent-tests`, reports in
  `reports/review/`): R-001/E-001 imports and bridge (1642), agent loop determinism across OS
  (1716), Research guard fixes RV-R1/R2/R4/R5 (1733), the confirmatory run (2232).
- **Confirmatory final, run once on 2024-25** (authorised by the user 22:27 Europe/London,
  receipt `5cbb3222`): CONF-HA home advantage SURVIVED_PROTOCOL (home-win 0.5449, Holm p 0.0054,
  1,224 games); CONF-MOM and CONF-HH hot hand INSUFFICIENT_EVIDENCE. 2024-25 outcomes are public,
  so this is pseudo-out-of-sample.
- **Repo suite** at `c15abf7`: `uv run --frozen pytest -q` 642 passed, 29 skipped, 16 xfailed
  (deferred reviewer probes, strict); `ruff` clean; `node --test apps/web/tests/*.test.mjs`
  71/71; CI "Preparation checks" green on every push tonight.
- **Demo end to end** (`reports/max/2026-11-08-scenarios-routing/`, Playwright Chromium, no model
  calls): chip stamps NOT ENOUGH EVIDENCE / SURVIVED / NOT ENOUGH EVIDENCE; Sunday scenario card;
  free-text routing to board, card and what-if; raw estimates only in the evidence drawer; empty
  console.
- **Read-only quotes**: captures on 7–8 Nov in `data/experience/quotes/`; latest via
  `capture_quotes.cmd` at 02:15 UTC: 24 contracts matched (13 Polymarket, 11 Kalshi), 13/13
  Polymarket mappings verified, no key in any file.
- **Live investigations before tip** (`reports/max/2026-11-08-market-live-recorded/`): CLE and OKC
  "Worth investigating · Edge unverified". On 12 of 13 comparable games the model is above the
  ask, which suggests model bias, not an edge.
- **Scenario numbers** equal Research's `scenario_probability` / committed answers to the digit
  (280 scenarios, `tests/integration/test_scenario.py`).

## Not run / not done

- No gate marked by a reviewer (see `docs/GATES_EVIDENCE.md`). The planned reviewer's laptop is
  down; the adviser will rerun on a `review/` branch.
- Voice and microphone in a real browser session: NOT_RUN (headless runs had speech off).
- OS-level isolation of the confirmatory custodian: NOT_RUN (not implemented); `fcntl` locking
  means the final runs on Linux only (the Windows dry run reports `platform` FAIL by design).
- Heater's "Does rest matter?" family (`data/max/idea_requests/does_rest_matter_heater_dev.json`,
  commit `c15abf7`): sent to Research, not yet run.
- Scenario effects are descriptive ESTIMATES: no registered test covers them (GP-REST found
  INSUFFICIENT_EVIDENCE); 2026-27 rosters are not verified.
- No claim that the model beats the market; no comparison of forecast skill against the market
  has been run (G09 scope is game-prediction against baselines only).
- Paid model use: ≈ US$0.072 logged of the $5 approval (`reports/max/SPEND.md`).
- Integration to `main`: not done; needs the user's instruction.
- CI runs only the root `tests/`; Research's handoff suite (92 passed, 8 skipped on Windows; three
  files need Linux for `fcntl`) and Experience's `apps/web` suites (104 unittest, 71 node) are run
  by hand only.
- Known data defect: the git-ignored local 2023-24 build on Max's machine records a HeatCheck
  commit as `upstream_revision`; rebuild before using it as provenance evidence.
