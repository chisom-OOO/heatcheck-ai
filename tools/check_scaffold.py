"""Validate preparation contracts; never a research/application acceptance test."""
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
assert (root / "AGENTS.md").read_bytes() == (root / "CLAUDE.md").read_bytes()
protocol = json.loads((root / "contracts/Shared_Protocol.json").read_text())
assert protocol["protocol_version"] == "heatcheck-nba/1"
assert set(protocol["claim_channels"]) == {
    "SHOT_ASSOCIATION", "GAME_PREDICTION", "MARKET_COMPARISON"
}
assert "ScanEvidence" not in protocol["required_envelopes"]
assert "paper_margin" not in protocol["numeric_semantics"]
gates = json.loads((root / "ACCEPTANCE.json").read_text())["gates"]
assert len({gate["id"] for gate in gates}) == len(gates) == 18
assert all(gate["status"] == "NOT_RUN" for gate in gates)
assert "exit 1" in (root / ".githooks/pre-push").read_text()
print("PASS: preparation contracts/guard only; application/research gates NOT_RUN")
