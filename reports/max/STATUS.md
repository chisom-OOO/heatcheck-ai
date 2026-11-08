# Max status (8 Nov 2026, ~08:25 UTC; freeze 09:30)

## Where things are
- Branch `max/integrate-r001-e001`. Main is `37b59e8` (CI passed). Last pushed branch commit: `e9fff82`.
- The rehearsal demo is running (`demo.cmd --recorded-market --no-browser`, model on), 8765/8770.
  - Stop it only by its process tree: `demo.cmd` with `recorded-market` in the command line.
  - `logs/tamper_events.jsonl` was emptied before the demo. Truncate it again if needed, don't
    delete it (the running server expects the file).
- Done:
  - Frost (adviser module with chip fixes), tamper endpoints, Experience's Frost page (`4c1a987`)
    and tamper UI (`a839a8d`), merged.
  - Ref voice 1.0/1.05; tamper button hidden by default (`?tamper=1`).
  - Report: `reports/max/2026-11-08-0735-frost-tamper.md`; screenshots in
    `reports/max/2026-11-08-frost-demo/`.

## Done (user, ~08:25): chip routing 9cc7a67+2a106dc; docs commit below; merging to main
1. **Fixed routing for the three chips**, like home advantage (rule before the model):
   "Is the hot hand real?" -> CONF-HH, "Does rest matter?" -> GP-REST,
   "Do home teams win more?" -> CONF-HA. Model mapping only for other text. Test, push.
   - Code: `heatcheck/agents/dialogue.py` `Dialogue._map` (the HOME_ADVANTAGE rule is the pattern).
2. **Docs, then merge to main:**
   - README: a Frost paragraph, the flowchart label, a screenshot (e.g. `live-chip1.png`).
   - docs/SUBMISSION.md: Frost and tamper paragraphs.
   - PROJECT_STATE.md.
   - Then merge to main and confirm CI green.

## Open items to report
- Experience page issues:
  - Frost's panel covers the chat at 1440x900; the Ref card falls below the fold.
  - Market cards don't show Frost.
  - The sample fixture has "47.27%", which is not in the record.
- Standard checks: ruff; pytest; apps/web unittest; node. Then CI.
