# Confirmatory run: sealed 2024-25 season (CONF-HA, CONF-MOM, CONF-HH)

Operator: Claude (adviser session), standing in for the independent reviewer whose machine failed.
Authorised by: Leo Nichols, in writing, 2026-11-07 22:27 Europe/London.
Code: max/integrate-r001-e001 @ 741b4de (working tree clean). Linux, Python 3.13.18,
numpy 2.5.3, pandas 3.0.5, scipy 1.18.1, scikit-learn 1.9.1.

## Before the run
1. Independent rebuild of 2024-25 from the pinned archives with Research's script
   (`reports/research/logs/rebuild/rebuild_2024-25.sh`, commit e7e8857), on a machine that
   did not produce the seal: SEAL MATCH 6/6 tables; Research's 2 real-data seal tests passed.
   Log: `logs/2026-11-07-confirmatory/independent_rebuild_2024-25.log`. The quarantine table
   (game 0022400072) reproduced by rule.
2. Max's dry run (`heatcheck.agents.confirmatory.dry_run`) against that build: READY,
   11/11 checks PASS, state UNRUN (0 reservations on EPOCH-CONF-2024-25-001).
3. No outcome statistic on 2024-25 was computed or opened before the final step.

## The run (once)
Command, start/end times, exit code and before/after hashes: `logs/2026-11-07-confirmatory/run_record.txt`.
Full stdout (the result JSON): `final_stdout.txt`. stderr: empty.
- Started 22:28:06Z, finished 22:30:38Z, exit 0.
- Receipt 5cbb3222-181d-439d-9202-02a8d8030e4e, receipt_was_retry: false.
- custodian_ledger.jsonl: 51dbc04a… before, b9d6a0b2… after (reserve + spend appended).
- final_result.json sha256 d16245990d09663917743122d5edb8e032e570c630d979454ecb4c718f626dd3.

## After the run
- Max's `verify_final_result`: PASS (family, plans, code, data hashes, epoch, receipt reserved and spent).
- Dry run state now FINAL_DONE.

## Results (copied from final_result.json, Holm across the three)
| Hypothesis | Sample | Estimate | 95% CI | p one-sided | Holm p | Verdict |
|---|---|---|---|---|---|---|
| CONF-HA home advantage | 1,224 games (5 neutral, 1 quarantined excluded) | home-win rate 0.5449 (+0.0449 over 0.5) | [+0.0160, +0.0752] | 0.0018 | 0.0054 | SURVIVED_PROTOCOL |
| CONF-MOM one-shot momentum | 219,274 FGA | P(make after make) 0.4667 vs after miss 0.4709; T -0.0043 vs null mean +0.0067 | n/a | 1.0 | 1.0 | INSUFFICIENT_EVIDENCE |
| CONF-HH hot hand (3) | 219,274 FGA | after 3 makes 0.47265 vs after 3 misses 0.47266; T -0.00001 vs null mean +0.0175 | n/a | 1.0 | 1.0 | INSUFFICIENT_EVIDENCE |

CONF-MOM and CONF-HH are INSUFFICIENT_EVIDENCE, not NOT_SUPPORTED, because no equivalence
test was pre-registered; the frozen rule cannot conclude "no effect", only "not shown".
Caveats recorded in the result: 2024-25 outcomes are public (pseudo-out-of-sample); shot-test
survival would be association, not causation; block-bootstrap p is approximate.

## Not done here
- Recording the three results into Max's evidence ledger: Max's ConfirmatoryLane detects
  FINAL_DONE and records without re-running.
- The confirmatory script rewrites final_result.json if run again: do not run final again.
