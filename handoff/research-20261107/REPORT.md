# What actually ran: HeatCheck-Research, 7 Nov 2026

Everything below was executed in a Linux workspace (2 CPUs, Python 3.13, numpy 2.5.3, pandas 3.0.5, scipy 1.18.1, scikit-learn 1.9.1). The raw output of each step is in `evidence/`. Nothing here is a projection.

## Ran

| # | Step | Command | Result |
|---|---|---|---|
| 1 | Pull upstream data | `git clone` shufinskiy/nba_data @ `46488f0f` + 3 archives | SHA-256 recorded in `raw/repo/SHA256SUMS` |
| 2 | Build canonical 2023–24 dataset | `scripts/build_dataset.py` | 1,230 games, 674,937 events, 218,693 FGAs, 0 exclusions, 0 duplicate IDs |
| 3 | Reconcile vs stats.nba.com | (inside step 2) | home team + final score match 1,230/1,230 |
| 4 | Replay determinism | build twice, compare hashes | 7/7 logical table hashes identical |
| 5 | Test suite | `python -m pytest -v` | **40 passed** (`evidence/test_run.txt`) |
| 6 | Game prediction, development | `game_prediction.py dev` | C1 worse than Elo on tune (−0.0047 nats) and calibration (−0.0009) |
| 7 | Freeze plan | `game_prediction.py freeze` | plan hash `a8d81292…12cf8` |
| 8 | Game prediction, final (once, via custodian) | `game_prediction.py final` | Elo vs base rate **SURVIVED_PROTOCOL** (+0.064 nats, CI [0.011, 0.128]). Rest/back-to-back vs Elo **INSUFFICIENT_EVIDENCE** (+0.020, CI [−0.004, 0.044]) |
| 9 | Custodian probes | retry + 2 bypass attempts | retry → same receipt and same result. Renamed family and edited code → both refused |
| 10 | Hot hand, dev games only | `shot_association.py nba` | 48.3% after 3 makes vs 47.8% after 3 misses. The null centres at +1.9pp, so p = 0.996, **not rejected** |
| 11 | Planted-truth harness | `shot_association.py harness` | 900 simulated leagues. Power 87% (strong), 31% (weak). Form-drift confounder triggers the test 38% of the time |
| 12 | Null calibration | 1,000 null leagues | false-positive rate 4.3% at α=0.05 (valid) |
| 13 | Clean-room check of this zip | unzip into empty dir → `setup_data.sh` → pytest → `final` | archive checksums OK. Rebuilt hashes match the original 7/7. 40 passed. Final replay returned the same receipt (retry) and identical decisions |

The 40 tests cover:
- the Beta(10,4) posterior moments, checked against scipy
- the log-loss and Brier arithmetic fixtures
- the exact Miller–Sanjurjo value 17/42
- p-values staying at or below nominal under the null
- the Holm correction
- block-bootstrap edge cases
- Kalshi derived asks, cents vs dollars, missing or crossed books, and stale or future quotes
- six contract-mismatch cases
- the custodian's persistence, retry and concurrency behaviour
- future-perturbation invariance on real games, with a deliberately leaky feature that fails, as it should

## Did not run

- BALLDONTLIE cross-check (no API key)
- interrupt-and-resume of paginated API ingestion
- upstream revision handling
- clutch, specification-curve, influence and time-replication attacks
- support-score calibration (G07)
- OS-level isolation of the truth and final data (logical only until Max wraps it)
- any live or recorded Kalshi/Polymarket data
- the final-split shot test
- independent review by Max (all gates are "evidence submitted", not passed)

## Caveats

- **Pseudo-out-of-sample:** 2023–24 outcomes are public, and LLMs may have memorised them.
- **Single season:** the final set is 300 games over 39 days, which is exactly the pre-registered minimum of 5 seven-day blocks.
- **Ledger:** `evidence/custodian_ledger.jsonl` is the live exposure ledger. Keep it, or the final 300 games are no longer protected.

## Reproduce

```
bash scripts/setup_data.sh   # checksum-verify archives, extract, build  (~1 min)
python -m pytest -v          # 40 tests
```
Then run the commands listed in `EVIDENCE.md` §8. The bundled upstream archives are for internal use only. Upstream redistribution rights are not established (DECISIONS D9).
