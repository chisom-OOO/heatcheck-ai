# Experience tasks

Owner: HeatCheck-Experience (Claude Pro, separate computer). Assigned by Max on 7 November 2026.
First read: `CLAUDE.md`, `docs/team/03_Pro_Experience.md`, `docs/DATA_PIPELINE.md` §2, §4
and §5, `docs/DATA_FORMAT.md`, `contracts/Shared_Protocol.json`. Example bundle:
`tests/fixtures/contracts/syn_reference_bundle/`.

---

## E-001: read-only quote fixture for one NBA game, replayable offline

**Status:** READY. **Branch:** `experience/e-001-quote-fixture` from the commit
that contains this file (`max/integration`, or `main` after Max merges it). **Gates touched:** G11 (fixture scope) and G12 (only if a real
public capture is made). **Reviewer:** Max, with Research reviewing the price-unit handling.

### Goal

Create one committed bundle in `heatcheck-records/1` that holds a read-only order-book
quote for one NBA game's team-win contract. A test must re-derive the bundle's `QUOTE`
records from the stored raw payload with the network disabled.

### Choose the source (record which in the manifest `notes`)

- **Preferred: a real recorded capture.** Pick one upcoming NBA game and make public,
  unauthenticated, read-only GET requests to Polymarket and/or Kalshi market-data
  endpoints. First confirm with the user that these requests are authorised on your
  computer: the role document does not grant tool permission. Use `data_mode =
  RECORDED_MARKET` and real `nba:` game/team ids. The capture time is the real
  `fetch_start_utc`/`received_utc`. Never reconstruct a past book from today's price.
- **Fallback: an invented fixture.** If live capture isn't authorised or no NBA market is
  listed, hand-write a venue-shaped raw payload. Use `data_mode = SYNTHETIC`, `syn:` ids,
  `venue = SYNTHETIC_VENUE` or the real venue's payload shape, and a rights note saying the
  data is invented. This satisfies E-001's format and replay criteria but leaves G12 NOT_RUN.

### Deliverables

1. **Bundle** at `tests/fixtures/quotes/e001/` (committed, under 1 MB), with `created_by_role: EXPERIENCE`:
   - `RAW_SNAPSHOT` for each raw payload (metadata response and book response). Files go in
     `raw/<sha256>.json` exactly as received. Redact nothing; no auth is involved. The
     `source` field is the endpoint path, and the `rights_note` states the venue terms checked.
   - `GAME`: one record for the game, with `status` as currently known. Use the canonical
     `nba:` id. Research owns canonical games, so record the id's source in `provider_ids`
     and the manifest notes. Max reconciles it with Research's table later.
   - `VENUE_MARKET` from the metadata payload. Outcomes come from the payload's own
     outcome/token or ticker fields; never assume the first outcome is YES.
   - `VENUE_MAPPING` for the team-win contract, `status: PROPOSED` (Max verifies), with the
     overtime and cancel/postpone conventions read from the rules text, or `UNKNOWN` with a reason.
   - At least one `QUOTE` with levels as the venue reported them (`derivation: DIRECT`) in
     `PROBABILITY_DOLLARS`. Do **not** compute complements or a midpoint. That is Research's
     normaliser.
2. **Replay adapter** in `heatcheck/markets/adapters/`. It is a pure parse function
   `raw bytes + capture metadata -> VENUE_MARKET/QUOTE records` plus a replay mode that reads
   only the bundle directory. The live mode, if built, uses an allowlist of public GET URLs and
   has no order, signing or account route.
3. **Tests** in `tests/experience/test_e001_*.py` (see acceptance).

### Acceptance criteria (each must be replayable by Max on the exact commit)

| # | Criterion | How it is checked |
|---|---|---|
| A1 | Valid in the shared format | `uv run python -m heatcheck.contracts.bundle tests/fixtures/quotes/e001` exits 0 and prints PASS |
| A2 | Replays offline, byte-identical | `uv run pytest tests/experience/test_e001_replay.py` passes. With `socket.socket` patched to raise, the adapter re-parses the files in `raw/` and produces `VENUE_MARKET` and `QUOTE` records whose canonical bytes equal those in `records.jsonl` |
| A3 | Raw integrity | Change one byte in a raw file in a temp copy, and the validator or the replay must fail. The test asserts the failure |
| A4 | Unit/semantics refusals | Tests assert that the adapter refuses, with an explicit error and no record emitted, in each case: a price in cents (e.g. `"53"`), a missing `received_utc`, an outcome id absent from the metadata, and a midpoint or last-trade field offered as a level. An empty book becomes `status: EMPTY` with a reason, never a zero price |
| A5 | Read-only | No adapter module contains an order, cancel, sign, withdraw or deposit call. The live client (if any) refuses a non-GET method or a URL outside its allowlist, and a test asserts both |
| A6 | Labelled honestly | The manifest `data_modes` matches what was actually done: `RECORDED_MARKET` for a real capture, `SYNTHETIC` for an invented one. The notes give the original capture time. `uv run ruff check .` passes |

