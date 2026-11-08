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
assert all(gate["status"] in {"NOT_RUN", "PASS", "PARTIAL", "FAIL"} for gate in gates)
# A gate may leave NOT_RUN only with a named non-author reviewer and evidence (CLAUDE.md rule 7).
for gate in gates:
    if gate["status"] != "NOT_RUN":
        assert gate.get("reviewer"), f"{gate['id']} marked without a reviewer"
        assert gate.get("evidence"), f"{gate['id']} marked without evidence"
assert "exit 1" in (root / ".githooks/pre-push").read_text()
marked = sum(gate["status"] != "NOT_RUN" for gate in gates)
print(f"PASS: preparation contracts; {marked} gate(s) marked, each with reviewer and evidence")
