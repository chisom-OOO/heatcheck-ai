# Max report: deterministic Ref, Research's recorded finals in the ledger, display titles, API contract

Written 2026-11-07 20:59 UTC on branch `max/integrate-r001-e001`. Code commit: `6468bd6`. Raw logs:
- `logs/2026-11-07-ref-recorded/`
- `logs/2026-11-07-live-e2e-ref-template/`
- `logs/2026-11-07-recorded-gp/`
- `logs/2026-11-07-api-doc/`

Spend for this step was $0.0178 (12 calls); the running total is in `SPEND.md`, about $0.061
logged of the $5 approved.

## 1. The Ref is deterministic

- **No model call.** `Dialogue._ref` and the Ref prompt are removed. `ref_text` is
  `ref_template(facts)`, built only from the evidence entry, in this shape:
  `<verdict phrase>. <display title> (<claim id>). What was tested: <statement>. Why: <reason>.`
  Recorded entries add a source note.
- **Numbers.** They appear only inside the record's own reason and source note, verbatim. I did
  not add rounded figures, because a rounded number would not be in the record. A test runs
  every committed entry's template through `ref_guard` and finds no problems.
- **Heater** is the only model-written text and keeps the number guard against the record.
  It is tested: an invented "61.3%" makes Heater fall back to its fixed line.
- **Mapping** still uses the model, with its existing keyword fallback.
- **Turn order:** map, then evidence, then Ref (instant), then Heater. Heater no longer runs
  in parallel with anything.

**Live latency** (6 turns, real calls; `tools/live_dialogue_e2e.py`):

| Case | Claim | Verdict | Map ms | Heater first text ms | Heater total ms | Turn wall ms | Cost USD |
|---|---|---|---|---|---|---|---|
| Agent loop | HH-K3 | INSUFFICIENT_EVIDENCE | 2388 | 3167 | 3411 | 6733 | 0.0034 |
| Agent loop | HH-K2 | NOT_SUPPORTED | 1541 | 3556 | 3890 | 6146 | 0.0030 |
| Recorded final | GP-ELO | SURVIVED_PROTOCOL | 2252 | 2712 | 3095 | 5389 | 0.0027 |
| Recorded final | GP-REST | INSUFFICIENT_EVIDENCE | 1549 | 2352 | 2633 | 4199 | 0.0026 |
| No registered test | NONE | none | 1544 | 2548 | 2676 | 4225 | 0.0027 |
| Confirmatory dry run | CONF-HA | none | 1649 | 3620 | 3717 | 5396 | 0.0034 |

**Before and after** (the 19:54 run, with the model-written Ref, against this run):

| Measure | Model-written Ref | Template Ref |
|---|---|---|
| Wall time, verdict turns | 5.8–8.5 s | 4.2–6.7 s |
| Model calls per verdict turn | 3 | 2 |
| Cost per turn | $0.0067–0.0080 | $0.0026–0.0034 |
| Ref time | 4.5–5.7 s | ~0 (template) |

**Other results of the run:**
- **Heater:** first text in 2.4–3.6 s, under 4 s in 6 of 6 turns. No timeouts, and no
  number-guard fallbacks.
- **Mapping:** 6 of 6 correct, and every verdict equals the committed entry.
- **Where the time goes now:** the mapping call (1.5–2.4 s), Heater's full reply, and for
  HH-K3/HH-K2 the permutation attacks. The endpoint returns everything at once, so the Ref
  text waits for Heater. Returning or streaming the Ref first would let the verdict appear
  about 3 s sooner; this is not done.
- **Heater lines** stayed in character, named no real person and used no numbers. On NONE
  Heater said "that's just my opinion".

## 2. Research's GAME_PREDICTION final recorded in the ledger (receipt `3e238d2d`)

**The recorder** (`heatcheck/agents/recorded.py`; command `tools/record_research_results.py <ledger> gp`)
**recomputes nothing.**

Before writing it checks:
- the plan's and the amendment's self-hashes (`a8d81292…` and `94fcd9ce…`), and that the
  amendment amends that plan;
- that the result names that plan and the receipt;
- that the custodian ledger has exactly one reserve for the receipt, naming the plan hash,
  plus a spend;
- that the reviewer-verified amended replay has **identical decisions**.

Each entry copies verbatim:
- the decision and reason;
- the numbers: `mean_improvement_nats`, `ci95`, `p_one_sided`, `p_holm`, `n_games`, `days`
  and `nonoverlap_7d_blocks`.

Each entry binds by sha256:
- the four files (`game_prediction_final.json` `163db64d…`, `claim_plan_GP.json`
  `a6cf299c…`, amendment `5988c776…`, replay `43280560…`);
- custodian ledger lines 1 (reserve), 2 (spend) and 3 (replay), each by the sha256 of its
  exact bytes.

Recording is idempotent; a second run writes nothing.

**Claim mapping:**
- H1 (rest and back-to-backs on top of Elo) is the registered **GP-REST**.
- H2 (Elo against the base rate) has no registry claim. It is recorded under a recorded-only
  id, **GP-ELO**. Its statement is my restatement of the H2 estimand in Research's plan, and
  the entry says so (`statement_source`). The registry is unchanged, so no plan hash changed.

