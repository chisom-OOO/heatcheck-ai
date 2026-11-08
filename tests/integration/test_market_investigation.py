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
    # plain-English template (user, 8 Nov): whole percent, the market as "bid to ask"
    assert "about 40%" in out["heater_text"] and "nearer 26 to 27" in out["heater_text"]
    for banned in (r"\bbet\b", r"\bedge found\b"):
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
    # Heater never voices a SAMPLE value as the model's forecast, and the LLM is not called.
    called = []
    out, _ = run(verified(recs), sha, doc=doc, heater_llm=lambda s_, u: called.append(1) or "x")
    assert out["heater_source"] == "FIXED_SAMPLE" and not called
    assert "SAMPLE" in out["heater_text"] and "%" not in out["heater_text"]
    assert not any(ch.isdigit() for ch in out["heater_text"])


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
    # The Ref line itself says RECORDED with the quote time, not only the evidence note.
    assert out["ref_text"].endswith(f"RECORDED: price received {POLY_RECEIVED[:19]}Z, not live.")
    assert cfg.ledger.get(out["evidence_id"])["identity"]["game"]["game_id"] == GAME
    code, out = run_investigation({**req, "game_id": "nba:0022600999"}, fc, cfg)
    assert code == 404


VERIFICATIONS = ROOT / "data" / "max" / "mapping_verifications"


def test_route_recorded_with_max_verification_is_worth_investigating(tmp_path):
    fc = tmp_path / "forecasts.json"
    fc.write_text(json.dumps(forecast_doc()), encoding="utf-8")
    cfg = InvestigationConfig(market_bundle=BUNDLE, ledger=EvidenceLedger(tmp_path / "inv.jsonl"),
                              mode="RECORDED", verifications=VERIFICATIONS)
    code, out = run_investigation({"game_id": GAME, "mapping_id": POLY, "message": "why?"}, fc, cfg)
    assert code == 200 and out["verdict"] == VERDICT_WORTH, out["ref_text"]
    ident = cfg.ledger.get(out["evidence_id"])["identity"]
    assert ident["quote"]["mapping_status"] == "VERIFIED"
    # Kalshi has no verification and only bids: still Can't compare.
    code, out = run_investigation({"game_id": GAME, "mapping_id": KALSHI, "message": "?"}, fc, cfg)
    assert out["verdict"] == VERDICT_CANT


def test_route_searches_bundle_directory_and_live_staleness(tmp_path):
    fc = tmp_path / "forecasts.json"
    fc.write_text(json.dumps(forecast_doc()), encoding="utf-8")
    cfg = InvestigationConfig(market_bundle=[ROOT / "tests" / "fixtures" / "quotes"],
                              ledger=EvidenceLedger(tmp_path / "inv.jsonl"), mode="LIVE",
                              verifications=VERIFICATIONS, clock=lambda: "2026-11-07T16:25:00Z")
    code, out = run_investigation({"game_id": GAME, "mapping_id": POLY, "message": "why?"}, fc, cfg)
    assert code == 200 and out["verdict"] == VERDICT_CANT
    assert "STALE" in {c["check_id"]: c for c in out["challenger_checks"]}["QUOTE_FRESH"]["detail"]


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


@pytest.mark.parametrize("as_of", ["2026-11-07T16:21:17.710454Z", "2026-11-07T16:21:30Z",
                                   "2026-11-07T16:30:00Z", "2026-11-07T16:00:00Z"])
def test_latest_quote_matches_eligibility_rule_on_verified_mapping(bundle, as_of):
    from heatcheck.agents.market_investigation import latest_quote
    from heatcheck.contracts.eligibility import LIVE_MAX_AGE, select_quote_for_cutoff
    _, recs = bundle
    recs = verified(recs)
    mapping = next(r for r in recs if r["record_type"] == "VENUE_MAPPING" and r["body"]["mapping_id"] == POLY)
    quotes = [r for r in recs if r["record_type"] == "QUOTE" and r["body"]["mapping_id"] == POLY]
    a = select_quote_for_cutoff(mapping, quotes, as_of, LIVE_MAX_AGE)
    b = latest_quote(quotes, as_of, LIVE_MAX_AGE)
    assert (a.status, a.quote_record_id, a.age_seconds) == (b.status, b.quote_record_id, b.age_seconds)


# ------------------------------------------------------------------ home-bias caveat (Research calibration 6cd2431)

from heatcheck.agents.market_investigation import HOME_BIAS_CAVEAT  # noqa: E402


def test_home_bias_caveat_text_is_researchs_fixed_text():
    assert HOME_BIAS_CAVEAT == ("On last season's games, this model overrated home teams by about 7 points "
                                "(62.4% predicted vs 55.5% actual). Part of any home-side gap is the model's own bias.")


