# Max tasks

Owner: HeatCheck-Max (integration lead). Branch: `max/integration`.

## M-001: freeze the shared data format heatcheck-records/1

**Status:** PATCH_READY. It needs a reviewer other than Max: Research reviews the
FEATURE_ROW, EVENT and label rules, and Experience reviews VENUE_MARKET, MAPPING and QUOTE.

Deliverables: `docs/DATA_FORMAT.md`, `heatcheck/contracts/records.py`,
`heatcheck/contracts/bundle.py`, `tools/make_reference_bundle.py`, the
`tests/fixtures/contracts/syn_reference_bundle/` fixture (SYNTHETIC, invented values),
`tests/contracts/test_records.py` and the `.gitattributes` EOL exemption for bundles.

Acceptance (replay on the exact commit):

| # | Check | Command |
|---|---|---|
| A1 | Reference bundle validates | `uv run python -m heatcheck.contracts.bundle tests/fixtures/contracts/syn_reference_bundle` → PASS |
| A2 | Reference bundle regenerates byte-identically | `uv run python tools/make_reference_bundle.py --check` → PASS |
| A3 | Invalid records/bundles are refused | `uv run pytest tests/contracts/test_records.py`. Each invalid case first validates unmutated, then fails with the expected message |
| A4 | Both teams' bundle shapes validate | Covered by `test_research_shape_real_nba_bundle_validates` and `test_experience_shape_recorded_market_bundle_validates` |

Defect found and repaired during M-001: the validator compared UTC strings lexically, so
`...00.250Z` sorted before `...00Z` and a valid quote was rejected. Root cause: string
comparison of timestamps. Repair: `records.parse_utc` is used for every time comparison.
Regression test: `test_quote_subsecond_receive_after_fetch_is_valid`.

## M-002: quote eligibility by forecast cutoff (pure)

**Status:** CLAIMED. The first slice is implemented: `heatcheck/contracts/eligibility.py`
and `tests/contracts/test_eligibility.py`. It selects the latest quote *received* by the
cutoff for a VERIFIED mapping. A later quote is ineligible, an old one is STALE, and an
unverified mapping blocks. The latest non-OK quote is reported, never skipped in favour of an older OK quote.

Next steps:
1. Once R-001 and E-001 land, join a Research `GAME` with an Experience `GAME` by canonical
   `nba:` id. Disagreement on teams or tip time → mapping `BLOCKED_RULES_UNVERIFIED`.
2. Max-verify the E-001 mapping against its stored rules text, or leave it PROPOSED with a reason.
3. Run the offline demo: forecast placeholder status UNAVAILABLE (no evaluated forecast exists),
   the eligible quote and the comparison card reasons. No probability difference is shown until a
   Research forecast has passed G09.

## M-003: review R-001 and E-001

On PATCH_READY, check out the exact commit, rerun every acceptance command from a clean
tree, and derive at least one expected value independently. Example: pick one shot by hand
from the raw play-by-play and compute its pre-shot margin. Record PASS/FAIL/NOT_RUN in the
task file and in `ACCEPTANCE.json` G01/G02/G11 with their scope.

### Checkpoint log

### 2026-11-07 PATCH_READY M-001, CLAIMED M-002 on max/integration
Commands, on Windows 11, Python 3.12 via `uv run --frozen`:
`uv run pytest -q` → 44 passed. `uv run ruff check .` → All checks passed.
`uv run python tools/check_scaffold.py` → PASS (preparation only).
`uv run python tools/make_reference_bundle.py --check` → PASS, records_sha256 6f3076466e2f0e889207bbceb6c2b32045eacbd33cafa28f58c926f94512dd41.
Gates: none closed. These are contract and tooling checks, and all G01–G18 remain NOT_RUN.

### 2026-11-07 live forecast format + MARKET_COMPARISON investigation (on max/integrate-r001-e001)
- heatcheck-live-forecast/1: `docs/LIVE_FORECAST_FORMAT.md`, `heatcheck/contracts/live_forecast.py`,
  SAMPLE fixture `tests/fixtures/live_forecast/forecasts.SAMPLE.json`, `GET /api/live-forecast`.
- `POST /api/investigate`: `heatcheck/agents/market_investigation.py` (Heater input guard, deterministic
  Challenger checks and Ref template, ledger identity), `--quote-bundle/--recorded` in serve_dialogue.
- Commands: `uv run --frozen pytest -q tests/integration/test_market_investigation.py
  tests/integration/test_live_forecast_route.py tests/contracts/test_live_forecast.py
  tests/integration/test_dialogue.py` -> 109 passed. Full suite before the investigation module:
  451 passed, 1 failed (`tests/review/test_rv_agent_loop.py::test_rv_al5_loop_accepts_minimal_challenger`,
  also failing on clean HEAD 741b4de, so not caused by this change). `ruff check .` -> clean.
- HTTP smoke (SAMPLE forecast + recorded E-001 bundle, --recorded, --no-llm): `/api/live-forecast` OK
  is_sample true; `/api/investigate` for nba:0022600189 -> 404 "not in the live forecast file".
- Blocking the recorded-game fallback: no forecast row exists for nba:0022600189 (Research), and both
  E-001 mappings are PROPOSED (Max must verify the Polymarket rules text, or the card shows Can't compare).
- Gates: none closed. Review needed by someone other than Max. No live provider or LLM call was run.
