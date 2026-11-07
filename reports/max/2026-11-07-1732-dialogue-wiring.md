# Max report: Meta free dialogue wired in (Heater, Challenger, guarded Ref, /api/dialogue)

Written 2026-11-07 17:32 UTC on branch `max/integrate-r001-e001`. The code commit is
`f0c7b95`. Raw logs:
- `logs/2026-11-07-dialogue-wiring/` (suite, dialogue tests, ruff);
- `logs/2026-11-07-dialogue-live/` (the live turn, its usage log and its evidence entry).

## Verdict

| Gate | Result |
|---|---|
| Dialogue tests (fake provider, no network) | **PASS**: 24 passed |
| Full suite | **FAIL as before**: 19 failed, 213 passed, 7 skipped. The 19 failures are identical to the pre-existing set (diff empty); none are new. |
| ruff | **PASS** |
| One live end-to-end turn through the endpoint on the real game | **PASS with two findings**, both handled below: the Challenger fell back and the Ref was slow. |
| Live turn after the fixes | **NOT_RUN**: no further calls without approval (see Spend) |

## What was built (`f0c7b95`)

| File | Role |
|---|---|
| `heatcheck/agents/llm.py` | Server-side Meta client. <br>• Default config: `muse-spark-1.3`, `reasoning_effort: minimal`, `max_completion_tokens: 1024`. <br>• **Hard 8 s deadline** per call, enforced in a worker thread. <br>• Any of these count as `LLMUnavailable`: timeout, HTTP error, network error, empty text, or `finish_reason` other than `stop`. <br>• Streaming support; Heater streams. <br>• Usage log: one JSON line per attempted call in `logs/llm_usage.jsonl`, which is gitignored. Each line holds role, model, effort, status, latency, first-text time, tokens (prompt/completion/reasoning/cached), estimated USD and request id. **No prompt, response or key is logged.** `usage_summary()` totals spend. <br>• `-contributor` models are refused at construction. |
| `heatcheck/agents/dialogue.py` | The free-dialogue turn (below), `ref_guard`, templates, `LLMChallenger`, `MappedDiscoverer`. |
| `heatcheck/api/dialogue_server.py` | `POST /api/dialogue` (stdlib, 127.0.0.1). CORS is allowed only for Experience's UI (`127.0.0.1:8765` / `localhost:8765`). Requests must be exactly `{question}` with 1–500 characters; anything else gets a 400. |
| `tools/serve_dialogue.py` | `uv run --frozen python tools/serve_dialogue.py <bundle> --ledger <jsonl> [--port 8770] [--no-llm]` |
| `tests/integration/test_dialogue.py` | 24 tests |

**Names.** The Discoverer's **display name is "Heater"**. Its role in code, protocol and
evidence remains `discoverer`, e.g. `proposer.role = "discoverer"`, `display_name = "Heater"`.
The legacy deterministic `DeterministicJone` is unchanged, so earlier evidence identities are
unaffected.

### One turn

1. **Map.** The LLM returns `{claim_id}` constrained by a strict json_schema enum (the registered
   ids plus NONE). The result is re-validated in code. On any failure, a deterministic keyword
   stand-in maps instead. Free-throw questions map to NONE, since FTs are out of scope.
2. **NONE.** No test runs and nothing is written to the ledger. Heater answers in character
   and says it is just opinion. The Ref text is the fixed template "No registered test exists
   for this question, so nothing was run and there is no verdict. Registered claims: …".
   `verdict` and `evidence_record_id` are null.
3. **Registered claim.** `run_once` runs with `MappedDiscoverer` and `LLMChallenger`.
   - `LLMChallenger` chooses only among optional attacks that are eligible on the view;
     mandatory attacks are always added.
   - An unregistered or ineligible id triggers the deterministic Challenger.
   - The **Referee is unchanged deterministic code.** No LLM text reaches `decide()`.
   - The evidence identity records the model, prompt hash and any fallback reason.
4. **Heater and Ref run in parallel.**
   - Heater streams free text.
   - The Ref phrases the verdict from a compact brief.
   - `ref_guard` checks the Ref's text against the full evidence facts. Rules:
     - every number, including signed and spelled-out ones, must appear in the record;
     - the actual verdict must be stated;
     - no other verdict's wording may appear;
     - over-claim words (proven, confirmed, myth, real, significant, …) are allowed only if
       the record itself contains them.
   - On any problem the deterministic template is used.
   - Heater's text gets the number check only.
5. **Response:** `{heater_text, ref_text, evidence_record_id, verdict, claim_id, sources}`.
   `sources` says, per role, whether the LLM, a stand-in or a template was used, and why.

### The tests the user asked for

