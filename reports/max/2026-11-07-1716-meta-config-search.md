# Max report: Meta Model API config search

Written 2026-11-07 17:16 UTC (commit time of 6c6a8e9) on branch `max/integrate-r001-e001`. The user authorised up to 10
calls (well under $0.10) to find a working config. **7 calls were used, costing about
$0.0104.**
- Scripts: `logs/2026-11-07-meta-config-search/probe.py` (streaming chat) and `probe_json.py`
  (structured mapping).
- Each call's raw output is in `c0N_*.json` in the same folder.
- The key was never printed.

## Verdict

**PASS: a working config was found.** `muse-spark-1.3`, `reasoning_effort: "minimal"`,
`max_completion_tokens: 1024`, streaming. The first text arrived at **1.43 s**, under the 4 s
target, and the reply was complete at 1.96 s. Use it for both Heater and the claim mapping.

## Models on the account (call 1, `GET /v1/models`)

- **Text:** `muse-wonder-1.0`, `muse-spark-1.3`, `muse-spark-1.2`, `muse-spark-1.1`.
- **Excluded:** `muse-spark-1.3-contributor` and `muse-spark-1.2-contributor` (Meta may train
  on our data).
- **Not chat models:** `sam-3.1`, `muse-image-1.0`, `muse-voice-transcribe-1.0`.
- **No non-reasoning chat model is listed.** All four text models used reasoning tokens even at
  `minimal`.

## What was tried

Calls 2–5 used the Heater prompt: "You are Heater, a loud, original sports-debate pundit. In
at most two short sentences, give a hot take on: 'Is the hot hand in basketball real?'"

All used `max_completion_tokens` 1024 and SSE streaming with `include_usage`.

| # | UTC | Model | Effort | Mode | HTTP | First text | Total | Prompt / completion / reasoning tokens | Approx. cost | finish |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 17:14:52 | (list models) | – | GET | 200 | – | 0.78 s | – | 0 | – |
| 2 | 17:15:00 | **muse-spark-1.3** | minimal | stream | 200 | **1.43 s** | **1.96 s** | 44 / 98 / 41 | $0.00047 | stop |
| 3 | 17:15:09 | muse-spark-1.2 | minimal | stream | 200 | 2.38 s | 3.35 s | 44 / 133 / 89 | $0.00062 | stop |
| 4 | 17:15:13 | muse-spark-1.1 | minimal | stream | 200 | 3.92 s | 4.15 s | 44 / 720 / 666 | $0.00312 | stop |
| 5 | 17:15:26 | muse-wonder-1.0 | minimal | stream | 200 | 2.84 s | 3.36 s | 44 / 217 / 132 | $0.00452 | stop |
| 6 | 17:15:50 | muse-spark-1.3 | minimal | json_schema, no stream | 200 | – | 1.39 s | 204 / 138 / 120 | $0.00084 | stop |
| 7 | 17:15:58 | muse-spark-1.3 | minimal | json_schema, no stream | 200 | – | 1.68 s | 198 / 147 / 131 | $0.00087 | stop |

Earlier calls, for context:
- 17:00: no effort set, `max_completion_tokens` 256.
- 17:05: effort `none` returned HTTP 400.
- 17:05: effort `low` with `max_tokens` 256.

All three produced no text. Two caused the failure:
- the 256-token budget, which reasoning used up;
- "none" being unsupported. The supported values are minimal, low, medium, high, xhigh, max.

Texts returned, verbatim (the model's own output):
- **#2:** "HOT HAND IS 100% REAL AND THE NERDS WITH THEIR SPREADSHEETS CAN KICK ROCKS! You don't
  need math when a guy hits three straight — GET HIM THE BALL AND GET OUT THE WAY!"
- **#4** (1.1) named a real player ("Steph"). The Heater system prompt must forbid real names.
- **#6:** "Do guys who hit three in a row keep shooting better, or is that a myth?" →
  `{"claim_id": "HH-K3"}`.
- **#7:** "Do left-handed players shoot better free throws on Tuesdays?" →
  `{"claim_id": "NONE"}`.

`response_format: json_schema` with a strict `enum` of registered ids plus NONE is accepted.

## Chosen configuration

| Use | Model | Settings | Expected latency |
|---|---|---|---|
| Heater free text | `muse-spark-1.3` | minimal, max_completion_tokens 1024, stream | about 1.4 s to first text |
| Question → claim id / NONE | `muse-spark-1.3` | minimal, json_schema enum, no stream | about 1.4–1.7 s |
| Ref phrasing | `muse-spark-1.3` | minimal, no stream; deterministic number/verdict guard with template fallback | not separately measured |

Every call has an 8 s timeout and falls back to the deterministic path.

## Limits

- n=1 per config. Latency varies from run to run and was not sampled repeatedly.
- 1024 tokens is a cap, not a guarantee: 1.1 used 720.
- A `finish_reason` other than `stop`, or empty text, is treated as failure, which triggers the
  fallback.
