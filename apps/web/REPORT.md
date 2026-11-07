# What this build actually ran

HeatCheck-Experience, local build, 7 Nov 2026. Everything below was executed in this workspace;
the raw output is in `evidence/test_run.log`, `evidence/e2e_results.json`,
`evidence/extension_results.json`, `evidence/harness_batch.json` and `evidence/screenshots/`.

```
date_utc: 2026-11-07T15:43:42Z
host: Linux 6.18.44-fc-v310 x86_64
python: Python 3.13.18 numpy: 2.5.3 scipy: 1.18.1
node: v22.23.4  chrome: Google Chrome for Testing 153.0.8010.12 
```

## Test results (final code)

| Suite | Command | Result |
|---|---|---|
| Unit + HTTP API (Python) | `python3 -m unittest discover -s tests -v` | 68 tests, all pass |
| Real browser journey | `node tests/e2e_browser.mjs` (headless Chrome for Testing 153, real backend) | 66 checks pass, 0 fail, 17 s |
| Browser extension | `node tests/e2e_extension.mjs` (unpacked MV3 extension loaded) | 10 checks pass, 0 fail |

The browser run covers:
- claim journeys: ambiguous, unsupported and full;
- plan confirmation, the blind run, reveal and export;
- revocation on edit, historical export, cancel and double-click idempotence;
- hostile page HTML, restricted URLs, oversized and disguised files;
- REAL mode blocked, push-to-talk with a fake mic and no provider;
- 14 market scenarios, harness rendering, keyboard tabs, accessible names, dark mode;
- console errors and dialogs.

## Planted-truth harness (fixture engine, SYNTHETIC)

20 leagues per cell; 30 shooters x 300 attempts per league; streak length 3; 150 permutations per league in batch mode. 360 leagues total.
The custodian scored each blind decision only afterwards.

| | Null leagues that survived | Effect leagues that survived (power) |
|---|---|---|
| Tuning families | 3/80 (3.8%, 95% 1.3%–10.5%) | 59/80 (73.8%, 95% 63.2%–82.1%) |
| Held-out family (ar1_drift) | 1/40 (2.5%, 95% 0.4%–12.9%) | 27/40 (67.5%, 95% 52.0%–79.9%) |

| Family | Planted | SURVIVED | NOT_SUPPORTED | INSUFFICIENT |
|---|---|---|---|---|
| parametric_beta_binomial | null | 0/20 | 20/20 | 0/20 |
| parametric_beta_binomial | weak | 9/20 | 11/20 | 0/20 |
| parametric_beta_binomial | planted | 20/20 | 0/20 | 0/20 |
| parametric_beta_binomial | confounded | 0/20 | 20/20 | 0/20 |
| heavy_tailed_talent | null | 0/20 | 15/20 | 5/20 |
| heavy_tailed_talent | weak | 10/20 | 10/20 | 0/20 |
| heavy_tailed_talent | planted | 20/20 | 0/20 | 0/20 |
| heavy_tailed_talent | confounded | 3/20 | 17/20 | 0/20 |
| ar1_drift (held-out) | null | 1/20 | 19/20 | 0/20 |
| ar1_drift (held-out) | weak | 10/20 | 10/20 | 0/20 |
| ar1_drift (held-out) | planted | 17/20 | 3/20 | 0/20 |
| ar1_drift (held-out) | confounded | 0/20 | 20/20 | 0/20 |

**Detectability** (parametric family; survived out of 20 leagues): 0pp 0/20, 2pp 12/20, 4pp 20/20, 6pp 19/20, 8pp 19/20, 12pp 19/20.

**Weak spot:** the confounded heavy-tailed cell let 3 of 20 null leagues through. That is where an extra attack is most needed.
These numbers describe the fixture engine on its own simulator. They say nothing about real NBA shooting.

## Bugs that testing found and that were fixed

1. **Keep-alive desync.** Unread POST bodies, and the PUT/DELETE handler, corrupted the next request on the same connection. The server now always consumes the body; a regression test covers it.
2. **Hidden controls still showed.** Elements marked `hidden` were displayed because a CSS `display` rule overrode the attribute.
3. **Inline legend style violated the page's own CSP.** It is replaced with classes.
4. **Stale market panel.** The panel showed the previous result while a new request was pending. It now clears and says "Fetching…".
5. **Wrong voice state.** A typed command left the voice state stuck on TRANSCRIBING.
6. **Fixture timestamp error.** The authored Polymarket timestamp was a year off. The engine flagged it correctly as STALE_BOOK.
7. **REAL-mode loophole.** REAL mode could look executable if an environment variable was set. It is now always BLOCKED until an agreed Research endpoint exists.
8. **Two test expectations were wrong**, not the code:
   - the hand-counted streak statistic;
   - invalid fixtures that deleted optional rather than required fields.

## Not run, or only partly run

- **Live Polymarket/Kalshi fetch.** The workspace egress proxy refused both hosts. The UI shows UNAVAILABLE; gate G12 is BLOCKED.
- **Real microphone and Meta transcription.** There is no microphone and no `META_API_KEY`. Chrome's fake media device only exercised record → BLOCKED. No latency figures were recorded.
- **Screen capture** (`getDisplayMedia`). It needs a real picker gesture.
- **The extension toolbar click.** The popup was driven as a tab instead.
- **Research engine, real NBA data, forecasts and the canonical normaliser.** None of these were delivered, so their gates stay NOT_RUN.
- **Max's independent review and replay** (G16). **No gate is marked PASS.**

## Gate ledger after this run

| Gate | Status |
|---|---|
| G01 Data/provenance | NOT_RUN |
| G02 Temporal correctness | NOT_RUN |
| G03 Statistical oracles | NOT_RUN |
| G04 Registered adversarial tests | NOT_RUN |
| G05 Harness truth isolation | FIXTURE_ENGINE_EVIDENCE_ONLY |
| G06 Null and power | FIXTURE_ENGINE_EVIDENCE_ONLY |
| G07 Calibration separation | PARTIAL_FIXTURE_EVIDENCE |
| G08 Final-data/adaptivity | NOT_RUN |
| G09 Forecast comparison | NOT_RUN |
| G10 NBA event mapping | EXPERIENCE_EVIDENCE_PENDING_MAX |
| G11 Quote normalization | EXPERIENCE_FIXTURES_PASS_PENDING_RESEARCH |
| G12 Read-only live adapters | BLOCKED |
| G13 Authority/immutability | EXPERIENCE_EVIDENCE_PENDING_MAX |
| G14 Injection/resource/security | PARTIAL_EVIDENCE_EXPERIENCE_SCOPE |
| G15 Real interface/voice | PARTIAL_EVIDENCE |
| G16 Separate review/replay | NOT_RUN |
| G17 Demo and claims | NOT_RUN |
| G18 Eligibility/submission | NOT_RUN |
