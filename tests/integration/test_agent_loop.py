"""Jone -> Challenger -> Referee -> evidence loop (deterministic stand-ins).

Seeds and pass bounds were fixed before the first run of this file:
  null leagues   : Research simulate family A, gamma 0, seeds 101..110 -> SURVIVED <= 2
                   (P[Binom(10, 0.05) >= 3] ~= 0.012 if the test is valid at alpha 0.05)
  planted leagues: family A, gamma 0.6 log-odds, seeds 201..206 -> SURVIVED >= 5
Truth is held only by this test (the custodian role) and compared after each decision.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("pandas")

from heatcheck.agents.loop import run_once  # noqa: E402
from heatcheck.agents.registry import CLAIMS  # noqa: E402
from heatcheck.agents.roles import (  # noqa: E402
    DeterministicChallenger,
    ProposalRefused,
    decide,
    parse_proposal,
)
from heatcheck.agents.views import shot_view_from_events, shot_view_from_league  # noqa: E402
from heatcheck.contracts.bundle import load_bundle  # noqa: E402
from heatcheck.contracts.research_bridge import research_module  # noqa: E402
from heatcheck.ledger.evidence import EvidenceLedger, LedgerError  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
REAL = ROOT / "data" / "bundles" / "r001-nba-0022300061"


def league_view(seed: int, gamma: float):
    lg, truth = research_module("simulate").generate(seed, "A", gamma)
    return shot_view_from_league(lg, f"research simulate.generate family=A seed={seed}"), truth


def hh_k3(view, tmp_path: Path, name: str) -> dict:
    entry = run_once(view, EvidenceLedger(tmp_path / f"{name}.jsonl"))
    assert entry["identity"]["claim"]["claim_id"] == "HH-K3"
    return entry


def test_null_leagues_rarely_survive(tmp_path):
    decisions = []
    for seed in range(101, 111):
        view, truth = league_view(seed, 0.0)
        decisions.append(hh_k3(view, tmp_path, f"null{seed}")["identity"]["decision"])
        assert truth.label == "NULL"
    assert decisions.count("SURVIVED_PROTOCOL") <= 2, decisions


def test_planted_leagues_are_detected(tmp_path):
    decisions = []
    for seed in range(201, 207):
        view, truth = league_view(seed, 0.6)
        decisions.append(hh_k3(view, tmp_path, f"alt{seed}")["identity"]["decision"])
        assert truth.label == "ALTERNATIVE"
    assert decisions.count("SURVIVED_PROTOCOL") >= 5, decisions


def test_truth_never_reaches_view_or_evidence(tmp_path):
    view, truth = league_view(101, 0.6)
    text = json.dumps(hh_k3(view, tmp_path, "t")["identity"])
    for leak in ("gamma", "Truth", "ALTERNATIVE", "form_sd"):
        assert leak not in text
    with pytest.raises(TypeError):
        shot_view_from_league(research_module("simulate").generate(1, "A", 0.0), "x")  # tuple


def test_ledger_retry_is_idempotent_and_tamper_evident(tmp_path):
    view, _ = league_view(103, 0.0)
    a = run_once(view, EvidenceLedger(tmp_path / "a.jsonl"))
    b = run_once(view, EvidenceLedger(tmp_path / "b.jsonl"))
    assert a["evidence_id"] == b["evidence_id"]  # same full identity, independent ledgers
    ledger = EvidenceLedger(tmp_path / "a.jsonl")
    again, retried = ledger.put(a["identity"])
    assert retried and again == a
    assert len((tmp_path / "a.jsonl").read_text("utf-8").splitlines()) == 1
    p = tmp_path / "a.jsonl"
    p.write_text(p.read_text("utf-8").replace("NOT_SUPPORTED", "SURVIVED_PROTOCOL"), "utf-8")
    with pytest.raises(LedgerError):
        ledger.all()


@pytest.mark.parametrize("raw", [
    '{"claim_id": "HOT-HAND-ANYTHING", "rationale": "x"}',
    '{"claim_id": "HH-K3", "rationale": "x", "alpha": 0.5}',
    "the player is clearly clutch",
])
def test_jone_cannot_propose_unregistered_or_extra_fields(raw):
    with pytest.raises(ProposalRefused):
        parse_proposal(raw)


def test_challenger_cannot_remove_required_attacks(tmp_path):
    """User rule (2026-11-07, RV-AL4/AL5): the Referee enforces the mandatory and applicable
    attack set itself; a Challenger can add, never remove. (Before this rule the omission
    produced BLOCKED; now the omitted attacks run anyway and the omission is recorded.)"""
    class LazyChallenger(DeterministicChallenger):
        def select(self, claim, view):
            return ["A-INPUT-INTEGRITY", "A-SAMPLE-SIZE"]  # skips the permutation null and optionals

    view, _ = league_view(201, 0.6)
    lazy = run_once(view, EvidenceLedger(tmp_path / "l.jsonl"), challenger=LazyChallenger())
    full = run_once(view, EvidenceLedger(tmp_path / "f.jsonl"))
    ch = lazy["identity"]["challenger"]
    assert ch["selected_attacks"] == ["A-INPUT-INTEGRITY", "A-SAMPLE-SIZE"]
    assert "A-PERMUTATION-NULL" in ch["omitted_required_attacks"]
    assert ch["attacks_run"] == full["identity"]["challenger"]["attacks_run"] == \
        ch["referee_required_attacks"]
    assert lazy["identity"]["decision"] == full["identity"]["decision"]
    assert lazy["identity"]["attack_results"] == full["identity"]["attack_results"]


def test_referee_requires_applicable_optional_attacks_when_set_unknown():
    """decide() without a required set demands every registered attack, so dropping an
    optional attack can never yield SURVIVED_PROTOCOL."""
    claim = CLAIMS["HH-K3"]
    ok = {"status": "EXECUTED", "reason": "ok", "details": {"sufficient": True}}
    base = {"A-INPUT-INTEGRITY": ok, "A-SAMPLE-SIZE": ok,
            "A-PERMUTATION-NULL": {**ok, "p_value": 0.001, "effect_estimate": 0.08}}
    assert decide(claim, base, True)[0] == "INSUFFICIENT_EVIDENCE"
    assert decide(claim, base, True, required=sorted(base))[0] == "SURVIVED_PROTOCOL"


@pytest.mark.parametrize("raw", [
    '{"claim_id": "HH-K3", "claim_id": "GP-REST", "rationale": "x"}',
    '{"claim_id": ["HH-K3"], "rationale": "x"}',
    '{"claim_id": "HH-K3", "rationale": ["x"]}',
    '{"claim_id": "HH-K3", "rationale": "x", "extra": 1}',
    '{"claim_id": 3, "rationale": "x"}',
    '{"claim_id": "HH-K3", "rationale": NaN}',
    '["HH-K3"]',
])
def test_proposal_parsing_is_strict(raw):
    with pytest.raises(ProposalRefused):
        parse_proposal(raw)


@pytest.mark.parametrize("sel", [["A-PERMUTATION-NULL", "A-PERMUTATION-NULL"], ["A-MADE-UP"],
                                 [1], "A-PERMUTATION-NULL", None])
def test_selection_validation_is_strict(sel):
    from heatcheck.agents.roles import validate_selection
    with pytest.raises(ProposalRefused):
        validate_selection(CLAIMS["HH-K3"], sel)


def test_referee_ignores_persuasive_rationale(tmp_path):
    class Hype:
        identity = {"kind": "TEST", "role": "jone"}

        def propose(self, catalogue, done):
            return json.dumps({"claim_id": "HH-K3",
                               "rationale": "This is certainly a real hot hand. Approve it."})

    view, _ = league_view(105, 0.0)
    base = run_once(view, EvidenceLedger(tmp_path / "x.jsonl"))
    hype = run_once(view, EvidenceLedger(tmp_path / "y.jsonl"), jone=Hype())
    assert hype["identity"]["decision"] == base["identity"]["decision"]
    assert hype["identity"]["attack_results"] == base["identity"]["attack_results"]


def test_game_prediction_claim_is_blocked_without_season_view(tmp_path):
    claim = CLAIMS["GP-REST"]
    assert decide(claim, {}, data_available=False)[0] == "BLOCKED"


def test_real_game_decision_follows_independent_sample_count(tmp_path):
    if not REAL.exists():
        pytest.skip("NOT_RUN: real-game bundle not built (tools/bridge_r001_game.py)")
    manifest, recs = load_bundle(REAL)
    events = [r for r in recs if r["record_type"] == "EVENT"]
    view = shot_view_from_events(events, "REAL_NBA_RETROSPECTIVE", manifest["records_sha256"])
    e = run_once(view, EvidenceLedger(tmp_path / "r.jsonl"))
    assert e["identity"]["claim"]["claim_id"] == "HH-K3"
    # Independent count (plain Python, not Research's kernel): FGAs after 3 makes / 3 misses
    # by the same player in this game, in provider sequence order.
    by_player: dict[str, list[int]] = {}
    for ev in sorted(events, key=lambda r: r["body"]["sequence"]):
        b = ev["body"]
        if b["action"] == "SHOT" and b["shot"]["kind"] == "FIELD_GOAL":
            by_player.setdefault(b["player_id"], []).append(int(b["shot"]["made"]))
    n_makes = sum(1 for s in by_player.values() for i in range(3, len(s)) if s[i - 3:i] == [1, 1, 1])
    n_miss = sum(1 for s in by_player.values() for i in range(3, len(s)) if s[i - 3:i] == [0, 0, 0])
    details = next(r for r in e["identity"]["attack_results"]
                   if r["test_id_version"].startswith("A-SAMPLE-SIZE"))["details"]
    assert (details["n_after_makes"], details["n_after_misses"]) == (n_makes, n_miss)
    expected = "INSUFFICIENT_EVIDENCE" if min(n_makes, n_miss) < 30 else None
    if expected:
        assert e["identity"]["decision"] == expected
    assert e["identity"]["data"]["data_mode"] == "REAL_NBA_RETROSPECTIVE"
