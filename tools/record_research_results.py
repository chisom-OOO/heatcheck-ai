"""Record Research's receipted final results in an evidence ledger (no recomputation).

    uv run --frozen python tools/record_research_results.py <ledger.jsonl> gp
        Research's 2023-24 GAME_PREDICTION final (receipt 3e238d2d): H1 -> GP-REST,
        H2 -> GP-ELO.

The confirmatory family's final is recorded through the same recorder by
ConfirmatoryLane (heatcheck/agents/confirmatory.py) once it has run.

Verifies before writing: the plan and amendment self-hashes, the custodian reserve and spend
lines for the receipt (with the plan hash), and that the reviewer-verified amended replay has
identical decisions. Prints the written (or already present) entries. Idempotent.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from heatcheck.agents.recorded import game_prediction_source, record  # noqa: E402
from heatcheck.ledger.evidence import EvidenceLedger  # noqa: E402


def main(argv: list[str]) -> int:
    ledger = EvidenceLedger(Path(argv[0]))
    if argv[1:] != ["gp"]:
        raise SystemExit("usage: record_research_results.py <ledger.jsonl> gp")
    entries = record(game_prediction_source(), ledger)
    for cid, e in entries.items():
        i = e["identity"]
        print(json.dumps({"claim_id": cid, "evidence_id": e["evidence_id"], "decision": i["decision"],
                          "reason": i["reason"], "receipt": i["custodian"]["receipt_id"],
                          "files": i["files"], "custodian_lines": i["custodian"]["ledger_lines"]}))
    print(json.dumps({"ledger": str(argv[0]), "entries": len(ledger.all()), "head": ledger.head()}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
