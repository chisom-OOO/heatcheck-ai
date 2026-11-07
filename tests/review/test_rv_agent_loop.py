"""Reviewer probes of Max's agent loop v1 (heatcheck/agents, heatcheck/ledger; 0013e53 onward).

A failing test is a reviewer FINDING (expected vs actual in the message). The Ref number-guard
section is staged ahead of the guard: set HEATCHECK_REVIEW_REF_GUARD=module:function, where the
function takes (text, evidence_entry) and returns True when the text is allowed to be spoken.
"""

from __future__ import annotations

import copy
import json
import multiprocessing as mp
import os
from pathlib import Path

import numpy as np
import pytest

from heatcheck.agents.loop import run_once
from heatcheck.agents.registry import ATTACKS, CLAIMS
from heatcheck.agents.roles import DeterministicChallenger, ProposalRefused, decide, parse_proposal
from heatcheck.agents.views import ShotView
from heatcheck.contracts.records import canonical_bytes, sha256_hex
from heatcheck.ledger.evidence import EvidenceLedger, LedgerError, evidence_id
from tests.review.review_support import load_callable

ROOT = Path(__file__).resolve().parents[2]
COMMITTED = ROOT / "reports" / "max" / "logs" / "2026-11-07-loop" / "evidence_real_game.jsonl"


def tiny_view(seed: int = 3, n_groups: int = 40, per: int = 30) -> ShotView:
    rng = np.random.default_rng(seed)
    group = np.repeat(np.arange(n_groups), per).astype(np.int64)
    value = rng.choice([2, 3], size=len(group)).astype(np.int64)
    made = (rng.random(len(group)) < 0.47).astype(np.int8)
    strata = group * 2 + (value == 3)
    return ShotView(made, group, strata, value, "SYNTHETIC", "reviewer-tiny-view", 0)


def forge(line: dict, **identity_changes) -> dict:
    """What anyone with write access can do: edit the identity, recompute both hashes."""
    e = copy.deepcopy(line)
    e["identity"].update(identity_changes)
    e["evidence_id"] = evidence_id(e["identity"])
    e["entry_hash"] = sha256_hex(canonical_bytes(e["identity"]) + e["created_at_utc"].encode())
    return e


def write_lines(path: Path, entries: list[dict]) -> None:
    path.write_text("".join(json.dumps(e, sort_keys=True, separators=(",", ":")) + "\n"
                            for e in entries), "utf-8")


# =========================================================================== controls


def test_control_committed_ledger_verifies_and_naive_tamper_detected(tmp_path):
    entries = EvidenceLedger(COMMITTED).all()
    assert [e["identity"]["decision"] for e in entries] == \
        ["INSUFFICIENT_EVIDENCE", "NOT_SUPPORTED", "BLOCKED"]
    bad = copy.deepcopy(entries)
    bad[1]["identity"]["decision"] = "SURVIVED_PROTOCOL"  # edit without rehashing
    write_lines(tmp_path / "l.jsonl", bad)
    with pytest.raises(LedgerError):
        EvidenceLedger(tmp_path / "l.jsonl").all()


# =========================================================================== ledger integrity


def test_rv_al1_forged_decision_with_recomputed_hashes_detected(tmp_path):
    """Max report: 'tampering is detected on read'. Both hashes are unkeyed content hashes, so
    a forger recomputes them. Expected: detection (hash chain / signed or externally anchored
    head). Actual is reported in the message."""
    entries = EvidenceLedger(COMMITTED).all()
    entries[1] = forge(entries[1], decision="SURVIVED_PROTOCOL",
                       reason="p=0.0010 <= 0.05, effect +0.0740 >= 0.01")
    write_lines(tmp_path / "l.jsonl", entries)
    try:
        got = EvidenceLedger(tmp_path / "l.jsonl").all()
    except LedgerError:
        return
    pytest.fail(f"EXPECTED forged line detected; ACTUAL accepted, HH-K2 decision now "
                f"{got[1]['identity']['decision']}")


def test_rv_al2_deleted_line_detected(tmp_path):
    entries = EvidenceLedger(COMMITTED).all()
    write_lines(tmp_path / "l.jsonl", [entries[1], entries[2]])  # HH-K3 result removed
    try:
        got = EvidenceLedger(tmp_path / "l.jsonl").all()
    except LedgerError:
        return
    pytest.fail(f"EXPECTED deletion detected; ACTUAL {len(got)} entries accepted, HH-K3 gone, "
                "and the loop would re-run it as a fresh evaluation")


