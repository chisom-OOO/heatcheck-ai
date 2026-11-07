# Handoff: HeatCheck-Experience → Max (integration) and Research

Protocol: `heatcheck-nba/1` (contracts/Shared_Protocol.json, unchanged copy of the pack).
Branch status: local build only; no push, deployment, outside message or paid service was used.

## Assumptions I made (change any of these and tell me)

1. **Role.** This is the Pro Experience deliverable: interface, voice, source capture, read-only venue adapters and interaction evidence.
2. **Vocabulary.** Shared_Protocol.json wins over heat-check-agents-spec.md. The UI and envelopes use SURVIVED_PROTOCOL / NOT_SUPPORTED / INSUFFICIENT_EVIDENCE / DATA_INVALID / BLOCKED. REAL/LUCKY, LMSR markets, Elo and appeals are not surfaced.
3. **No package installs.** The server is Python stdlib plus numpy/scipy. The web app is plain ES modules with no framework or build step.
4. **Research engine and forecasts were not delivered.**
   - A local fixture engine (`server/engine_fixture.py`) runs the hot-hand streak claim on sealed synthetic leagues.
   - REAL_NBA_RETROSPECTIVE plans are shown as BLOCKED with a reason. No real NBA result is produced or implied.
   - The game forecast is one authored fixture, labelled SYNTHETIC, with no calibration.
5. **Quote arithmetic.** `server/quotes.py` is a stand-in until Research's normaliser exists (G11). Calls are isolated in `comparison.py`.
6. **EventMapping trust.** Approval requires a named human reviewer and an unchanged rules hash. Automated, model or role names are refused. Max still owns the full trusted workflow: reviewer identity and persistence.
7. **No LLM in the loop.** Claim interpretation is rule-based (`intake.py`). It proposes fields with source spans and lists every open question rather than choosing.
8. **Voice is push-to-talk**, not always-on, and has no wake word.
   - Browser speech is disclosed as going to the browser vendor's service.
   - Server transcription uses Meta `muse-voice-transcribe-1.0` (`POST https://api.meta.ai/v1/asr/transcribe`, multipart `request`+`audio` WAV 16 kHz). It is only enabled when `META_API_KEY` is set.
9. **Freshness thresholds are configured before any demo:**
   - historical comparison: the quote must be observed ≤ 600 s before the forecast cutoff, and never after it;
   - live comparison: ≤ 60 s old.

## API consumed and offered (127.0.0.1:8765, JSON unless noted)

| Method | Path | Purpose |
|---|---|---|
| GET | /api/health | versions, code hash, provider availability |
| POST | /api/session · GET /api/session/{id} | session state: revision, claim, sources, plan, confirmation, runs |
| POST | /api/interpret | `{text}` → proposal or literal command |
| POST | /api/claim | approve the fields; every required field must be present; bumps the revision and revokes confirmation |
| POST | /api/file?session_id= | raw body + `X-File-Name`; bounded, typed, previewed, hashed |
| POST | /api/page | selected page text/tables (extension or paste); untrusted |
| POST | /api/screen | frame hash + metadata only; nothing is extracted |
| POST | /api/plan | → `ClaimPlan` envelope + `executable`/`blocked_reason` |
| POST | /api/confirm | `{revision, plan_hash}` must match exactly |
| POST | /api/run | `{request_id, blind}`; idempotent per request_id; the blind config goes only to the custodian |
| GET | /api/run/{id}?session_id= | events, result (`EvaluationRun` + `AttackResult` envelopes) |
| POST | /api/cancel · /api/reveal | reveal only after a recorded decision |
| GET | /api/export/{run}?session_id=[&format=csv] | export of the stored run; the CSV is formula-safe |
| POST | /api/transcribe | WAV body → transcript, or 503 BLOCKED |
| GET/POST | /api/harness | synthetic batch: decisions by truth, tuning vs held-out, detectability |
| GET | /api/market-scenarios · POST /api/market-propose · /api/market-compare | `MarketSpec` → `EventMapping` → `BookSnapshot` → `MarketComparison` |
| GET | /api/gates | the acceptance ledger |

## What Research needs to plug in

- **Real evaluations.** Replace `engine_fixture.analyse` behind `app._run_worker` with a call that takes the confirmed `ClaimPlan` and returns `EvaluationRun` and `AttackResult` envelopes plus `talent` rows (`shooter, attempts, makes, raw, shrunk, interval`). The UI renders exactly those fields.
- **Forecasts.** Provide `{forecast_id, game_id, team, probability, cutoff_utc, model, evidence_hash, calibration_scope, data_mode}` to replace `venue_fixtures.FORECAST`.
- **Normaliser.** Swap `quotes.normalise_*`/`compare` for the checked normaliser. `tests/test_core.py::TestQuotes` and `TestComparison` assert the expected values.

## Known limits (not hidden in the UI)

- **Live venue fetch has not run (G12).** This workspace's egress proxy denies polymarket.com and kalshi.com. The adapters were written from the vendor docs read on 7 Nov 2026 and tested only against authored payloads.
- **Live venue fetch fails behind any HTTP proxy.** The adapter refuses private/loopback DNS answers by resolving locally. Where DNS is only available through a proxy, live fetch reports UNAVAILABLE rather than bypassing the check.
- **No real microphone was used.** Chrome's fake media device exercised the push-to-talk and recording path. Latency figures need a real mic session; the table in the Evidence tab records them.
- **Screen capture is untested.** It cannot be exercised headless, because the browser permission picker needs a real user gesture.
- **Discovery is by explicit identifier only.** Kalshi takes a ticker and Polymarket a slug; free-text event search is not implemented.
- **Sessions are in memory.** A restart clears them. Exports are the durable record.
