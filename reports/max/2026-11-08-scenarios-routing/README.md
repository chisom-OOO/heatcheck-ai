# Scenarios on Research's shrunk estimates, and free-text routing (Max, 2026-11-08 ~01:45 UTC)

Candidate: max/integrate-r001-e001 (this commit). Research: research/scenario-effects@f86d797 merged unchanged (30cd9d9).
Run: `demo.cmd --fresh-ledger --no-browser --no-llm --recorded-market`, then `uv run --frozen python shoot_route.py <dir>`
(Playwright Chromium, 1280x1000). No LLM calls (Heater's fixed lines; idea proposer deterministic).

| Check | Result |
|---|---|
| Chip stamps: hot hand / home teams / rest | NOT ENOUGH EVIDENCE / **SURVIVED** / NOT ENOUGH EVIDENCE (PASS) |
| Sunday card LAL @ DET, What if…? (Research's `scenario_api_answer`) | LAL back-to-back: DET 67.6% -> 72.1%, 90% 70.3-73.7%, n 1,313, GP-REST "unproven" caveat (PASS) |
| GET /api/scenario equals Research's committed scenario_answers.json, 28 answers / 280 scenarios, Experience's rules | PASS (tests/integration/test_scenario.py) |
| Free text "find me an interesting market tonight" | board opens, Heater introduces it (PASS) |
| Free text "What about the Lakers and Pistons game?" | LAL @ DET card focused (PASS) |
| Free text "What if Detroit were without Cade Cunningham?" | Heater reads it back, confirm, Ref: 67.6% -> 67.6% (95% 57.5-76.2%), HYPOTHETICAL stamp, "Edge unverified" (PASS) |
| Shrunk shown, raw only in evidence drawer | drawer: "Raw estimate (C. Cunningham) log-odds -0.001, 95% -0.594 to 0.570; shrinkage 0.55" (PASS) |
| Browser console | empty (PASS) |
| pytest full suite | 640 passed, 29 skipped, 16 xfailed (PASS) |
| node --test apps/web/tests/*.test.mjs | 71 pass, 0 fail (PASS) |

Defect found and fixed during the run: a second `scenarioDetails` declaration in demo.js (Experience already had one)
stopped the page module from loading; `node --check` on the .js file missed it (script parse). Renamed to
`whatifDetails`; checked by `node --check` on a .mjs copy and the browser run above.
