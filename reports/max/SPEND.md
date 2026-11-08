# Max: paid model spend log (Meta Model API)

Approved budgets:
- **Up to $5 total for testing** (user, 2026-11-07, about 19:50 UTC).
- Earlier, "well under $0.10" for config tests.

Prices: `muse-spark-1.3` costs $1.25 per 1M input tokens and $4.25 per 1M output tokens,
reasoning tokens included. Costs below are estimates from token counts in the API's usage
fields. They are not invoiced amounts.

Model rules:
- Only non-contributor models (no training opt-in) are used.
- Every run writes per-call JSON lines with role, status, latency, tokens and est_cost_usd.

| UTC (2026-11-07) | Run | Calls (billed / logged) | Est. cost (USD) | Raw log |
|---|---|---|---|---|
| ~17:00 | First test call (256-token cap, empty text) | 1 / 1 | ≤ 0.0012 (upper bound: usage not recorded) | `logs/2026-11-07-meta-api-test/result.json` |
| ~17:06 | `reasoning_effort` none (HTTP 400, not billed) and low (256-token cap) | 1 / 2 | ≤ 0.0012 (upper bound) | `logs/2026-11-07-meta-api-test2/` |
| ~17:16 | Config search: 6 completions plus a models list | 6 / 7 | 0.006898 | `logs/2026-11-07-meta-config-search/` |
| 17:27 | First live dialogue turn (4 calls, 1 HTTP 400 `uniqueItems`) | 3 / 4 | 0.006536 | `logs/2026-11-07-dialogue-live/llm_usage.jsonl` |
| 19:54 | Live end-to-end, 5 turns (this report) | 13 / 13 | 0.027300 | `logs/2026-11-07-live-e2e/llm_usage.jsonl` |
| 19:56 | BLOCKED turn rerun after the `ref_brief` fix (1 Heater TIMEOUT) | 2 + 1 timed out / 3 | 0.002615, plus ≤ 0.0044 for the timed-out call (usage not returned) | `logs/2026-11-07-live-e2e-blocked-rerun/llm_usage.jsonl` |
| 20:40 | Live end-to-end, 6 turns, deterministic Ref (mapping + Heater only) | 12 / 12 | 0.017785 | `logs/2026-11-07-live-e2e-ref-template/llm_usage.jsonl` |
| 21:25 | Demo run with the model on (Discoverer map + Heater; 1 map TIMEOUT, usage not returned) | 5 + 1 timed out / 6 | 0.008061, plus ≤ 0.0044 for the timed-out call | `logs/llm_usage.jsonl` (git-ignored), rows 2026-11-07T21:25:12–21:26:09Z |
| 8 Nov 01:53 | Heater idea proposer, "Does rest matter?" (muse-spark-1.3, 535 + 628 tokens) | 1 / 1 | 0.003338 | `data/max/idea_requests/does_rest_matter_heater_dev.model_output.json`; `logs/llm_usage.jsonl` |
| **Total** | | | **≈ 0.072 logged; ≤ 0.084 with upper bounds** | |

Remaining under the $5 approval: at least $4.91 (updated 8 Nov 02:20 UTC).

The demo (`demo.cmd`) makes live calls whenever `META_API_KEY` is set. Those calls are logged
to `logs/llm_usage.jsonl` (git-ignored) and are not in this table. A turn costs about
$0.003–0.008.
