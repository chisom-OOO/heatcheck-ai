"""Frost (adviser's test; last assertion tightened by Max to use number_violations, 8 Nov 2026)."""
from heatcheck.agents import frost
from heatcheck.agents.dialogue import number_violations, ref_facts
from heatcheck.ledger.evidence import EvidenceLedger


def test_every_challenge_is_anchored_and_chips_use_record_numbers_only():
    led = EvidenceLedger.open_readonly("evidence/evidence.jsonl")
    for entry in led.all():
        facts = ref_facts(entry)
        chal = frost.select(facts)
        assert len(chal) <= 3
        kinds = [c.kind for c in chal]
        # Adviser's line was `len(set(kinds)) == min(len(kinds), 3) or len(candidates) < 3`, which
        # fails whenever a record has 3+ candidates in only 2 kinds (CONF-HH, CONF-MOM: the user's own
        # sample). This is select()'s documented rule: at most one per kind while kinds remain.
        assert len(set(kinds)) == min(len(kinds), len({c.kind for c in frost.candidates(facts)}))
        for c in chal:
            assert c.source                      # anchored
            assert number_violations(c.chip, facts) == [], (facts["claim_id"], c.check, c.chip)


def test_selection_and_anchoring_hold_for_every_entry():
    """The parts of the adviser's test that pass today, kept as a hard check."""
    for entry in EvidenceLedger.open_readonly("evidence/evidence.jsonl").all():
        facts = ref_facts(entry)
        chal = frost.select(facts)
        assert len(chal) <= 3 and all(c.source for c in chal)
        kinds = [c.kind for c in chal]
        available = {c.kind for c in frost.candidates(facts)}
        assert len(set(kinds)) == min(len(kinds), len(available))   # one per kind where possible


def test_payload_shape():
    facts = ref_facts(EvidenceLedger.open_readonly("evidence/evidence.jsonl").all()[0])
    chal = frost.select(facts)
    out = frost.to_payload(chal, {chal[0].check: "Rephrased?"})
    assert all(set(o) == {"check", "question", "chip", "source"} for o in out)
    assert out[0]["question"] == "Rephrased?" and out[0]["chip"] == chal[0].chip
