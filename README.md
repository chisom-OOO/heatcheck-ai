# HeatCheck

**The NBA researcher that tries to prove itself wrong.**

Jone proposes a claim. Challenger tries to disprove it. A deterministic referee
applies registered tests and preserves the evidence. The intended product also
includes a planted-truth harness, voice/page/file interaction and optional
read-only NBA forecast/quote comparisons with Polymarket/Kalshi.

## Run the demo (Windows)

Prerequisites: [uv](https://docs.astral.sh/uv/getting-started/installation/) (it fetches
Python 3.12 itself), and internet access on the first run. Then, in the repository root:

```powershell
.\demo.cmd
```

On any OS the same command is `uv run --frozen --group research python tools/demo.py`.

This one command:

1. **First run only (a few minutes, about 46 MB downloaded).** It downloads the three pinned
   public archives from `shufinskiy/nba_data` at the commit in
   `incoming/research-20261107/raw/repo/COMMIT`, and verifies them against Research's
   `SHA256SUMS`; any mismatch stops the demo. It builds Research's 2023-24 tables with
   Research's unchanged `build_dataset.py`, then bridges game `nba:0022300061` into a
   `heatcheck-records/1` bundle. Finally it checks that the bundle's `records_sha256` equals
   the data identity in the committed evidence ledger. All of this is written to git-ignored
   `data/`, because raw redistribution rights are unverified.
2. It copies the committed evidence ledger to `logs/demo/evidence.jsonl` (git-ignored). The
   committed file is never written.
3. It starts two local servers and opens both pages:
   - `http://127.0.0.1:8770/`: the **dialogue console**. Ask Heater (the Discoverer) a
     question; the Ref answers from the evidence ledger. This is Max's API test page for
     `POST /api/dialogue`.
   - `http://127.0.0.1:8765/`: **Experience's UI**. It shows the same ledger read-only, and
     new dialogue entries appear there.

Ctrl+C stops both servers.

| Option | Effect |
|---|---|
| `--no-llm` | Deterministic templates only, with no model calls. This is automatic when `META_API_KEY` is not set. |
| `--no-browser` | Do not open the browser. |
| `--setup-only` | Build the data and the ledger, then exit. |
| `--fresh-ledger` | Reset the demo ledger to the committed one. |

With `META_API_KEY` set in the environment, Heater, the question mapping and the Ref's
phrasing use live Meta model calls (`muse-spark-1.3`, minimal reasoning). Spend is logged
per call to `logs/llm_usage.jsonl`. The key stays in the server process.

Known limits:
- Experience's UI does not yet send questions to `/api/dialogue`; the console page does.
- The registered tests run on one real game. HH-K3 needs more data and is
  INSUFFICIENT_EVIDENCE; HH-K2 is NOT_SUPPORTED; GP-REST is BLOCKED (no game-season view).
- Confirmatory claims (CONF-*) answer in dry-run mode: no verdict until the single recorded
  final run.

## Current truth

*Partly superseded on branch `max/integrate-r001-e001` (7 November 2026, evening): the
agent loop, evidence ledger, dialogue API and Experience's UI exist there; see "Run the
demo" above and `reports/`. The paragraph below describes the morning skeleton.*

This is a LOCAL PREPARATION SKELETON created 7 November 2026. Reserved Python
packages, development tooling and specifications exist. No NBA data, agent loop,
statistics engine, fitted/calibrated model, application/server, voice integration,
market connector or trading functionality is implemented. Statistical arbitrage
and the general-market opportunity scanner are removed from scope.

The user-created GitHub repository is https://github.com/chisom-OOO/heatcheck-ai.
The fetch remote was verified empty and configured for the authorised initial
local checkpoint. Publication remains blocked by a disabled push URL and hook;
no remote push has been performed. Preserve true development/prior-work provenance
and verify event reuse rules. Git history records actual local checkpoints.

## Start here

- Read AGENTS.md, PROJECT_STATE.md, CONTRACTS.md and ELIGIBILITY.md.
- Max: docs/team/01_Max_Lead.pdf or docs/prompts/01_Max_Lead.txt.
- Pro Research: docs/team/02_Pro_Research.pdf or matching TXT.
- Pro Experience: docs/team/03_Pro_Experience.pdf or matching TXT.
- Shared contract: contracts/Shared_Protocol.json.
- All 18 implementation/research gates in ACCEPTANCE.json begin NOT_RUN.

One Max and two Pro coding sessions run on THREE computers. Branch/transport and
message delivery must be configured and tested; shared memory is not automatic.
Max integrates; each author receives separate review of exact source/evidence.

## Tooling checks only

Python 3.12 + uv. Runtime dependencies are not installed by default. Existing
backend/research/browser groups are optional preparation; add pandas/scikit-learn/
statsmodels under a reviewed lock update when implementing the research kernel.

```powershell
uv sync --frozen --group dev
uv run python tools/check_scaffold.py
uv run ruff check .
```

These validate preparation/tooling only, not mathematical or application gates.
For the demo, see "Run the demo (Windows)" above. Create actual discriminating tests
when functionality exists; do not turn placeholders into claimed capabilities.
