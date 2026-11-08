# Research status: keyword-proposed idea family "Does rest matter?" run (fallback)

| | |
|---|---|
| Branch | `research/idea-family` |
| Request | `evidence/idea-family/request_does_rest_matter_keyword.json`: byte-for-byte copy of Max's `data/max/idea_requests/does_rest_matter_dev.json` at `e1c2dc3` (sha256 `981af07b…9abf8`) |
| Proposer | **KEYWORD RULES**: Heater's proposer, deterministic keyword path, from the fan message "Does rest matter?". **Not model-proposed.** Recorded in `PROVENANCE_does_rest_matter_keyword.json`. |
| Outputs | `evidence/idea-family/does_rest_matter_keyword/{registration,results}.json` (write-once; registration `c54df263…`) |
| Log | `logs/idea-family/does_rest_matter_keyword.log` (exit 0, about 22 s) |
| Data | 2023-24 development games only: 926 non-neutral games. Spent final games and the sealed 2024-25 season were not read. |

## Results (Holm across the 2 ideas)

| Idea | Group / rest | Home-win rate (group / rest) | T | p | Holm p | Verdict |
|---|---|---|---|---|---|---|
| home team more rested, greater | 222 / 704 | 0.5901 / 0.5412 | +0.0489 | 0.107 | 0.107 | NOT_A_CANDIDATE |
| away team more rested, less | 196 / 730 | 0.4898 / 0.5699 | −0.0801 | 0.030 | 0.060 | NOT_A_CANDIDATE |

**Reading it:**
- The direction fits "rest helps": when the away team is more rested, the home team wins 8 points less often.
- But after correcting for the two ideas, neither passes 0.05. This matches the registered 2023-24 final test
  (GP-REST: INSUFFICIENT_EVIDENCE).
- It is exploratory and on development data, so it cannot overturn that registered verdict.

## Pending

The model-proposed request from Max will be run the same way when it arrives, and labelled model-proposed.
