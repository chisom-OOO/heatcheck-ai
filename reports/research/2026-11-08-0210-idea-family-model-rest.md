# Research status: model-proposed idea family "Does rest matter?" (Heater, muse-spark-1.3)

| | |
|---|---|
| Branch | `research/idea-family` |
| Request | `evidence/idea-family/request_does_rest_matter_model.json`: byte-for-byte copy of Max's `does_rest_matter_heater_dev.json` at `c15abf7` (sha256 `4a7e42a3…af2e`) |
| Model output | `model_output_does_rest_matter.json`: byte-for-byte copy (sha256 `bea64d24…58bd`). Research checked that its `model_output_text` parses to exactly the request's 5 ideas, with `source: LLM` and the keyword fallback unused. |
| Proposer | **MODEL**: Heater's proposer, one Meta `muse-spark-1.3` call constrained to the grammar's JSON schema (`PROVENANCE_does_rest_matter_model.json`) |
| Outputs | `evidence/idea-family/does_rest_matter_model/{registration,results}.json` (registration `2ca00c88…`) |
| Log | `logs/idea-family/does_rest_matter_model.log` (exit 0) |
| Data | 2023-24 development games only (926 non-neutral) |

## Results (Holm across the 5 ideas, all two-sided)

| Idea | Group / rest | Home-win rate (group / rest) | T | p | Holm p | Verdict |
|---|---|---|---|---|---|---|
| home team on a back-to-back | 154 / 772 | 0.5000 / 0.5635 | −0.0635 | 0.190 | 0.632 | NOT_A_CANDIDATE |
| away team on a back-to-back | 169 / 757 | 0.5917 / 0.5443 | +0.0475 | 0.232 | 0.632 | NOT_A_CANDIDATE |
| home team more rested | 222 / 704 | 0.5901 / 0.5412 | +0.0489 | 0.233 | 0.632 | NOT_A_CANDIDATE |
| away team more rested | 196 / 730 | 0.4898 / 0.5699 | −0.0801 | 0.043 | 0.215 | NOT_A_CANDIDATE |
| home team with 0 rest days | 154 / 772 | 0.5000 / 0.5635 | −0.0635 | 0.158 | 0.632 | NOT_A_CANDIDATE |

**Reading it:**
- Every direction fits "rest helps", but no idea survives Holm across the 5.
- Compared with the keyword family's 2 ideas, the model asked more questions, so each must clear a higher bar.
  The away-more-rested idea is 0.043 raw here (two-sided) and 0.030 there (one-sided).
- The result is consistent with the registered GP-REST INSUFFICIENT_EVIDENCE. It is exploratory, on
  development data.

## Observation: a semantic duplicate

- Ideas 1 and 5 define the same game group: a back-to-back is 0 rest days. They have identical counts and T.
- Their p-values differ (0.190 vs 0.158) only by Monte Carlo noise, because each idea's seed comes from its
  hash.
- The grammar validator refuses exact duplicates but not equivalent ones. The duplicate makes Holm stricter,
  never looser.
- Suggested fix: refuse `home_rest_days "0"` / `away_rest_days "0"` alongside the matching back-to-back idea,
  or map one to the other. This changes the grammar, so it is Max's and the user's call.
