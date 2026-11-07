# HeatCheck-Experience

The interface, voice, source-capture and read-only venue-adapter layer of HeatCheck
(protocol `heatcheck-nba/1`). It is built for the **Pro Experience** role in the coordinated handoff.

It is a working local application. It is **not** a real NBA research result: every
number it produces comes from a sealed synthetic league or an authored market fixture,
and each one is labelled as such.

## Run it

Requirements: Python 3.11+ with `numpy` and `scipy`. No other packages, no build step.

```bash
python3 -m server.app            # http://127.0.0.1:8765  (binds localhost only)
```

Optional environment:

| Variable | Effect |
|---|---|
| `META_API_KEY` | Enables server-side push-to-talk transcription via Meta `muse-voice-transcribe-1.0`. Without it, `/api/transcribe` returns `BLOCKED` and the UI says so. |
| `HEATCHECK_KALSHI_BASE` | Overrides the Kalshi base URL (default `https://api.elections.kalshi.com/trade-api/v2`). |
| `HEATCHECK_QUIET` | Silences request logging. |

Browser extension: load `extension/` unpacked (`chrome://extensions` → Developer mode →
Load unpacked). Paste the pairing code shown under **Attach evidence**.

## Tests

```bash
python3 -m unittest discover -s tests -v          # 68 unit + HTTP API tests
python3 -m server.app &                           # then, with Playwright + Chrome available:
node tests/e2e_browser.mjs                        # real headless-Chrome journey, writes evidence/
node tests/e2e_extension.mjs                      # extension load + selection capture
bash tools/run_checks.sh                          # all of the above, logged to evidence/test_run.log
python3 -I tools/build_fixtures.py                # regenerate contracts/fixtures from real outputs
```

## Layout

```
server/
  app.py             HTTP API + static server (stdlib); plans, runs, reveal, export, market endpoints
  authority.py       revisions, exact-plan confirmation, request identity, late-callback rules
  contracts.py       strict envelope validation against contracts/Shared_Protocol.json
  intake.py          rule-based claim interpretation with source spans and open questions (no LLM)
  files.py           bounded file intake, preview, provenance, CSV formula neutralisation
  engine_fixture.py  LOCAL FIXTURE ENGINE (SYNTHETIC only): custodian, Discoverer/Challenger/Referee loop, harness
  venues.py          read-only Polymarket + Kalshi adapters (allowlist, no redirects, bounded retry)
  venue_fixtures.py  authored SYNTHETIC venue payloads, one per market-semantics case
  mapping.py         EventMapping proposals; approval needs a named human
  comparison.py      forecast vs one typed quote → MarketComparison envelope
  quotes.py          STAND-IN quote normaliser (Research owns the canonical one, gate G11)
web/                 index.html, app.js, voice.js, style.css (no framework, CSP script-src 'self')
extension/           MV3 selected-tab extension (activeTab + scripting, localhost host permission only)
contracts/           Shared_Protocol.json + fixtures/valid, fixtures/invalid (generated from real outputs)
tests/               test_core.py, test_api.py, e2e_browser.mjs, e2e_extension.mjs
evidence/            acceptance_ledger.json, test logs, e2e results, screenshots, harness_batch.json
```
