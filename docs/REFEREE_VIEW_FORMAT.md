# Referee view format: `heatcheck-referee-view/1`

Owner: Max. Agreed by the user on 2026-11-07. Experience reviews it after 20:00 UTC on
2026-11-07. Status: **v1, pending Experience review**.

## Purpose and boundary

- The evidence ledger (`heatcheck/ledger/evidence.py`) stores one hashed `identity` per run.
  The `evidence_id` is the sha256 of that identity. Renaming or reshaping ledger fields would
  change every id, so the ledger is **never** reshaped for display.
- The UI instead reads a **read-only projection** of one verified ledger entry, produced by
  `heatcheck.ledger.referee_view.referee_view(entry)`.
- The projection rules:
  - It copies values. It never recomputes or rounds them.
  - It is not hashed, and it is not evidence by itself.
  - `derived_from.evidence_id` and `derived_from.entry_hash` point back to the ledger entry,
    which is the evidence.
- `POST /api/dialogue` returns the projection as `referee_view` when a test ran.
- `tools/build_referee_view_fixture.py <ledger> <evidence_id> <out>` writes one to a file.

Sample, projected from a real ledger entry (the live turn of 2026-11-07T17:27Z, game
`nba:0022300061`): `apps/web/fixtures/referee/referee_view.sample.json`.

## Shape

```text
{
  format:            "heatcheck-referee-view/1"
  derived_from:      { evidence_id: sha256, entry_hash: sha256, created_at_utc: Z timestamp }
  protocol_version:  "heatcheck-nba/1"
  registry_version:  "heatcheck-registry/1"
  channel:           SHOT_ASSOCIATION | GAME_PREDICTION | ...
  data_mode:         SYNTHETIC | REAL_NBA_RETROSPECTIVE | RECORDED_MARKET | LIVE_MARKET
  claim: {
    claim_id, version          registered claim id and its registry version
    statement, estimand        from the registered plan
    plan_hash                  canonical plan sha256
    revision: null             registered claims have no user revision (see below)
    params                     plan parameters as registered
  }
  attacks_run: [ {
    test_id                    "<attack id>@<version>", e.g. "A-PERMUTATION-NULL@1"
    status                     EXECUTED | FAILED | UNSUPPORTED  (copied as recorded)
    statistic, effect_estimate, interval, p_value     number | [number, number] | null
    method                     null/method assumptions, as recorded
    reason                     text, as recorded
    evidence_hash              the attack envelope's sha256
  } ]
  verdict:  { decision: SURVIVED_PROTOCOL | NOT_SUPPORTED | INSUFFICIENT_EVIDENCE |
                        DATA_INVALID | BLOCKED,
              reason: text }
  evidence: [ { label: text, value: string | number | null, kind: hash|time|count|estimate|version } ]
  roles: {
    discoverer: { role, display_name ("Heater"), kind (LLM | DETERMINISTIC_STANDIN), model,
                  reasoning_effort, fallback_reason? }
    challenger: { role, kind, model, selected_attacks, fallback_reason? }
    referee:    { kind: DETERMINISTIC_CODE, rule }
  }
  limits: text
}
```

## Rules for readers

- **Attack status is not pass/fail.** It says whether the attack ran:
  - `EXECUTED`: it ran.
  - `FAILED`: the input-integrity check failed.
  - `UNSUPPORTED`: it could not be computed on this data.

  Only `verdict.decision` says whether the claim survived. Show the status as supplied; do
  not map it to PASSED.
- `null` means not reported or not applicable. Never show it as zero.
- `claim.revision` is `null` because these are registered claims. Free-text user claims
  with revisions are not implemented. Show "not applicable (registered claim, version N)".
- The verdict values are the five above, identical to `provisional-experience/0`.
- **Old provisional records.** `fromRecord()` still reads `provisional-experience/0`, and
  labels it as the old provisional format.

## Mapping from Experience's `provisional-experience/0`

| provisional-experience/0 | heatcheck-referee-view/1 |
|---|---|
| `format` | `format` (new value) |
| `data_mode` | `data_mode` |
| `claim.{claim_id, statement, plan_hash, revision}` | same names. `revision` is always null; `version` was added. |
| `attacks_run[].test_id` | same |
| `attacks_run[].outcome` (PASSED/FAILED/NOT_RUN/ERROR) | **`attacks_run[].status`** (EXECUTED/FAILED/UNSUPPORTED). The meaning differs, see above. |
| `attacks_run[].{statistic, p_value, method, reason}` | same names, plus `effect_estimate`, `interval`, `evidence_hash` |
| `verdict.{decision, reason}` | same |
| `evidence[]` `{label, value, kind}` | same |
| (none) | `derived_from`, `roles`, `limits`, `channel`, protocol and registry versions |
