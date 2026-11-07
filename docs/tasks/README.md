# Task board

Max writes assignments here; each owner works on their own branch and reports back
in their task file. Git carries the files between the three computers; it does not
notify anyone. Pull before starting and after each checkpoint.

| ID | Owner | File | Status |
|---|---|---|---|
| M-001 | Max | [MAX.md](MAX.md) | PATCH_READY: needs a separate reviewer |
| M-002 | Max | [MAX.md](MAX.md) | CLAIMED |
| R-001 | Research | [RESEARCH.md](RESEARCH.md) | READY |
| E-001 | Experience | [EXPERIENCE.md](EXPERIENCE.md) | READY |

## Lifecycle

`READY -> CLAIMED(owner, base commit) -> PATCH_READY(checks, artifacts) -> REVIEW_REQUIRED
-> ACCEPTED | REPAIR_REQUIRED -> INTEGRATED`. Only Max sets `INTEGRATED`. The author can
never set `ACCEPTED`; a reviewer other than the author replays the acceptance commands
on the exact commit.

## Branches

| Owner | Branch | Base |
|---|---|---|
| Max | `max/integration` | integrates into `main` |
| Research | `research/r-001-one-game` | the commit containing this file (on `max/integration` until Max merges it to `main`) |
| Experience | `experience/e-001-quote-fixture` | the commit containing this file (on `max/integration` until Max merges it to `main`) |

Do not edit another owner's paths or `heatcheck/contracts/` on your branch. Path ownership:
Research `heatcheck/data`, `heatcheck/research`, `heatcheck/attacks`, `heatcheck/sim`,
`heatcheck/markets/normalization`, `tests/research`; Experience `apps/web`,
`heatcheck/markets/adapters`, `tests/experience`, `tests/fixtures/quotes`; Max
`heatcheck/contracts`, `heatcheck/api`, `heatcheck/ledger`, `heatcheck/agents`, `tests/contracts`,
`tests/integration`, `docs/tasks`, the root state files.

## Reporting back (append to your task file under "Checkpoint log")

```
### <UTC time> <status> on <branch>@<commit>
Commands run (exact) and exit codes:
Raw output excerpt / artifact paths and sha256:
Gates touched and status (PASS/FAIL/NOT_RUN with scope):
Defects found and root cause:
Questions for Max (one actionable question each):
```

## Schema change requests

Append here; Max decides and records the outcome in `docs/DECISIONS.md`.

- (none yet)
