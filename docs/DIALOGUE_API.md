# Dialogue API: contract for Experience's Heater page

Owner: Max. Status: implemented on `max/integrate-r001-e001`. This document is the contract
for Experience's Heater page. Max's console page at `http://127.0.0.1:8770/` stays available
as a fallback.

The examples are real responses, not hand-written ones. They were captured in template mode
(`--no-llm`) against a copy of `evidence/evidence.jsonl` and the real-game bundle; the raw
capture is `reports/max/logs/2026-11-07-api-doc/api_examples.json`. With a model key set,
only `heater_text` and the `sources` values change.

## Server

| | |
|---|---|
| Start | `demo.cmd` (both servers), or `uv run --frozen --group research python tools/serve_dialogue.py data/bundles/r001-nba-0022300061 --ledger <ledger.jsonl> [--port 8770] [--no-llm]` |
| Base URL | `http://127.0.0.1:8770`, bound to 127.0.0.1 only |
| CORS | `Access-Control-Allow-Origin` is echoed only for `http://127.0.0.1:8765` and `http://localhost:8765`. Other origins get no CORS header. |
| Auth | None (local only). The model key stays in the server process and never appears in a response. |
| Concurrency | One turn at a time. Concurrent POSTs queue behind a lock, because the ledger is an append-only file. |

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/dialogue` | One dialogue turn: map the question, get the evidence, Heater reacts, the Ref states the verdict. |
| `GET` | `/api/display-titles` | `{"display_titles": {claim_id: title}}`: short fan-facing titles, presentation only (below). |
| `GET` | `/` or `/index.html` | Max's console page (HTML). |
| `GET` | `/api/live-forecast` | Research's live forecast file, re-validated per request (docs/LIVE_FORECAST_FORMAT.md). |
| `POST` | `/api/investigate` | Read-only MARKET_COMPARISON investigation of one game card (below). |
| `OPTIONS` | any | CORS preflight: `204`, with `Access-Control-Allow-Methods: GET, POST` and `Access-Control-Allow-Headers: Content-Type`. |

Any other path returns `404 {"error": "not found"}`.

## `POST /api/dialogue`

### Request

```http
POST /api/dialogue HTTP/1.1
Content-Type: application/json