def test_rv_al3_concurrent_put_of_same_identity_is_one_line(tmp_path):
    path = tmp_path / "l.jsonl"
    ctx = mp.get_context("spawn")
    ident = EvidenceLedger(COMMITTED).all()[0]["identity"]
    with ctx.Pool(6) as pool:
        pool.starmap(_put, [(str(path), ident)] * 12)
    lines = [ln for ln in path.read_text().splitlines() if ln.strip()]
    assert len(lines) == 1, f"EXPECTED 1 line (retry identity); ACTUAL {len(lines)} lines"


def _put(path: str, ident: dict) -> None:
    EvidenceLedger(Path(path)).put(ident)


# =========================================================================== role boundaries


def test_rv_al4_challenger_cannot_drop_applicable_optional_attacks():
    """The Referee only requires mandatory attacks. If the shot-value confound check would
    flag, a Challenger that simply does not select it turns INSUFFICIENT into SURVIVED."""
    claim = CLAIMS["HH-K3"]
    ok = {"status": "EXECUTED", "reason": "ok", "details": {"sufficient": True}}
    base = {"A-INPUT-INTEGRITY": ok, "A-SAMPLE-SIZE": ok,
            "A-PERMUTATION-NULL": {**ok, "p_value": 0.001, "effect_estimate": 0.08}}
    with_sv = {**base, "A-SHOT-VALUE-SELECTION": {**ok, "reason": "gap 0.25",
                                                  "details": {"flagged": True}}}
    assert decide(claim, with_sv, True)[0] == "INSUFFICIENT_EVIDENCE"
    got = decide(claim, base, True)[0]
    assert got != "SURVIVED_PROTOCOL", (
        "EXPECTED the Referee to require every optional attack whose prerequisites hold "
        f"(BLOCKED or INSUFFICIENT); ACTUAL {got} when the Challenger omits the confound check")


def test_rv_al5_loop_accepts_minimal_challenger(tmp_path):
    """RV-AL5, as resolved by RV-AL4 (Referee-enforced attack set): a Challenger that selects only the
    mandatory attacks cannot shrink what is run. The Referee's required set (mandatory + applicable
    optional) is run anyway, the omission is recorded in the evidence identity, and the decision equals
    the full Challenger's.

    Fixed 2026-11-07 by Research, which did not write the agent loop. The earlier version ended in an
    unconditional pytest.fail(...), so it failed whether run_once refused or accepted and could never pass.
    """
    class MandatoryOnly(DeterministicChallenger):
        identity = {**DeterministicChallenger.identity, "version": "rv-mandatory-only"}

        def select(self, claim, view):
            return sorted(a.attack_id for a in ATTACKS.values() if a.mandatory)

    view = tiny_view()
    full = run_once(view, EvidenceLedger(tmp_path / "a.jsonl"))
    mini = run_once(view, EvidenceLedger(tmp_path / "b.jsonl"), challenger=MandatoryOnly())
    fc, mc = full["identity"]["challenger"], mini["identity"]["challenger"]
    have_optional = set(fc["selected_attacks"]) - set(mc["selected_attacks"])
    assert have_optional, "control: the full Challenger should select optional attacks here"
    assert set(mc.get("omitted_required_attacks") or []) == have_optional, (
        f"EXPECTED the omitted applicable attacks {sorted(have_optional)} recorded as omitted; "
        f"ACTUAL {mc.get('omitted_required_attacks')}")
    assert set(mc.get("referee_required_attacks") or []) >= have_optional and \
        set(mc.get("attacks_run") or []) >= set(mc.get("referee_required_attacks") or have_optional), (
        f"EXPECTED every Referee-required attack to run despite the minimal Challenger; ACTUAL attacks_run="
        f"{mc.get('attacks_run')}, required={mc.get('referee_required_attacks')}")
    assert set(mc["attacks_run"]) == set(fc["attacks_run"]), "the minimal Challenger changed what was run"
    assert mini["identity"]["decision"] == full["identity"]["decision"], (
        f"EXPECTED the same decision as the full Challenger ({full['identity']['decision']}); "
        f"ACTUAL {mini['identity']['decision']}")


