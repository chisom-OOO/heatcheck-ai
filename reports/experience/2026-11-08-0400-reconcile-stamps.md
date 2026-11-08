# Experience: reconciled with Max's server-side stamp (cd0f542)

- Branch: `experience/market-board`. Integrate at **cd0f542** was merged in (d3f9c85), and integrate is now
  an ancestor of this branch: **Max can merge it as a fast-forward with no conflicts**.
- Commits: **d3f9c85** (merge and resolution) and **df7cbf7** (demo.css byte fix). All checks below ran on
  **df7cbf7** with a clean worktree. This report and its log are in the commit after it.
- Supersedes my previous push, 0402a5e, which conflicted with cd0f542 in `demo.js`. **Do not merge
  0402a5e on its own.**
- Gates: none closed or self-marked.

## What happened

- After my 0402a5e, Max built the same stamp rule into his API and page (cd0f542). Estimate answers now
  carry `"stamp"`, and his `whatifStamp` in `whatif/whatif.js` shows it on the stamp, the panel badge and
  the drawer.
- He also made my e0a47b8 idea test the contract (7c59c49).
- My f97649a and a7a346f had done both on the page side instead, so the two clashed.

## Resolution: Max's version wins wherever both did the same thing

| File | Result |
|---|---|
| `web/demo.js` | Max's hunk: the stamp is the server's. The second `whatifStamp` import (from my `scenario-model.js`) is removed; two imports of one name would stop the page module loading. Only remaining difference from integrate: presets call `scenarioStamp(data, s)`. |
| `web/market/scenario-model.js` | My `whatifStamp` and `STAMP_ASSUMPTION` are removed. Presets keep `scenarioStamp(data, s)`, which is their ESTIMATE label from `GET /api/scenario` (always Research's data), with Max's stamp kinds. |
| `web/demo.css` | Identical to integrate (my unused `.stamp.assumption` is gone). |
| `server/ideas.py`, `tests/test_ideas.py`, `tests/fixtures/idea_family_api.json` | Identical to integrate, which is byte-identical to my e0a47b8 (git blob ids checked). |
| `tests/scenario.test.mjs` | Tests of the removed function are replaced by: a preset ESTIMATE stamp equals Max's `whatifStamp({stamp: "ESTIMATE"})`; `demo.js` imports `whatifStamp` once, from `whatif.js`; typed what-ifs use the server's stamp; presets use their label; there is no fixed "HYPOTHETICAL" stamp. |

**Error caught before pushing:** in d3f9c85, removing `.stamp.assumption` joined two CSS lines into
`…}@keyframes slam {`. It was still valid CSS, but df7cbf7 restores integrate's exact bytes.

## Checks (commit df7cbf7)

Complete raw output: `reports/experience/logs/2026-11-08-0400-reconcile-checks.log` (LF), run started
2026-11-08T03:02:00Z.

| Check | Command | Result |
|---|---|---|
| env | `uv sync --frozen --all-groups` | PASS |
| scaffold | `uv run --frozen --all-groups python tools/check_scaffold.py` | PASS |
| lint | `uv run --frozen --all-groups ruff check .` | PASS |
| pytest | `uv run --frozen --all-groups pytest -v` (git on PATH) | PASS: 642 passed, 31 skipped, 16 xfailed |
| bundles | `make_reference_bundle.py --check`; `-m heatcheck.contracts.bundle tests/fixtures/quotes/e001`; `make_e001_bundle.py --check` | PASS |
| web unittests | `cd apps\web && uv run --frozen --all-groups python -m unittest discover -s tests -v` | PASS (106 tests) |
| web node tests | `cd apps\web && node --test tests/scenario.test.mjs tests/speech.test.mjs tests/whatif.test.mjs tests/ideas.test.mjs tests/board.test.mjs tests/heater.test.mjs tests/referee.test.mjs` | PASS (77 tests) |

Also run: `node --check` on an `.mjs` copy of `demo.js` (module parse) PASS; `git merge-base --is-ancestor
origin/max/integrate-r001-e001 HEAD` true.

## Not executed

- **Browser end-to-end:** NOT_RUN by Experience. Max's cd0f542 browser run covers the server stamp.

## For Max

1. Merge `experience/market-board` up to this report's commit; it is a fast-forward of cd0f542.
2. Experience stops here until your rehearsal fixes.