{"question": "Do back-to-backs and rest days change who wins?"}
```

- The body must be **exactly** `{"question": <string>}`, with no other fields.
- `question` must be 1–500 characters after trimming whitespace.
- The body must be at most 16 KiB.

### Response `200`: fields

| Field | Type | Always present | Meaning |
|---|---|---|---|
| `heater_text` | string | yes | Heater's line: entertainment, **not evidence**. Model-written when a key is set. If the model fails, times out (8 s) or uses a number not in the record, a fixed line is used instead (see `sources.heater`). |
| `ref_text` | string | yes | The Ref's ruling. **Deterministic**: a template built only from the evidence entry, with no model call. Show it as the verdict text. |
| `verdict` | string \| null | yes | One of `SURVIVED_PROTOCOL`, `NOT_SUPPORTED`, `INSUFFICIENT_EVIDENCE`, `DATA_INVALID`, `BLOCKED`, or `null` when there is no verdict (see the cases below). |
| `evidence_record_id` | string \| null | yes | 64-hex `evidence_id` of the ledger entry behind the verdict, or `null`. Look it up in the ledger (Experience's `GET /api/evidence` shows the same file). |
| `claim_id` | string | yes | Registered claim id, or `"NONE"`. |
| `claim_title` | string | yes | Display title for `claim_id` (same map as `/api/display-titles`). |
| `lane` | string \| null | yes | `DEVELOPMENT` (2023-24), `CONFIRMATORY` (2024-25 sealed family), or `null`. |
| `evidence_source` | string \| null | yes | `AGENT_LOOP` (the Referee ran registered attacks now), `RECORDED_RESEARCH_RESULT` (a receipted Research final copied into the ledger, not recomputed), or `null`. |
| `sources` | object | yes | Where each part came from, for transparency or debugging: `mapping`, `heater`, `ref`, and usually `challenger`. Values are strings such as `LLM`, `KEYWORD_STANDIN`, `TEMPLATE`, `TEMPLATE (fallback: …)` or `TEMPLATE (guard rejected numbers […])`. Do not parse them for logic. |
| `phase` | string | only for recorded entries | `FINAL`. |
| `custodian_receipt_id` | string | only for recorded entries | Research custodian exposure receipt, e.g. `3e238d2d-030e-45b4-aae7-db0787ecb873`. |
| `confirmatory_status` | string | only for confirmatory dry run | `UNRUN_NOT_READY`, `UNRUN`, `RESERVED_INCOMPLETE` or `FINAL_DONE`. |
| `dry_run` | object | only for confirmatory dry run | `{"ready": bool, "checks": [{"check", "status": PASS\|FAIL\|NOT_CHECKED, "detail"}]}`. |

Treat unknown extra fields as additive and ignore them.

### The five cases

| Case | `verdict` | `evidence_record_id` | `evidence_source` | Ledger written? |
|---|---|---|---|---|
| Registered claim run by the agent loop (HH-K3, HH-K2) | a verdict | id of the new entry | `AGENT_LOOP` | yes, one entry |
| Claim with a recorded Research final (GP-REST, GP-ELO; CONF-* after their final) | the recorded verdict | id of the recorded entry | `RECORDED_RESEARCH_RESULT` | no |
| No registered test (`claim_id: "NONE"`) | `null` | `null` | `null` | no |
| Recorded-only claim with no record in this ledger | `null` | `null` | `null` | no |
| Confirmatory claim before its final (dry run) | `null` | `null` | `null` | no |

**UI rule:** show a verdict badge only when `verdict` is non-null. With `null`, show
`ref_text`: it says why there is no verdict.

### Examples

Agent loop (HH-K2):

```json
{
  "heater_text": "Heater here, and OUCH. The Ref says not supported. I'll be back with a hotter take.",
  "ref_text": "Not supported by the registered checks (NOT_SUPPORTED). Hot hand: two makes in a row (HH-K2). What was tested: Same as HH-K3 with streak length 2. Why: p=0.2390 (alpha 0.05), bias-corrected effect +0.0740 (floor 0.01).",
  "evidence_record_id": "<64 hex: new entry>",
  "verdict": "NOT_SUPPORTED",
  "claim_id": "HH-K2",
  "claim_title": "Hot hand: two makes in a row",
  "lane": "DEVELOPMENT",
  "evidence_source": "AGENT_LOOP",
  "sources": {"ref": "TEMPLATE", "mapping": "KEYWORD_STANDIN", "challenger": "DETERMINISTIC_STANDIN", "heater": "TEMPLATE"}
}
```

Recorded final (GP-REST):

```json
{
  "heater_text": "Heater here! The Ref wants more evidence before ruling. Patience is NOT my game, but rules are rules.",
  "ref_text": "Insufficient evidence (INSUFFICIENT_EVIDENCE). Rest and back-to-backs on top of Elo (GP-REST). What was tested: Rest-day difference and back-to-backs improve pre-tip win forecasts over Elo. Why: CI includes values on both sides of the decision thresholds. Source: Research's recorded final run on 300 unseen 2023-24 games, under a custodian exposure receipt; copied here, not recomputed.",
  "evidence_record_id": "6a67b1820c0869128c6f65ba7289a55c21cb4fc5ee600105302078c7091b2e8d",
  "verdict": "INSUFFICIENT_EVIDENCE",
  "claim_id": "GP-REST",
  "claim_title": "Rest and back-to-backs on top of Elo",
  "lane": "DEVELOPMENT",
  "evidence_source": "RECORDED_RESEARCH_RESULT",
  "sources": {"ref": "TEMPLATE", "mapping": "KEYWORD_STANDIN", "challenger": "NOT_APPLICABLE (recorded final result)", "heater": "TEMPLATE"},
  "phase": "FINAL",
  "custodian_receipt_id": "3e238d2d-030e-45b4-aae7-db0787ecb873"
}
```

No registered test:

```json
{
  "heater_text": "Heater here, and I've got OPINIONS! But the Ref says there's no registered test for that one, so take this as pure hot air.",
  "ref_text": "No registered test exists for this question, so nothing was run and there is no verdict. Registered claims: HH-K3, HH-K2, GP-REST, GP-ELO, CONF-HA, CONF-MOM, CONF-HH.",
  "evidence_record_id": null, "verdict": null, "claim_id": "NONE", "claim_title": "No registered test",
  "lane": null, "evidence_source": null,
  "sources": {"ref": "TEMPLATE_NO_REGISTERED_TEST", "mapping": "KEYWORD_STANDIN", "heater": "TEMPLATE"}
}
```

Confirmatory dry run (CONF-HA, abridged `checks`):

```json
{
  "heater_text": "Heater here! That one's locked in the vault for its one big official run. No peeking, no verdict yet. I'm DYING to know.",
  "ref_text": "CONF-HA is a pre-registered confirmatory claim on the sealed 2024-25 season: In 2024-25 NBA regular-season games not played at a neutral site, the designated home team wins more than half of the games. Its single final test has not been run, so there is no verdict yet. It runs once, recorded, after the reviewer verifies the seal. Dry run: plans, code and seal match; the sealed data were not checked on this machine.",
  "evidence_record_id": null, "verdict": null, "claim_id": "CONF-HA",
  "claim_title": "Home advantage (2024-25, confirmatory)", "lane": "CONFIRMATORY", "evidence_source": null,
  "confirmatory_status": "UNRUN_NOT_READY",
  "dry_run": {"ready": false, "checks": [{"check": "family_manifest", "status": "PASS", "detail": "…"}, "…"]},
  "sources": {"ref": "TEMPLATE_CONFIRMATORY_NOT_RUN", "mapping": "KEYWORD_STANDIN", "heater": "TEMPLATE", "challenger": "NOT_APPLICABLE (confirmatory: frozen pre-registered procedure)"}
}
```

### Errors

Every error body is `{"error": <message>}`. These messages are the exact strings from the capture.

| Status | When | `error` |
|---|---|---|
| 400 | No body, or a body larger than 16 KiB | `missing or oversized body` |
| 400 | Body is not JSON | `body is not JSON` |
| 400 | Not an object, or keys other than exactly `question` (e.g. `{}`, an extra field) | `body must be exactly {"question": string}` |
| 400 | `question` is empty, whitespace only, or not a string | `question must be a non-empty string` |
| 400 | `question` is longer than 500 characters | `question longer than 500 characters` |
| 404 | Unknown path | `not found` |
| 500 | The turn itself failed: no verdict is invented | `turn failed: <ExceptionClassName>` |

The server never answers a model failure with an error status. A model timeout, HTTP error,
missing key or guard rejection falls back to deterministic text inside a `200` response.

### Timing

Measured on 2026-11-07; see `reports/max/`.
- **Template mode:** about 0.2 s for a recorded or no-test answer.
- **Agent-loop claims:** add the permutation attacks, which take seconds on a large view.
- **With a model key:** add the mapping call and Heater's call, each capped at 8 s.

Use a client timeout of at least 30 s and show a waiting state.

## `GET /api/display-titles`

```json
{"display_titles": {
  "HH-K3": "Hot hand: three makes in a row",
  "HH-K2": "Hot hand: two makes in a row",
  "GP-REST": "Rest and back-to-backs on top of Elo",
  "GP-ELO": "Elo vs the home-win base rate",
  "CONF-HA": "Home advantage (2024-25, confirmatory)",
  "CONF-MOM": "One-shot momentum (2024-25, confirmatory)",
  "CONF-HH": "Hot hand: three in a row (2024-25, confirmatory)",
  "NONE": "No registered test"}}