### Out of scope for E-001

UI, voice, comparison cards, multiple games, complement/midpoint arithmetic and any change
to `heatcheck/contracts/`. File a schema change request in `docs/tasks/README.md` instead.

### Constraints

Read-only public market data only. No wallet, keys, orders, account creation or
geo-restriction bypass. Follow venue rate limits and terms. Do not push: hand the branch to
Max as a `git bundle` or patch through the medium the user authorises, or push only if the
user explicitly releases pushing.

### Checkpoint log

(append entries using the template in `docs/tasks/README.md`)

### 2026-11-07T16:12Z PATCH_READY on experience/e-001-quote-fixture@(this commit; parent 8210fda)
Source: SYNTHETIC fallback. Live Polymarket/Kalshi GETs were not authorised in this session,
so no capture was made and G12 stays NOT_RUN. Payloads are carried over from the earlier
Experience build (`heatcheck-experience.zip`, sha256
c646c751454b696228e706f9035394f29ad2660802cdc1b6d11b49845f537a90, `server/venue_fixtures.py`)
and its read-only Polymarket/Kalshi adapter (`server/venues.py`). Reconciled to
heatcheck-records/1:
- DIRECT levels only. Dropped the old adapter's Kalshi derived YES ask, midpoint, spread and
  best bid/ask; Kalshi quotes store the contract's own bids, plus a reason.
- Legacy integer-cent Kalshi books are now refused, not converted.
- Statuses map to OK/EMPTY/ERROR(crossed)/PAUSED.
- Timestamps use `Z` and ids are `syn:`/`syn-team:`.
- The non-venue `_provider_time` field is dropped.
- Polymarket metadata gains `events[0].id`.
- The ZIP's `contracts/Shared_Protocol.json` is semantically identical to this repo's.

Not integrated, because E-001 puts them out of scope: the ZIP's UI, voice, extension, fixture
research engine, comparison cards and stand-in quote normaliser. They remain in the ZIP for a
later task.

Platform: Windows 10.0.26200, Python 3.12.13, uv 0.11.26; checkout path kept short (Windows MAX_PATH).

Commands run (exact) and exit codes:
- `uv sync --frozen --group dev` 0
- `uv run python tools/check_scaffold.py` 0 (PASS)
- `uv run ruff check .` 0 (All checks passed)
- `uv run pytest -q` 0 (100 passed: 44 existing + 56 E-001)
- `uv run python tools/make_reference_bundle.py --check` 0
- A1 `uv run python -m heatcheck.contracts.bundle tests/fixtures/quotes/e001` 0 (PASS)
- A2 `uv run pytest tests/experience/test_e001_replay.py` 0 (5 passed; socket patched to raise)
- A3–A5 `uv run pytest tests/experience -q` 0 (56 passed)
- `uv run python tests/experience/make_e001_bundle.py --check` 0 (reproducible)

Mutation checks:
- `price()` accepting anything: 4 refusal tests fail.
- Replay skipping its raw hash check: A3 fails. A direct per-file hash test was then added.

Raw output excerpt / artifact paths and sha256:
- `tests/fixtures/quotes/e001/records.jsonl` b98438c49e35115bd0130e95988c3d8393f79d7315691c95044f0cfe2987e843
  [GAME=1, QUOTE=2, RAW_SNAPSHOT=5, VENUE_MAPPING=2, VENUE_MARKET=2], 16.5 KB in total.
- `tests/fixtures/quotes/e001/manifest.json` 063f2a3a6f56abefb5f5a99b5e7585fa98f39e9b0a355819c36a971c06476e75

Gates touched and status:
- G11: fixture-scope E-001 criteria A1–A6 pass on SYNTHETIC data only. This is not a gate PASS;
  it needs Max's replay and Research's price-unit review.
- G12: NOT_RUN (no live capture).
- G10: mappings are PROPOSED only.
- All other gates are untouched.

Defects found and root cause:
- The earlier build's adapter derived complements and midpoints inside the adapter, which
  conflicts with DATA_FORMAT §3. Fixed by storing DIRECT levels only.
- Repo checks fail under a long Windows checkout path (MAX_PATH): `uv sync` cannot write
  `.venv`, and pytest cannot open fixtures. This is environmental, with no code change. Use a
  short path or enable long paths.

Questions for Max:
1. Synthetic records keep `venue = POLYMARKET/KALSHI` because the payloads use those venues'
   shapes, with `data_mode = SYNTHETIC`. Should they be `SYNTHETIC_VENUE` instead?
2. Capture metadata (fetch_start/received/target) lives in a `heatcheck-capture/1` log stored
   as a RAW_SNAPSHOT under `raw/`. Should this become a schema field?
3. Should CI also run `tests/experience/make_e001_bundle.py --check`? `.github/` is outside
   Experience paths.