**Committed ledger `evidence/evidence.jsonl`.** The chain verifies on every read.
- Lines 1–3 are byte-identical to the earlier loop log `evidence_real_game_v2.jsonl`.
- Line 4 is GP-REST, INSUFFICIENT_EVIDENCE (`6a67b182…`).
- Line 5 is GP-ELO, SURVIVED_PROTOCOL (`cebfede7…`). Both ids are in `logs/2026-11-07-recorded-gp/record_gp.txt`.
- The head is `8a356654…451d`.
- `evidence/README.md` explains each line.

**Dialogue.**
- A claim with a recorded final is answered from that entry: nothing is run and nothing is
  written.
- **GP-REST now shows INSUFFICIENT_EVIDENCE from the final**, with `evidence_source:
  RECORDED_RESEARCH_RESULT`, `phase: FINAL` and `custodian_receipt_id`. It no longer shows
  the loop's BLOCKED, which stays in the ledger as history (line 3).
- GP-ELO shows SURVIVED_PROTOCOL.
- The demo and the live tool now use `evidence/evidence.jsonl`. The demo warns when an older
  local demo ledger lacks committed entries.

**Same mechanism for the confirmatory results.** `ConfirmatoryLane` final mode now records
through `recorded.record`, replacing its own identity code. When the reviewer's Linux run
produces `final_result.json`, the entries will have the same shape and checks: the
reservation must name the family hash, and there must be a spend. A new test refuses a
reservation that names another plan.

**Tamper tests** (on copies; each leaves nothing written):

| Tamper | Refused because |
|---|---|
| Replay decision flipped | the replay no longer reproduces the original |
| Plan threshold edited | the plan's self-hash fails |
| Spend line removed | the receipt was never spent |
| Reserve names another plan | the reservation is for a different plan hash |

## 3. Display titles

`heatcheck/api/display_titles.py` is a presentation-only map, also served at
`GET /api/display-titles`:

| Claim | Title |
|---|---|
| HH-K3 | Hot hand: three makes in a row |
| HH-K2 | Hot hand: two makes in a row |
| GP-REST | Rest and back-to-backs on top of Elo |
| GP-ELO | Elo vs the home-win base rate |
| CONF-HA | Home advantage (2024-25, confirmatory) |
| CONF-MOM | One-shot momentum (2024-25, confirmatory) |
| CONF-HH | Hot hand: three in a row (2024-25, confirmatory) |
| NONE | No registered test |

- Responses carry `claim_title`, and the Ref template and the console page use it.
- Tests check that every id that can be mapped has a title, and that **no title string
  appears in the committed ledger**: titles never enter an identity.
- Registry statements, including the terse HH-K2 one, are unchanged.

## 4. Endpoint contract for Experience

`docs/DIALOGUE_API.md` covers:
- the server, CORS (8765 origins only), concurrency, and all four methods and paths;
- the request rules: exactly `{"question"}`, 1–500 characters, at most 16 KiB;
- every response field, with its type and when it is present, and the five response cases
  with their ledger effect;
- the exact error messages (400 ×5 kinds, 404, 500), timing advice and a minimal client.

The examples are real responses captured from the server (`logs/2026-11-07-api-doc/api_examples.json`).
A script checked that the doc's example texts match the capture exactly. The 8770 console
page stays as the fallback, and now shows the title, evidence source, phase and receipt.

## Checks

| Check | Result |
|---|---|
| Full suite (`uv run --frozen python -m pytest -q`) | **1 failed, 415 passed, 29 skipped, 16 xfailed**. The failure is the same unpassable reviewer AL5 test. |
| New `tests/integration/test_recorded_results.py` | **PASS** 13 |
| Confirmatory lane tests (updated shape plus the new reservation test) | **PASS** 21 |
| Dialogue tests (Ref-model tests replaced by deterministic-Ref and Heater-guard tests) | **PASS** |
| Reviewer agent-loop suite with my guard | **30 passed, 1 failed (AL5)**, unchanged |
| ruff | **PASS** |
| Live run, 6 turns | **PASS**: verdicts equal the committed entries, and the committed ledger head is unchanged after the run |

**Suite time.** It took 8.4 minutes, against 2–2.5 minutes earlier today. The slow tests are
the permutation-heavy `test_agent_loop.py` tests (149 s and 87 s), whose code this step does
not touch (`git diff` of loop, attacks, roles and views is empty). No process of mine was
left running. Other applications on the machine were using a lot of CPU, so this looks
environmental, but I have not confirmed that.

**Test change worth flagging.** The endpoint test's client timeout went from 10 s to 60 s.
A turn on the simulated test league takes about 12 s here, all of it the permutation attacks.
The test checks the contract, not speed.

## Open items

- Returning or streaming the Ref text before Heater's would cut perceived latency by about 3 s.
- The HH-K2 registry statement ("Same as HH-K3 with streak length 2") reads poorly in the Ref
  text. Fixing it needs a registry version bump.
- Experience can now build its Heater page against `docs/DIALOGUE_API.md`.
- The AL5 reviewer test still needs replacing.