def test_home_bias_caveat_when_model_favours_home_more_than_market(bundle):
    sha, recs = bundle
    out, ident = run(verified(recs), sha)  # IND is home, p 0.4 above the ask 0.27
    assert out["flag"] == "FORECAST_ABOVE_ASK" and out["caveats"] == [HOME_BIAS_CAVEAT]
    assert ident["caveats"] == [HOME_BIAS_CAVEAT]
    assert out["verdict"] == VERDICT_WORTH and "Edge unverified" in out["verdict"]  # verdict unchanged
    assert HOME_BIAS_CAVEAT not in out["ref_text"]
    # Heater reacts in words, AFTER the Ref: the bias line is his reaction, not his first line
    assert "own bias" in out["heater_reaction"] and "own bias" not in out["heater_text"]


@pytest.mark.parametrize("p_home", [0.2, 0.265])  # below the bid 0.26; inside the spread 0.26-0.27
def test_no_home_bias_caveat_when_model_not_above_the_ask(bundle, p_home):
    sha, recs = bundle
    out, _ = run(verified(recs), sha, doc=forecast_doc(p_home))
    assert out["flag"] != "FORECAST_ABOVE_ASK" and out["caveats"] == []
    assert "own bias" not in out["heater_text"] + out["heater_reaction"]


def test_no_home_bias_caveat_for_the_away_team_or_a_sample(bundle):
    sha, recs = bundle
    recs_away = verified(recs)
    for r in recs_away:
        if r["record_type"] == "VENUE_MAPPING" and r["body"]["mapping_id"] == POLY:
            r["body"]["team_id"] = DEN  # in-memory only: contract pays on the away team
    out, _ = run(recs_away, sha)  # away team 0.6 above the ask: favours the AWAY team, no home caveat
    assert out["team"] == "Denver Nuggets" and out["caveats"] == []
    doc = forecast_doc()
    doc["source"] = {"results": "SAMPLE - hand-made", "fetched_utc": "SAMPLE", "sha256": "SAMPLE",
                     "cross_check": "NOT_RUN"}
    out, _ = run(verified(recs), sha, doc=doc)
    assert out["caveats"] == []


# ------------------------------------------------------------------ Heater speaks before the Ref (rehearsal fix)

REF_WORDS = ("ref", "verdict", "unverified", "worth investigating", "can't compare", "own bias", "calibration")


def test_heater_first_line_never_mentions_the_ref_or_its_verdict(bundle):
    sha, recs = bundle
    for kw in ({}, {"as_of": "2026-11-07T22:30:00Z"}, {"doc": forecast_doc(0.2)}):
        out, ident = run(verified(recs), sha, **kw)
        low = out["heater_text"].lower()
        assert not [w for w in REF_WORDS if w in low], out["heater_text"]
        assert out["heater_reaction"] and ident["heater"]["reaction"] == out["heater_reaction"]


def test_llm_heater_is_not_given_the_verdict_or_the_bias(bundle):
    sha, recs = bundle
    seen = []
    run(verified(recs), sha, heater_llm=lambda s_, u: seen.append((s_, json.loads(u))) or "")
    system, ctx = seen[0]
    assert "refs_verdict" not in ctx and "known_model_bias" not in ctx
    assert "BEFORE the Ref" in system


def test_llm_take_that_mentions_the_ref_falls_back_to_the_template(bundle):
    sha, recs = bundle
    out, _ = run(verified(recs), sha, heater_llm=lambda s_, u: "The Ref will say worth a look, I bet!")
    assert out["heater_source"].startswith("TEMPLATE (guard rejected") and "ref:" in out["heater_source"]


def test_board_load_with_no_message_does_not_call_the_model(bundle):
    sha, recs = bundle
    called = []
    out, _ = run(verified(recs), sha, message="", heater_llm=lambda s_, u: called.append(1) or "x")
    assert called == [] and out["heater_source"] == "TEMPLATE"


def test_no_home_bias_caveat_when_the_card_cannot_compare(bundle):
    sha, recs = bundle
    out, _ = run(verified(recs), sha, as_of="2026-11-07T22:30:00Z")  # after tip: Can't compare
    assert out["verdict"] == VERDICT_CANT and out["caveats"] == []
    assert "own bias" not in out["heater_text"] + out["heater_reaction"]


# ------------------------------------------------------------------ safer gambling: no betting wording from Heater

def test_every_market_heater_template_and_reaction_has_no_betting_wording(bundle):
    from heatcheck.agents.dialogue import betting_words
    sha, recs = bundle
    sample = forecast_doc()
    sample["source"] = {"results": "SAMPLE - hand-made", "fetched_utc": "SAMPLE", "sha256": "SAMPLE",
                        "cross_check": "NOT_RUN"}
    cases = {"above ask": {}, "below bid": {"doc": forecast_doc(0.2)}, "inside spread": {"doc": forecast_doc(0.265)},
             "after tip": {"as_of": "2026-11-07T22:30:00Z"}, "sample": {"doc": sample},
             "hypothetical": {"message": "what if Haliburton is out?"}}
    seen = set()
    for name, kw in cases.items():
        out, _ = run(verified(recs), sha, **kw)
        for t in (out["heater_text"], out["heater_reaction"]):
            assert betting_words(t) == [], (name, t)
        seen.add(out["heater_source"])
    assert {"TEMPLATE", "FIXED_SAMPLE", "FIXED_HYPOTHETICAL"} <= seen


