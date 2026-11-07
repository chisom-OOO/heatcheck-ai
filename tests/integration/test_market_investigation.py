"""MARKET_COMPARISON investigation (heatcheck-market-investigation/1).

Quotes: Experience's RECORDED E-001 bundle for nba:0022600189 (DEN at IND), unchanged on disk.
Forecast: an in-test document whose numbers are INVENTED for these format/flow tests. It is not
a Research forecast. Tests that need a verified mapping flip its status in an in-memory copy;
the stored mappings remain PROPOSED.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest

from heatcheck.agents.market_investigation import (
    HYPOTHETICAL_ANSWER,
    VERDICT_CANT,
    VERDICT_WORTH,
    heater_guard,
    investigate,
)
from heatcheck.agents.recorded import find_recorded
from heatcheck.api.dialogue_server import (
    InvestigationConfig,
    run_investigation,
    validate_investigate_request,
)
from heatcheck.contracts.bundle import load_bundle
from heatcheck.contracts.live_forecast import validate_live_forecast
from heatcheck.ledger.evidence import EvidenceLedger

ROOT = Path(__file__).resolve().parents[2]
BUNDLE = ROOT / "tests" / "fixtures" / "quotes" / "e001-recorded-0022600189"
EVIDENCE = ROOT / "evidence" / "evidence.jsonl"
GAME = "nba:0022600189"
POLY = ("map:nba:0022600189:POLYMARKET:"
        "100155597339514587735512788056351223587036241159790520590685103796616707991866")
KALSHI = "map:nba:0022600189:KALSHI:KXNBAGAME-26NOV07DENIND-IND:yes"
POLY_RECEIVED = "2026-11-07T16:21:17.710454Z"
IND, DEN = "nba-team:1610612754", "nba-team:1610612743"
INPUTS = ["elo_rating_home", "elo_rating_away", "home_court"]


def forecast_doc(p_home=0.4) -> dict:
    return {
        "format": "heatcheck-live-forecast/1", "label": "DESCRIPTIVE FORECAST",
        "model": "TEST ONLY - invented numbers", "inputs_used": list(INPUTS),
        "data_cutoff_utc": "2026-11-07T15:00:00Z",
        "source": {"results": "test fixture (invented values)", "fetched_utc": "2026-11-07T15:00:00Z",
                   "sha256": "b" * 64, "cross_check": "NOT_RUN"},
        "backtest_2024_25": {"log_loss": 0.6, "brier": 0.2, "games": 1},
        "games": [{"game_id": GAME, "tip_utc": "2026-11-07T22:00:00Z", "home_team_id": IND,
                   "away_team_id": DEN, "home_team": "Indiana Pacers", "away_team": "Denver Nuggets",
                   "p_home_win": p_home, "elo_home": 1450.0, "elo_away": 1600.0}],
    }


@pytest.fixture(scope="module")
def bundle():
    manifest, recs = load_bundle(BUNDLE)
    return manifest["records_sha256"], recs


def verified(recs, mapping_id=POLY):
    out = copy.deepcopy(recs)
    for r in out:
        if r["record_type"] == "VENUE_MAPPING" and r["body"]["mapping_id"] == mapping_id:
            r["body"]["status"] = "VERIFIED"
            if r["body"]["overtime_convention"] == "UNKNOWN":  # in-test only (Kalshi rule not read)
                r["body"]["overtime_convention"] = "INCLUDES_OVERTIME"
    return out


def run(recs, sha, *, doc=None, mapping=POLY, as_of=POLY_RECEIVED, message="why the flag?", **kw):
    lf = validate_live_forecast(doc or forecast_doc())
    mode = kw.pop("mode", "RECORDED")
    return investigate(lf, "c" * 64, GAME, mapping, recs, sha, message, as_of, mode=mode, **kw)


def checks(out):
    return {c["check_id"]: c for c in out["challenger_checks"]}


def test_stored_proposed_mapping_cannot_compare(bundle):
    sha, recs = bundle
    out, ident = run(recs, sha)
    assert out["verdict"] == VERDICT_CANT
    assert checks(out)["OUTCOME_MATCH"]["status"] == "FAIL" and "PROPOSED" in out["ref_text"]
    assert ident["verdict"] == VERDICT_CANT and ident["quote"]["mapping_status"] == "PROPOSED"


def test_matched_fresh_card_is_worth_investigating(bundle):
    sha, recs = bundle
    out, ident = run(verified(recs), sha)
    assert out["verdict"] == VERDICT_WORTH
    assert all(c["status"] in ("PASS", "INFO") for c in out["challenger_checks"])
    # Hand-derived: best bid = max BID = 0.26, best ask = min ASK = 0.27; IND is home, p 0.4 > ask.
    assert out["quote"]["best_bid"] == "0.26" and out["quote"]["best_ask"] == "0.27"
    assert out["flag"] == "FORECAST_ABOVE_ASK" and out["forecast"]["p_team_win"] == "0.4"
    assert "40.0%" in out["heater_text"] and "27.0%" in out["heater_text"]
    for banned in (r"bet", r"edge found"):
        assert not re.search(banned, out["ref_text"] + " " + out["heater_text"], re.IGNORECASE)
    skill = checks(out)["MARKET_SKILL_EVIDENCE"]["detail"]
    assert "no evaluation shows this model beats the market" in skill


def test_away_team_probability_is_complement(bundle):
    sha, recs = bundle
    recs = verified(recs)
    for r in recs:
        if r["record_type"] == "VENUE_MAPPING" and r["body"]["mapping_id"] == POLY:
            r["body"]["team_id"] = DEN  # in-memory only: pretend the contract pays on Denver
    out, _ = run(recs, sha)
    assert out["forecast"]["p_team_win"] == "0.6" and out["team"] == "Denver Nuggets"


def test_live_quote_older_than_limit_is_stale(bundle):
    sha, recs = bundle
    out, _ = run(verified(recs), sha, as_of="2026-11-07T16:23:00Z", mode="LIVE")
    assert out["verdict"] == VERDICT_CANT and "STALE" in checks(out)["QUOTE_FRESH"]["detail"]


def test_one_sided_book_cannot_compare(bundle):
    sha, recs = bundle
    out, _ = run(verified(recs, KALSHI), sha, mapping=KALSHI, as_of="2026-11-07T16:21:18.328918Z")
    assert checks(out)["QUOTE_SIDE"]["status"] == "FAIL" and out["verdict"] == VERDICT_CANT
    assert out["flag"] == "NO_TWO_SIDED_QUOTE"


def test_swapped_teams_fail_game_match(bundle):
    sha, recs = bundle
    doc = forecast_doc()
    g = doc["games"][0]
    g["home_team_id"], g["away_team_id"] = DEN, IND
    out, _ = run(verified(recs), sha, doc=doc)
    assert checks(out)["GAME_MATCH"]["status"] == "FAIL" and out["verdict"] == VERDICT_CANT


def test_tip_time_mismatch_fails_game_match(bundle):
    sha, recs = bundle
    doc = forecast_doc()
    doc["games"][0]["tip_utc"] = "2026-11-08T00:00:00Z"
    out, _ = run(verified(recs), sha, doc=doc)
    assert "tip time differs" in checks(out)["GAME_MATCH"]["detail"]


def test_cutoff_after_comparison_time_fails(bundle):
    sha, recs = bundle
    doc = forecast_doc()
    doc["data_cutoff_utc"] = "2026-11-07T17:00:00Z"
    out, _ = run(verified(recs), sha, doc=doc)
    assert checks(out)["FORECAST_CUTOFF"]["status"] == "FAIL"


def test_after_tip_is_not_pregame(bundle):
    sha, recs = bundle
    out, _ = run(verified(recs), sha, as_of="2026-11-07T22:00:30Z", mode="LIVE")
    assert "tipped off" in checks(out)["QUOTE_FRESH"]["detail"]


def test_sample_forecast_cannot_compare(bundle):
    sha, recs = bundle
    doc = forecast_doc()
    doc["source"] = {"results": "SAMPLE - hand-made", "fetched_utc": "SAMPLE", "sha256": "SAMPLE",
                     "cross_check": "NOT_RUN"}
    out, ident = run(verified(recs), sha, doc=doc)
    assert out["verdict"] == VERDICT_CANT and out["is_sample"] and ident["forecast"]["is_sample"]
    assert "SAMPLE" in out["data_note"]


def test_missing_inputs_reported(bundle):
    sha, recs = bundle
    out, _ = run(verified(recs), sha)
    detail = checks(out)["MISSING_INPUTS"]["detail"]
    assert detail.index("lineups") < detail.index("rest") and "injuries" in detail


# --------------------------------------------------------------------------- Heater guard

FACTS = {"p_team_win": "0.4", "p_team_win_pct": "40.0%", "best_ask": "0.27", "best_ask_pct": "27.0%"}


@pytest.mark.parametrize("text", [
    "The model has Indiana at 40.0%. Is Indiana rested after travel?",
    "Elo ratings and home court put Indiana at 40.0%, above the ask of 27.0%. Could injuries matter?",
])
def test_guard_allows_inputs_and_questions(text):
    assert heater_guard(text, INPUTS, FACTS) == []


@pytest.mark.parametrize("text,needle", [
    ("Indiana is rested, so the model likes them.", "rest"),
    ("The market missed a back-to-back.", "rest"),
    ("Haliburton's injury explains it.", "injuries"),
    ("You should bet Indiana.", "betting"),
    ("Edge found on Indiana.", "betting"),
    ("Indiana sits at 55%.", "number 55%"),
    ("This proves the model is right.", "betting"),
])
def test_guard_rejects(text, needle):
    problems = heater_guard(text, INPUTS, FACTS)
    assert any(needle in p for p in problems), problems


def test_llm_text_shown_only_if_guard_passes(bundle):
    sha, recs = bundle
    ok = "Elo and home court put Indiana at 40.0%. Is rest a factor?"
    out, _ = run(verified(recs), sha, heater_llm=lambda s, u: ok)
    assert out["heater_text"] == ok and out["heater_source"] == "LLM"
    out, _ = run(verified(recs), sha, heater_llm=lambda s, u: "Indiana is rested. Bet it at 55%.")
    assert out["heater_source"].startswith("TEMPLATE (guard rejected") and "Bet" not in out["heater_text"]

    def down(s, u):
        raise TimeoutError

    out, _ = run(verified(recs), sha, heater_llm=down)
    assert out["heater_source"] == "TEMPLATE (fallback: TimeoutError)"


def test_hypothetical_gets_fixed_answer(bundle):
    sha, recs = bundle
    called = []
    out, _ = run(verified(recs), sha, message="What if Haliburton is out?",
                 heater_llm=lambda s, u: called.append(1) or "x")
    assert out["hypothetical"] and not called
    assert out["heater_text"] == HYPOTHETICAL_ANSWER.format(inputs=", ".join(INPUTS))
    assert "can't quantify lineup changes" in out["heater_text"]


def test_back_to_back_thesis_uses_research_recorded_check(bundle):
    sha, recs = bundle
    entry = find_recorded(EvidenceLedger.open_readonly(EVIDENCE), "GP-REST")
    assert entry is not None
    out, ident = run(verified(recs), sha, message="Denver is on a back-to-back, right?", thesis_entry=entry)
    assert out["thesis"]["status"] == "RECORDED"
    assert out["thesis"]["decision"] == entry["identity"]["decision"]
    assert ident["thesis"]["evidence_id"] == entry["evidence_id"]
    out, _ = run(verified(recs), sha, message="why the flag?", thesis_entry=entry)
    assert out["thesis"] is None


# --------------------------------------------------------------------------- ledger + route


def test_ledger_records_forecast_quote_verdict(bundle, tmp_path):
    sha, recs = bundle
    out, ident = run(verified(recs), sha, message="my private question")
    led = EvidenceLedger(tmp_path / "inv.jsonl")
    entry, retried = led.put(ident)
    assert not retried
    i = led.get(entry["evidence_id"])["identity"]
    assert i["forecast"]["p_team_win"] == "0.4" and i["quote"]["best_ask"] == "0.27"
    assert i["quote"]["received_utc"] == POLY_RECEIVED and i["as_of_utc"] == POLY_RECEIVED
    assert i["verdict"] == VERDICT_WORTH and i["outcome"] is None
    assert "my private question" not in json.dumps(i)


def test_route_recorded_mode_end_to_end(tmp_path):
    fc = tmp_path / "forecasts.json"
    fc.write_text(json.dumps(forecast_doc()), encoding="utf-8")
    cfg = InvestigationConfig(market_bundle=BUNDLE, ledger=EvidenceLedger(tmp_path / "inv.jsonl"),
                              mode="RECORDED")
    body = json.dumps({"game_id": GAME, "mapping_id": POLY, "message": "why?"}).encode()
    req = validate_investigate_request(body)
    code, out = run_investigation(req, fc, cfg)
    assert code == 200 and out["verdict"] == VERDICT_CANT  # stored mapping is PROPOSED
    assert out["as_of_utc"] == POLY_RECEIVED and "RECORDED" in out["data_note"]
    assert cfg.ledger.get(out["evidence_id"])["identity"]["game"]["game_id"] == GAME
    code, out = run_investigation({**req, "game_id": "nba:0022600999"}, fc, cfg)
    assert code == 404


def test_route_without_forecast_cannot_compare(tmp_path):
    cfg = InvestigationConfig(market_bundle=BUNDLE, ledger=EvidenceLedger(tmp_path / "inv.jsonl"))
    req = {"game_id": GAME, "mapping_id": POLY, "message": ""}
    code, out = run_investigation(req, tmp_path / "none.json", cfg)
    assert code == 200 and out["verdict"] == VERDICT_CANT and out["evidence_id"] is None


@pytest.mark.parametrize("body", [b"{}", b'{"game_id":"x","mapping_id":"y"}',
                                  b'{"game_id":"x","mapping_id":"y","message":1}'])
def test_route_rejects_bad_body(body):
    with pytest.raises(ValueError):
        validate_investigate_request(body)