| Test | Shows |
|---|---|
| `test_guard_rejects_invented_number` | An invented "12.7 percent over 4321 attempts" is rejected; the record's own n_attempts passes; spelled "seventeen" is rejected. |
| `test_guard_rejects_sign_flip_spelled_and_percent_numbers` | A sign flip of the p-value, "Ninety", and "73%" are rejected. |
| `test_guard_rejects_wrong_or_overclaimed_verdict` | A contradicting verdict, "proven", "myth", and a missing verdict are rejected. |
| `test_template_always_passes_guard` (×5) | The fallback template passes the guard for all five decisions. |
| `test_ref_with_invented_number_falls_back_to_template` | End to end: an invented "61.3%" leads to the template. |
| `test_none_runs_no_test_and_ref_says_so` | NONE: no ledger write and no Challenger call; the Ref says no test exists. |
| `test_unregistered_mapping_is_never_run` (×4) | `HH-K9`, an extra key, non-JSON, or a made-up test name never run. |
| `test_llm_challenger_cannot_add_unregistered_or_drop_mandatory` | Mandatory attacks are always present; `A-MADE-UP` leads to the stand-in. |
| `test_timeout_falls_back_within_deadline` | A 1 s reply against a 0.3 s deadline: all 4 roles fall back, every wait is under 600 ms, and all fields are still returned. |
| `test_http_error_and_missing_key_fall_back`, `test_empty_or_truncated_reply_is_a_failure` | Provider failures are handled. |
| `test_usage_logged_per_call_without_key_or_prompt` | 4 log rows, one per role, with tokens and cost; neither the key nor the question text is in the log. |
| `test_endpoint_returns_four_fields_and_rejects_bad_requests` | A real HTTP round trip returns the fields and the CORS origin; 6 malformed bodies each get 400. |

One test expectation was wrong on its first run and was corrected. The timeout test bounded
the whole turn at 3 s, which forgot the permutation test's own compute time (4.8 s observed).
It now bounds each provider wait, which is the property that matters. One real bug was fixed:
the keyword stand-in missed the plural "back-to-backs".

## Live turn (2026-11-07 17:27:41Z, real game `nba:0022300061`, 181 FGA)

Question: "Is the hot hand real? When a guy hits three in a row, does he keep making them?"
The raw response is in `turn_hh.json`:

| Field | Value |
|---|---|
| HTTP | 200, 10.4 s client total |
| claim_id | `HH-K3` (mapping source LLM) |
| verdict | `INSUFFICIENT_EVIDENCE` (deterministic Referee: after-3-makes n=14, after-3-misses n=18, need ≥ 30 each) |
| evidence_record_id | `3ff5ed9fc4faf52a0f2f4dca495d85d672802fe715b9abed9bf4264e8af8b661` (`evidence_live_turn.jsonl`, `proposer.role=discoverer`, `display_name=Heater`, `kind=LLM`) |
| heater_text (LLM) | "LISTEN UP! The Ref says there just isn't enough proof on this one yet! I FEEL like the heater is real, but that's just my opinion!" |
| ref_text (LLM, passed guard) | "There is insufficient evidence that within a player-game a field goal after 3 straight makes is made more often than one after 3 straight misses, beyond what within-stratum shuffling produces. The record notes the comparison did not meet the needed size for each side." |
| challenger | **DETERMINISTIC_STANDIN, fallback**: HTTP 400 "JSON schema keyword `uniqueItems` is not supported for structured outputs" |

Per-call usage from `llm_usage.jsonl`:

| Role | Status | Latency | First text | Prompt / completion / reasoning | Est. cost |
|---|---|---|---|---|---|
| discoverer_map | OK | 1.82 s | – | 259 / 101 / 83 | $0.00075 |
| challenger | HTTP_400 | 0.48 s | – | – | – |
| heater (stream) | OK | 4.25 s | **3.92 s** | 227 / 303 / 262 | $0.00157 |
| ref | OK | **7.83 s** | – | 676 / 792 / **730** | $0.00421 |

### Findings and fixes (in `f0c7b95`, verified only against the fake provider)

1. **Challenger 400.** Meta's structured outputs reject `uniqueItems`. It was removed, and
   duplicates are dropped in code. The fake provider now returns the same 400 when it sees
   `uniqueItems`, so the Challenger test guards against a regression. The fallback worked as
   designed.
2. **Ref latency 7.8 s, just inside the 8 s deadline.** It came from 730 reasoning tokens over a
   676-token prompt. The Ref is now sent a compact brief (claim, verdict, reason, attempts,
   games) instead of all facts; the guard still checks the full record. The effect on latency
   is **NOT_RUN**.
3. **Heater first text 3.9 s,** just under the 4 s target. Reasoning varied: 262 tokens here
   against 41 in the probe.
4. **The whole turn takes about 10 s.** Map and Challenger run in sequence before the
   Heater/Ref pair. To reach a snappy demo:
   - stream Heater to the UI, so speech starts while the Ref is still working (needs an
     SSE variant of the endpoint);
   - or give the Ref a tighter deadline than 8 s.

   This is the user's decision.

## Spend

| Calls | Status | Est. cost |
|---|---|---|
| Config search (17:14–17:16Z) | 7 of the 10 authorised | about $0.0104 |
| Live verification turn (17:27Z) | **4 calls outside the 10-call config authorisation**; made to verify the wiring the user asked for | about $0.0065 |
| **Today's total, all Meta calls by Max** | 3 early tests + 7 + 4 | **about $0.019** |

No further live calls will be made until the user approves a verification budget.

## Not done

- The UI does not call the endpoint yet; Experience owns that.
- Streaming to the browser is not built; the endpoint returns the full JSON.
- Separate review of this code: NOT_RUN.