@pytest.mark.parametrize("raw", [
    '{"claim_id": "HH-K3", "rationale": "x", "params": {"alpha": 0.5}}',
    '{"claim_id": "hh-k3", "rationale": "x"}',
    '{"claim_id": "HH-K3 ", "rationale": "x"}',
    '{"claim_id": ["HH-K3"], "rationale": "x"}',
    '{"claim_id": "HH-K3", "claim_id": "GP-REST", "rationale": "x"}',
])
def test_rv_al6_jone_cannot_smuggle_ids_or_params(raw):
    with pytest.raises(ProposalRefused):
        parse_proposal(raw)


def test_rv_al7_rationale_is_free_text_in_evidence(tmp_path):
    """Jone's rationale (model text once wired) is stored verbatim in the evidence identity.
    Recorded here so the number guard below can be checked against it."""
    class Chatty:
        identity = {"kind": "RV", "role": "jone", "model": None, "prompt": None, "version": "1"}

        def propose(self, cat, done):
            return json.dumps({"claim_id": "HH-K3",
                               "rationale": "Shooters hit 62.5% after three makes, p=0.003."})
    e = run_once(tiny_view(), EvidenceLedger(tmp_path / "l.jsonl"), jone=Chatty())
    assert "62.5%" in e["identity"]["proposer"]["rationale"]


# =========================================================================== Ref number guard


def _guard():
    spec = os.environ.get("HEATCHECK_REVIEW_REF_GUARD")
    if not spec:
        pytest.skip("NOT_RUN: Ref number guard not landed; set HEATCHECK_REVIEW_REF_GUARD")
    return load_callable(spec)


def _hh_k3() -> dict:
    return EvidenceLedger(COMMITTED).all()[0]  # n=14 vs 18, p=0.061, INSUFFICIENT_EVIDENCE


ALLOWED = [
    "Not enough evidence: 14 attempts after three makes and 18 after three misses; 30 needed.",
    "The permutation p-value was 0.061, which is reported but not decisive.",
]
# Each should be refused: the number is not in the evidence record, or only appears in a
# non-evidence field (Jone's rationale, an id, a hash), or is a transformation of one.
SMUGGLED = [
    ("invented", "Shooters made 62.5% after three makes."),
    ("sum", "In total 32 streak attempts were examined."),           # 14 + 18
    ("percent_of_p", "There is a 6.1% chance this is luck."),        # p re-expressed
    ("complement", "We are 93.9% confident the hot hand is real."),  # 1 - p
    ("sign_flip", "The bias-corrected effect was -0.074."),          # K2's +0.074, wrong record
    ("other_record", "The p-value was 0.239."),                      # belongs to HH-K2
    ("hash_digits", "Run 754 confirms it."),                         # digits inside 2c754d04…
    ("claim_id_digit", "Players get 3 times hotter."),               # from 'HH-K3' / k=3
    ("spelled", "Fourteen of them went in."),
    ("sci", "p was 6.1e-2."),
    ("leading_dot", "p was .061 so it survived."),
    ("rounded_up", "p was 0.07."),
    ("thousands", "Across 1,230 games the effect held."),           # season count, not here
    ("unicode_digits", "p was ٠٫٠٦١."),
    ("fullwidth", "n was １４ after makes and the effect is ９９%."),
    ("fraction", "Half of the shots after makes went in."),
]


@pytest.mark.parametrize("text", ALLOWED)
def test_rv_ref1_guard_allows_numbers_in_record(text):
    assert _guard()(text, _hh_k3()), f"EXPECTED allowed: {text!r}"


@pytest.mark.parametrize("name, text", SMUGGLED, ids=[n for n, _ in SMUGGLED])
def test_rv_ref2_guard_refuses_numbers_not_in_record(name, text):
    assert not _guard()(text, _hh_k3()), f"EXPECTED refused ({name}); ACTUAL allowed: {text!r}"


def test_rv_ref3_guard_ignores_numbers_only_in_jone_rationale(tmp_path):
    """A model-written rationale must not launder a number into 'the evidence record'."""
    entry = copy.deepcopy(_hh_k3())
    entry["identity"]["proposer"]["rationale"] = "Expect about 62.5% after three makes."
    assert not _guard()("Shooters made 62.5% after three makes.", entry), \
        "EXPECTED refused: 62.5 appears only in Jone's rationale, not in any attack result"