@pytest.mark.parametrize("line", ["Indiana is a lock tonight?", "That's a value bet, folks?",
                                  "You can't lose with Indiana?", "Lock it in: Indiana?"])
def test_model_heater_line_with_betting_wording_falls_back_to_the_template(bundle, line):
    sha, recs = bundle
    out, _ = run(verified(recs), sha, heater_llm=lambda s_, u: line)
    assert out["heater_source"].startswith("TEMPLATE (guard rejected") and out["heater_text"] != line


# ------------------------------------------------------------------ Frost on market cards (Max, 8 Nov 2026)

def test_market_card_has_three_anchored_frost_challenges(bundle):
    from heatcheck.agents.dialogue import betting_words, number_violations
    from heatcheck.agents.market_investigation import HOME_BIAS_CAVEAT
    sha, recs = bundle
    for kw in ({}, {"doc": forecast_doc(0.2)}, {"as_of": "2026-11-07T22:30:00Z"}):
        out, ident = run(verified(recs), sha, **kw)
        assert [f["check"] for f in out["frost"]] == ["model_bias", "mapping_verification", "inputs_used"]
        assert all(set(f) == {"check", "question", "chip", "source"} and f["source"] for f in out["frost"])
        assert out["frost_reaction"] and ident["frost"]["challenges"] == out["frost"]
        facts = {"note": HOME_BIAS_CAVEAT, "checks": out["challenger_checks"]}
        for f in out["frost"]:
            assert number_violations(f["chip"], facts) == [], f["chip"]
            assert betting_words(f["question"] + " " + f["chip"]) == []
    assert run(recs, sha)[0]["frost"][1]["chip"].startswith("Not confirmed:")
    good = run(verified(recs), sha)[0]["frost"]
    assert good[1]["chip"].startswith("Verified: the contract pays if the Indiana Pacers win, overtime included")
    assert good[2]["chip"] == ("The model uses only Elo rating (home), Elo rating (away) and home court. "
                               "It does not see lineups, injuries, rest, recent form or matchups.")
    assert "_" not in good[1]["chip"] + good[2]["chip"] and "nba-team" not in good[1]["chip"]



# ------------------------------------------------------------------ plain-English walk-through (user, 8 Nov)

BULLS_EXAMPLE = ("My numbers give the Bulls about 36% here, while the market has them nearer 21 to 22. "
                 "That gap is mostly the ratings: Bulls around 1380 against 1577, with home court helping "
                 "a little. Before I'd read anything into it I'd want to check injuries, rest and tonight's lineups.")
BULLS_FACTS = {"p_team_win": "0.363546", "p_team_win_pct": "36.4%", "best_bid": "0.21", "best_bid_pct": "21.0%",
               "best_ask": "0.22", "best_ask_pct": "22.0%", "elo_home": 1380.057, "elo_away": 1576.6,
               "team": "Chicago Bulls", "inputs_used": ["elo_rating_home", "elo_rating_away", "home_court"]}


def test_user_example_passes_the_relaxed_guard():
    from heatcheck.agents.market_investigation import heater_guard
    assert heater_guard(BULLS_EXAMPLE, BULLS_FACTS["inputs_used"], BULLS_FACTS) == []


def test_relaxed_guard_still_refuses_numbers_and_field_names_not_on_the_card():
    from heatcheck.agents.market_investigation import heater_guard
    ins = BULLS_FACTS["inputs_used"]
    assert heater_guard("My numbers give the Bulls about 41% here.", ins, BULLS_FACTS)          # not a rounding
    assert heater_guard("The Bulls sit at 1400 against 1577.", ins, BULLS_FACTS)               # not a rounding
    assert heater_guard('The "best_bid" is 21%.', ins, BULLS_FACTS)                            # field name
    assert heater_guard("The Bulls are tired from travel.", ins, BULLS_FACTS)                  # rest stated as a reason
    assert heater_guard("That gap is value worth a bet.", ins, BULLS_FACTS)                    # betting wording


def test_walk_through_never_shows_a_raw_probability_or_field_name(bundle):
    sha, recs = bundle
    out, _ = run(verified(recs), sha)
    text = out["heater_text"]
    p = out["forecast"]["p_team_win"]
    assert f'"{p}"' not in text and '"0.363546"' not in text
    assert not re.search(r"\b0\.\d+", text)                  # no decimal fraction
    assert not re.search(r"\b[a-z]+(?:_[a-z0-9]+)+\b", text)   # no snake_case field name
    assert len(re.findall(r"[.!?](?:\s|$)", text)) <= 3


def test_check_framing_is_not_a_ref_mention_but_other_check_wording_is():
    from heatcheck.agents.dialogue import take_mentions_ref
    from heatcheck.agents.market_investigation import CHECK_FRAME
    ok = "Before I'd read anything into it I'd want to check injuries, rest and tonight's lineups."
    assert take_mentions_ref(CHECK_FRAME.sub("I'd want to see", ok)) == []
    assert take_mentions_ref(CHECK_FRAME.sub("I'd want to see", "The checks all passed, so it's real."))
