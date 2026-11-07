# Contracts: specification only

Canonical protocol heatcheck-nba/1 is in contracts/Shared_Protocol.json.
Channels: SHOT_ASSOCIATION, GAME_PREDICTION, MARKET_COMPARISON.
Referee verdicts: SURVIVED_PROTOCOL, NOT_SUPPORTED, INSUFFICIENT_EVIDENCE,
DATA_INVALID, BLOCKED. Runtime and coding-agent roles are different.

Data records: heatcheck-records/1 (docs/DATA_FORMAT.md) has a strict stdlib validator
in heatcheck/contracts/records.py and bundle.py; envelopes for ClaimPlan/AttackResult/
EvaluationRun are not yet implemented. No registered HTTP routes exist. Future authority binds
exact revision/owner/context/data/model/config; edits invalidate confirmation,
retries match full identity and historical evidence remains immutable.
Final-data epochs bind underlying record IDs and cannot be reopened by renaming
families/files. Full exposure/assumption checks remain to be implemented.

NBA quote comparisons are read-only descriptive context. No scanner, portfolio
payoff optimiser, trading endpoint, profit claim or funded execution.
