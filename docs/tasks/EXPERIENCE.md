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