```

The titles are **presentation only** (`heatcheck/api/display_titles.py`). They are never part
of a plan, a plan hash, an evidence identity or an evidence id, so they can change without
touching any evidence. Use them for display, and still show `claim_id` somewhere for
traceability. If an id has no title, show the id itself.

## Minimal client

```js
async function askHeater(question) {
  const r = await fetch("http://127.0.0.1:8770/api/dialogue", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });
  const body = await r.json();
  if (!r.ok) throw new Error(body.error);          // 400 / 404 / 500
  return body;  // render heater_text (entertainment), ref_text + verdict badge (evidence)
}
```

Render all text with `textContent`, never `innerHTML`.

## `POST /api/investigate` (MARKET_COMPARISON, read-only, descriptive)

Enabled by `tools/serve_dialogue.py ... --live-forecast F --quote-bundle DIR [--recorded]`;
`503` when not configured. Code: `heatcheck/agents/market_investigation.py`.

Request: exactly `{"game_id": "nba:<10 digits>", "mapping_id": "<VENUE_MAPPING mapping_id>",
"message": "<0..500 chars>"}`. The server resolves the forecast row and quotes from its own
validated files. It never accepts forecast or price numbers from the client.

Response `200`: `format, mode (LIVE|RECORDED), as_of_utc, data_note, is_sample, label, game{},
team, flag (FORECAST_ABOVE_ASK|FORECAST_BELOW_BID|FORECAST_INSIDE_SPREAD|NO_TWO_SIDED_QUOTE),
forecast{p_team_win, model, inputs_used, data_cutoff_utc}, quote{record_id, venue, best_bid,
best_ask, received_utc, status}|null, heater_text, heater_source, hypothetical,
challenger_checks[{check_id, status PASS|FAIL|INFO, detail}], thesis|null, verdict, ref_text,
evidence_id, recorded_at_utc`. Probabilities and prices are decimal strings.

- `verdict` is exactly `Worth investigating · Edge unverified` (game, team, outcome matched,
  verified mapping, fresh two-sided quote, cutoff before tip, non-SAMPLE forecast) or
  `Can't compare`. Nothing else. Show `data_note` on screen; it says SAMPLE or RECORDED.
- Checks: GAME_MATCH, OUTCOME_MATCH, QUOTE_FRESH (LIVE limit 60 s; also before tip), QUOTE_SIDE,
  FORECAST_CUTOFF, MISSING_INPUTS (info), MARKET_SKILL_EVIDENCE (info: none exists), and
  FORECAST_SAMPLE when the forecast is a sample.
- `heater_text` cites only `inputs_used` and card numbers; other factors appear only as
  questions. A guard-rejected or unavailable LLM falls back to a template (`heater_source`).
  A "what if X is out?" message gets the fixed answer (`hypothetical: true`).
- `thesis` appears when the message raises rest/back-to-backs: Research's recorded GP-REST result.
- Every call is appended to the investigation ledger (default `logs/market_investigations.jsonl`)
  with forecast, quote, checks, verdict and timestamps; the message is stored as a hash only.
- `404 {"error"}` when the game is not in the forecast file or the mapping/quote is not in the
  bundle. `200` with `Can't compare` and `evidence_id: null` when the forecast file is missing
  or invalid.
