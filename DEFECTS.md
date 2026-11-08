# Defects

Updated 8 November 2026 by Max. The original line ("No production functionality exists", written
7 November at the scaffold stage) is no longer true: see `PROJECT_STATE.md` for what is implemented
and `ACCEPTANCE.json` / `reports/review/2026-11-08-0310-gate-review.md` for the reviewed gate marks.
No bug-free claim.

Defects are recorded where they were found, with repair and retest evidence:

- Reviewer findings and their status: `reports/review/` (RV-R*, RV-E*, RV-AL*).
- Max's defects found and fixed during the event, with root cause in each commit message, e.g.
  - `cd0f542`: typed what-if assumptions got 409 "confirmation revoked" (browser JSON writes -5.0 as
    -5); regression test `test_confirmation_survives_the_browser_json_round_trip`.
  - `240e3d5`: mapping verification records stored an absolute Windows path and failed Linux CI.
  - `7c59c49`: Max's change to the idea reader broke Experience's snapshot test (CI does not run
    `apps/web` tests; they are now in Max's standard checks).
  - `11772da`: a duplicate function in `demo.js` stopped the page module loading.
- Open, known: see "Not run / not done" in `PROJECT_STATE.md` and "Known contradictions" in
  `docs/GATES_EVIDENCE.md`.
