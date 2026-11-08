# Evidence ledger (Max)

`evidence.jsonl` is Max's committed, hash-chained evidence ledger (`heatcheck/ledger/evidence.py`).
Every read verifies each entry's `evidence_id`, `entry_hash` and the chain. It is append-only.

| Lines | What | How it got here |
|---|---|---|
| 1-3 | Agent-loop results on real game `nba:0022300061`: HH-K3, HH-K2, GP-REST (BLOCKED: no game-season view in the loop) | Byte-identical copy of `reports/max/logs/2026-11-07-al-fixes/evidence_real_game_v2.jsonl` |
| 4-5 | Research's recorded 2023-24 GAME_PREDICTION final, receipt `3e238d2d`: GP-REST (H1) INSUFFICIENT_EVIDENCE and GP-ELO (H2) SURVIVED_PROTOCOL | `uv run --frozen python tools/record_research_results.py evidence/evidence.jsonl gp` |

Recorded entries copy Research's decisions verbatim and bind the result, plan, amendment and
replay files and the exact custodian-ledger lines by sha256 (`heatcheck/agents/recorded.py`).
Nothing is recomputed. When both exist for a claim, the dialogue answers from the recorded
final (line 4 for GP-REST), not from the loop's BLOCKED entry (line 3).

The confirmatory family's final will be recorded the same way by `ConfirmatoryLane` once it
has run, on the reviewer's Linux container, with the user as authoriser.

Chain head after line 5: `8a356654353b75eb8e7257409ec263e1366b3c5865184cec72356593a317451d`.
