"""Free-text routing and scenario questions (heatcheck/agents/scenario.py, /api/route, /api/scenario).

Inputs: Research's real data/live/forecasts.json (research/live-forecast@e03629d). The provider
classes below are TEST doubles of Research's scenario-effects signature; their numbers are made up
to exercise the code paths and are never served by the app (the app uses ResearchStub).
"""

from __future__ import annotations

import json
import re
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from heatcheck.agents.scenario import (
    VERDICT,
    YOUR_ASSUMPTION,
    ConfirmationError,
    ResearchStub,
    check_confirmation,
    elo_from_p,
    estimate_scenario,
    home_court_in_forecast,
    p_from_elo,
    parse_changes,
    parse_scenario,
    route,
    verdict_for,
)
from heatcheck.api.dialogue_server import ScenarioConfig, serve
from heatcheck.ledger.evidence import EvidenceLedger

ROOT = Path(__file__).resolve().parents[2]
FORECAST = ROOT / "data" / "live" / "forecasts.json"
DOC = json.loads(FORECAST.read_text(encoding="utf-8"))
GAMES = DOC["games"]
G = {g["game_id"][-3:]: g for g in GAMES}
NOW = "2026-11-08T00:40:00Z"  # before CLE/OKC tip
SHA = "f" * 64


def kinds(msg, row=None):
    return [c["kind"] for c in parse_changes(msg, row)]


# ------------------------------------------------------------------ routing

@pytest.mark.parametrize("msg,action,game", [
    ("find me an interesting market tonight", "OPEN_BOARD", None),
    ("What are the odds tonight?", "OPEN_BOARD", None),
    ("which games are on tonight", "OPEN_BOARD", None),
    ("What about the Celtics game?", "OPEN_CARD", "200"),
    ("Knicks vs Cavs", "OPEN_CARD", "191"),
    ("show me OKC", "OPEN_CARD", "192"),
    ("how about Brooklyn tonight", "OPEN_CARD", "199"),   # BKN at ATL tipped 00:30Z; next is Sunday at DAL
    ("Is the hot hand real?", "DIALOGUE", None),
    ("Do home teams win more?", "DIALOGUE", None),
    ("Does rest matter?", "DIALOGUE", None),
    ("What if Cleveland played on a neutral floor?", "SCENARIO", "191"),
    ("Assume it costs Boston 5%", "SCENARIO", "200"),
    ("Cleveland without Donovan Mitchell", "SCENARIO", "191"),
])
def test_route(msg, action, game):
    r = route(msg, GAMES, NOW)
    assert r["action"] == action, r
    assert (r["game_id"] or "")[-3:] == (game or "")


def test_route_brooklyn_after_saturday_tip_picks_sunday():
    assert route("Brooklyn tonight", GAMES, "2026-11-08T01:05:00Z")["game_id"] == "nba:0022600199"
    assert route("Brooklyn tonight", GAMES, "2026-11-08T00:20:00Z")["game_id"] == "nba:0022600190"


def test_heat_alone_is_not_miami():
    assert route("is HeatCheck any good?", GAMES, NOW)["action"] == "DIALOGUE"


# ------------------------------------------------------------------ parsing

def test_parse_each_kind():
    cle, bos = G["191"], G["200"]
    assert kinds("on a neutral floor", cle) == ["VENUE_NEUTRAL"]
    assert kinds("what if the Knicks were at home", cle) == ["HOME_AWAY_SWAP"]
    assert kinds("what if Cleveland were at home", cle) == []          # already home: no change
    assert kinds("swap home and away", cle) == ["HOME_AWAY_SWAP"]
    assert kinds("if Polymarket priced Cleveland at 55%", cle) == ["MARKET_PRICE"]
    assert kinds("Cleveland without Donovan Mitchell", cle) == ["PLAYER_OUT"]
    assert kinds("the Bucks are on a back-to-back", bos) == ["REST"]
    c = parse_changes("Assume it costs Boston 5% and the Bucks are on a back-to-back", bos)
    assert c[0] == {"kind": "USER_ADJUSTMENT", "team": "Boston Celtics", "amount": -5.0, "unit": "PROB_POINTS",
                    "source_text": "Assume it costs Boston 5%"}
    assert c[1]["kind"] == "REST" and c[1]["team"] == "Milwaukee Bucks"
    pts = parse_changes("assume it costs Boston 3 points", bos)[0]
    assert (pts["amount"], pts["unit"]) == (-3.0, "GAME_POINTS")
    assert parse_changes("if OKC were priced at 90%", G["192"])[0]["price"] == 0.9


def test_interpretation_needs_confirmation_and_shows_no_number():
    it = parse_scenario("What if Cleveland played on a neutral floor?", G["191"], SHA)
    assert it["status"] == "NEEDS_CONFIRMATION" and it["label"] == "READ_BACK"
    assert it["interpretation"] == ["The game is played on a neutral floor: no home court."]
    assert "%" not in it["heater_text"] and "Confirm" in it["heater_text"]
    assert parse_scenario("tell me a story", G["191"], SHA)["status"] == "NO_CHANGES"


# ------------------------------------------------------------------ confirmation binding

def _req(it, **kw):
    return {"game_id": it["game_id"], "changes": it["changes"], "focus_team": it["focus_team"],
            "interpretation_id": it["interpretation_id"], "confirmed": True, **kw}


def test_confirmation_is_bound_to_the_exact_interpretation():
    row = G["200"]
    it = parse_scenario("Assume it costs Boston 5%", row, SHA)
    assert check_confirmation(_req(it), row, SHA)[0] == it["changes"]
    with pytest.raises(ConfirmationError, match="not confirmed"):
        check_confirmation(_req(it, confirmed=False), row, SHA)
    edited = [dict(it["changes"][0], amount=-50.0)]
    with pytest.raises(ConfirmationError, match="revoked"):
        check_confirmation(_req(it, changes=edited), row, SHA)
    with pytest.raises(ConfirmationError, match="revoked"):
        check_confirmation(_req(it), row, "e" * 64)                    # forecast file changed
    with pytest.raises(ConfirmationError, match="revoked"):
        check_confirmation(_req(it, focus_team="Milwaukee Bucks"), row, SHA)
    with pytest.raises(ConfirmationError):
        check_confirmation(_req(it, changes=[{"kind": "PLAYER_OUT", "player": "X", "evil": 1}]), row, SHA)


# ------------------------------------------------------------------ estimation

def est(msg, row, provider=None, sample=False, as_of=NOW):
    it = parse_scenario(msg, row, SHA)
    return estimate_scenario(it["changes"], row, DOC, sample, SHA, as_of, provider or ResearchStub(),
                             focus_team=it["focus_team"])


def test_baseline_reproduces_and_game_189_is_neutral():
    assert [home_court_in_forecast(g) for g in GAMES] == [0.0] + [100.0] * 13
    g = G["189"]
    # Research's report: 0.304 with home court, 0.197 at the neutral site
    assert round(p_from_elo(g["elo_home"] - g["elo_away"] + 100), 3) == 0.304


def test_neutral_and_swap_recalculate_with_the_forecasts_own_elo():
    cle = G["191"]
    d = cle["elo_home"] - cle["elo_away"]
    e = est("What if Cleveland played on a neutral floor?", cle)
    assert e["baseline"]["p"] == round(cle["p_home_win"], 4)
    assert e["scenario"]["p"] == round(p_from_elo(d), 4) and e["scenario"]["range_is_point"]
    assert e["effects"][0]["type"] == "MODEL_RECALC" and e["verdict"] == VERDICT
    s = est("what if the Knicks were at home", cle)
    assert s["focus_team"] == "New York Knicks"
    assert s["baseline"]["p"] == round(1 - cle["p_home_win"], 4)
    assert s["scenario"]["p"] == round(1 - p_from_elo(d - 100), 4)


def test_neutral_on_a_neutral_game_is_flagged_not_double_counted():
    e = est("what if Denver and Indiana played on a neutral floor", G["189"])
    flags = [c for c in e["challenger_checks"] if c["check_id"] == "DOUBLE_COUNT"]
    assert flags[0]["status"] == "FLAG" and "already" in flags[0]["detail"]
    assert e["scenario"]["p"] == e["baseline"]["p"]


def test_neutral_plus_swap_is_a_conflict_with_no_number():
    e = est("swap home and away, on a neutral floor", G["191"])
    assert e["scenario"] is None and "contradict" in e["ref_text"]


def test_user_adjustments():
    bos = G["200"]
    e = est("Assume it costs Boston 5%", bos)
    assert e["focus_team"] == "Boston Celtics"
    assert e["scenario"]["p"] == round(1 - bos["p_home_win"] - 0.05, 4)
    assert e["effects"][0]["type"] == "YOUR_ASSUMPTION" and e["effects"][0]["text"].startswith(YOUR_ASSUMPTION)
    pts = est("assume it costs Boston 3 points", bos)
    assert pts["scenario"] is None and pts["effects"][0]["type"] == "NO_NUMBER"
    assert "points-to-Elo conversion" in pts["effects"][0]["text"]

    class WithConversion(ResearchStub):
        def points_to_elo(self):
            return 28.0
    c = est("assume it costs Boston 3 points", bos, WithConversion())
    d = elo_from_p(bos["p_home_win"])
    assert c["scenario"]["p"] == round(1 - p_from_elo(d + 84), 4)
    huge = est("Assume it costs Boston 90%", bos)
    assert huge["scenario"] is None and any(x["check_id"] == "RANGE" for x in huge["challenger_checks"])


def test_stub_gives_no_number_for_player_out_and_rest():
    e = est("Cleveland without Donovan Mitchell", G["191"])
    assert e["scenario"] is None and e["effects"][0]["type"] == "NO_NUMBER"
    assert "Can't quantify this with the current model; it would need" in e["effects"][0]["text"]
    assert e["provider"]["version"] == "STUB" and e["verdict"] == verdict_for("NO NUMBER")


class FakeResearch(ResearchStub):
    """TEST DOUBLE: made-up estimates to exercise the ESTIMATE path. Never served."""
    identity = {"name": "test-double", "version": "TEST"}

    def __init__(self, **by_kind):
        self.by_kind = by_kind

    def estimate(self, change, ctx):
        return self.by_kind[change["kind"]]


def test_research_estimates_ranges_sample_size_failed_and_staleness():
    cle = G["191"]
    good = {"status": "ESTIMATE", "elo_shift": -40.0, "elo_shift_range": [-70.0, -10.0], "n": 12,
            "verdict": "INSUFFICIENT_EVIDENCE", "data_through_utc": "2024-06-01T00:00:00Z",
            "caveats": ["test double"], "interval": "90% test interval"}
    e = est("Cleveland without Donovan Mitchell", cle, FakeResearch(PLAYER_OUT=good))
    d = elo_from_p(cle["p_home_win"])
    assert e["scenario"]["p"] == round(p_from_elo(d - 40), 4)
    assert e["scenario"]["range"] == [round(p_from_elo(d - 70), 4), round(p_from_elo(d - 10), 4)]
    ch = {c["check_id"]: c["status"] for c in e["challenger_checks"]}
    assert ch["SAMPLE_SIZE"] == "FLAG" and ch["ESTIMATE_STALENESS"] == "FLAG"
    assert e["effects"][0]["n"] == 12 and e["effects"][0]["verdict"] == "INSUFFICIENT_EVIDENCE"
    # the away team's player: the shift helps Cleveland
    away = est("New York without Jalen Brunson", cle, FakeResearch(PLAYER_OUT=good))
    assert away["focus_team"] == "New York Knicks"
    assert away["scenario"]["p"] == round(1 - p_from_elo(d + 40), 4)
    failed = est("Cleveland without Donovan Mitchell", cle, FakeResearch(PLAYER_OUT={**good, "verdict": "FAILED"}))
    assert failed["effects"][0]["type"] == "FAILED_TEST" and not failed["effects"][0]["included"]
    assert failed["scenario"] is None
    nod = est("Cleveland without Donovan Mitchell", cle, FakeResearch(
        PLAYER_OUT={"status": "NO_DATA", "reason": "he has not missed a game"}))
    assert nod["scenario"] is None and "No data: he has not missed a game" in nod["effects"][0]["text"]


def test_double_count_adjustment_and_player_out_same_team():
    e = est("Assume it costs Cleveland 5% because Cleveland is without Donovan Mitchell", G["191"],
            FakeResearch(PLAYER_OUT={"status": "ESTIMATE", "elo_shift": -40.0, "elo_shift_range": [-60, -20],
                                     "n": 200, "verdict": "NOT_TESTED", "caveats": []}))
    dc = [c for c in e["challenger_checks"] if c["check_id"] == "DOUBLE_COUNT"]
    assert dc and dc[0]["status"] == "FLAG" and "counted twice" in dc[0]["detail"]
    assert "Watch out" in e["ref_text"]


def test_market_price_only_compares_the_unchanged_forecast():
    e = est("What if OKC were priced at 90% on Polymarket?", G["192"])
    assert e["scenario"] is None and e["hypothetical_price"] == 0.9
    assert "unchanged forecast for Oklahoma City Thunder sits 3.6 points above it" in e["ref_text"]


def test_sample_forecast_gives_no_numbers():
    e = est("What if Cleveland played on a neutral floor?", G["191"], sample=True)
    assert e["baseline"] is None and e["scenario"] is None and "SAMPLE" in e["ref_text"]


def test_forecast_staleness_flag():
    e = est("What if Cleveland played on a neutral floor?", G["191"], as_of="2026-11-10T00:00:00Z")
    assert {c["check_id"]: c["status"] for c in e["challenger_checks"]}["FORECAST_STALENESS"] == "FLAG"


@pytest.mark.parametrize("msg", ["What if Cleveland played on a neutral floor?", "Assume it costs Boston 5%",
                                 "Cleveland without Donovan Mitchell", "What if OKC were priced at 90%?"])
def test_ref_never_claims_an_edge_or_a_bet(msg):
    row = route(msg, GAMES, NOW)["game_id"]
    e = est(msg, next(g for g in GAMES if g["game_id"] == row))
    assert e["ref_text"].startswith(verdict_for(e["stamp"])) and e["label"] == e["stamp"]
    assert "HYPOTHETICAL" not in e["ref_text"].upper() and e["verdict"].endswith("Edge unverified")
    assert e["number_source"] == {"ESTIMATE": "DATA", "YOUR ASSUMPTION": "USER"}.get(e["stamp"])
    assert not re.search(r"\bbet\b|edge found|guarantee", e["ref_text"], re.I)


# ------------------------------------------------------------------ HTTP

class _NoDialogue:
    def turn(self, q):
        raise AssertionError("dialogue must not be called")


@pytest.fixture
def server(tmp_path):
    fc = tmp_path / "forecasts.json"
    fc.write_bytes(FORECAST.read_bytes())
    ledger = EvidenceLedger(tmp_path / "scenarios.jsonl")
    srv = serve(_NoDialogue(), 0, fc, None, ScenarioConfig(ledger=ledger, clock=lambda: "2026-11-08T00:40:00.000000Z"))
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", ledger, fc
    srv.shutdown()


def post(base, path, obj):
    req = urllib.request.Request(base + path, data=json.dumps(obj).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_http_route_parse_confirm_estimate_and_ledger(server):
    base, ledger, fc = server
    code, r = post(base, "/api/route", {"message": "find me an interesting market tonight"})
    assert code == 200 and r["action"] == "OPEN_BOARD" and "fourteen games" in r["heater_text"]
    assert not re.search(r"\d", r["heater_text"])
    code, r = post(base, "/api/route", {"message": "What about the Celtics game?"})
    assert r["action"] == "OPEN_CARD" and r["game_id"] == "nba:0022600200"
    code, it = post(base, "/api/scenario", {"message": "What if Cleveland played on a neutral floor?"})
    assert code == 200 and it["status"] == "NEEDS_CONFIRMATION"
    body = {"game_id": it["game_id"], "changes": it["changes"], "focus_team": it["focus_team"],
            "interpretation_id": it["interpretation_id"], "confirmed": True, "message_sha256": it["message_sha256"]}
    code, e = post(base, "/api/scenario/estimate", {**body, "confirmed": False})
    assert code == 409
    code, e = post(base, "/api/scenario/estimate", body)
    assert code == 200 and e["verdict"] == VERDICT and e["scenario"]["p"] < e["baseline"]["p"]
    entry = ledger.get(e["evidence_id"])["identity"]
    assert entry["lane"] == "SCENARIO" and entry["label"] == e["stamp"] and entry["changes"] == it["changes"]
    assert entry["interpretation_id"] == it["interpretation_id"] and entry["outcome"] is None
    # a new forecast file revokes the confirmation
    fc.write_bytes(FORECAST.read_bytes() + b"\n")
    code, e = post(base, "/api/scenario/estimate", body)
    assert code == 409 and "revoked" in e["error"]
    code, r = post(base, "/api/scenario", {"message": "what if they were on a neutral floor?"})
    assert r["status"] == "NEEDS_GAME"
    assert post(base, "/api/route", {"message": ""})[0] == 400
    assert post(base, "/api/scenario/estimate", {"game_id": "x"})[0] == 400


# ------------------------------------------------------------------ GET /api/scenario (Experience's heatcheck-scenario/1)

from heatcheck.agents.scenario import MENU_FORMAT, NOT_MERGED, scenario_menu  # noqa: E402

PROB = re.compile(r"^(0(\.\d+)?|1(\.0+)?)$")


class MenuDouble(FakeResearch):
    """TEST DOUBLE with a menu; numbers made up, never served."""

    def __init__(self, items, **by_kind):
        super().__init__(**by_kind)
        self.items = items

    def menu(self, ctx):
        return self.items


def experience_rules(body, card_team, card_p):
    """Python mirror of apps/web/web/market/scenario-model.js readScenarios/scenarioProblem."""
    assert body["format"] == MENU_FORMAT and body["status"] == "OK"
    assert body["team"] == card_team and float(body["baseline"]["p_team_win"]) == card_p
    assert isinstance(body["is_sample"], bool)
    for s in body["scenarios"]:
        assert s["label"] == "ESTIMATE" and s["scenario_id"] and s["text"].strip()
        r = s["range"]
        assert all(PROB.match(x) for x in (s["p_team_win"], r["low"], r["high"], r["level"]))
        assert float(r["low"]) <= float(s["p_team_win"]) <= float(r["high"]) and 0 < float(r["level"]) < 1
        assert isinstance(s["n"], int) and s["n"] >= 1 and s["n_unit"] and s["caveats"]


def test_menu_with_the_stub_is_unavailable_and_says_why():
    m = scenario_menu(G["191"], DOC, False, SHA, NOW, ResearchStub())
    assert m["format"] == MENU_FORMAT and m["status"] == "UNAVAILABLE" and m["reason"] == NOT_MERGED
    assert m["scenarios"] == [] and m["baseline"]["p_team_win"] == f"{G['191']['p_home_win']:.6f}"
    s = scenario_menu(G["191"], DOC, True, SHA, NOW, ResearchStub())
    assert s["status"] == "UNAVAILABLE" and "SAMPLE" in s["reason"]


def test_menu_meets_experiences_rules_and_routes_failed_and_missing():
    b2b = {"kind": "REST", "team": "New York Knicks", "detail": "back-to-back", "text": "The Knicks are on a back-to-back"}
    hurt = {"kind": "PLAYER_OUT", "team": "Cleveland Cavaliers", "player": "X", "text": "X is out"}
    est = {"status": "ESTIMATE", "elo_shift": -30.0, "elo_shift_range": [-55.0, -5.0], "n": 1224, "level": 0.9,
           "verdict": "INSUFFICIENT_EVIDENCE", "caveats": ["test double"]}

    class P(MenuDouble):
        def estimate(self, change, ctx):
            if change["kind"] == "PLAYER_OUT":
                return {**est, "verdict": "FAILED"}
            return est
    cle = G["191"]
    m = scenario_menu(cle, DOC, False, SHA, NOW, P([b2b, hurt]))
    experience_rules(m, "Cleveland Cavaliers", cle["p_home_win"])
    assert len(m["scenarios"]) == 1 and len(m["failed_tests"]) == 1
    d = elo_from_p(cle["p_home_win"])
    s = m["scenarios"][0]
    assert s["p_team_win"] == f"{p_from_elo(d + 30):.6f}"           # the Knicks get worse: Cleveland up
    assert s["range"] == {"low": f"{p_from_elo(d + 5):.6f}", "high": f"{p_from_elo(d + 55):.6f}", "level": "0.90"}
    # same scenario from the Knicks' side
    k = scenario_menu(cle, DOC, False, SHA, NOW, P([b2b]), team="New York Knicks")
    experience_rules(k, "New York Knicks", round(1 - cle["p_home_win"], 6))
    assert k["scenarios"][0]["p_team_win"] == f"{1 - p_from_elo(d + 30):.6f}"
    # no caveats / no level / no data never become an ESTIMATE
    bad = scenario_menu(cle, DOC, False, SHA, NOW, MenuDouble([b2b], REST={**est, "caveats": [], "level": None}))
    assert bad["status"] == "UNAVAILABLE" and "no caveats" in bad["not_quantified"][0]["reason"]
    nod = scenario_menu(cle, DOC, False, SHA, NOW, MenuDouble([b2b], REST={"status": "NO_DATA", "reason": "none"}))
    assert nod["not_quantified"][0]["reason"] == "none"


def test_http_get_scenario(server):
    base, _ledger, _fc = server
    with urllib.request.urlopen(base + "/api/scenario?game_id=nba:0022600191", timeout=10) as r:
        body = json.loads(r.read())
    assert body["format"] == MENU_FORMAT and body["status"] == "UNAVAILABLE" and body["reason"] == NOT_MERGED
    for q, code in (("", 400), ("?game_id=nba:0000000000", 404), ("?game_id=nba:0022600191&team=Boston+Celtics", 400)):
        try:
            urllib.request.urlopen(base + "/api/scenario" + q, timeout=10)
            raise AssertionError("expected an error")
        except urllib.error.HTTPError as e:
            assert e.code == code


# ------------------------------------------------------------------ Research's real functions (research/scenario-effects@d6ad25a)

from heatcheck.agents.research_scenario import ResearchScenario, name_matches, shown_by_default  # noqa: E402


@pytest.fixture(scope="module")
def rs():
    return ResearchScenario()


def _allen(rs, row):
    return next(k for k, v in rs.absence.items() if v.get("player_name") == "J. Allen" and v["team_id"] == row["home_team_id"])


def test_research_worked_example_reproduced_point_and_interval(rs):
    """Research: CLE without J. Allen + NYK back-to-back -> 0.533 raw, 0.649 after shrinkage (f86d797)."""
    row = G["191"]
    theirs = rs.mod.scenario_probability(row["p_home_win"], row["home_team_id"], row["away_team_id"],
                                         [{"type": "player_absence", "key": _allen(rs, row), "side": "home"},
                                          {"type": "schedule", "effect": "back_to_back", "side": "away"}],
                                         rs.absence, rs.schedule)
    assert round(theirs["scenario_p_home"], 3) == 0.649
    mine = est("What if Cleveland were without Jarrett Allen and the Knicks on a back-to-back?", row, rs)
    assert [e["type"] for e in mine["effects"]] == ["ESTIMATE", "ESTIMATE"]
    assert mine["scenario"]["p"] == round(theirs["scenario_p_home"], 4)
    assert mine["scenario"]["range"] == [round(x, 4) for x in theirs["ci95"]]


def test_menu_on_a_sunday_game_meets_experiences_rules(rs):
    row = G["197"]  # LA Lakers at Detroit, Sunday
    m = scenario_menu(row, DOC, False, SHA, NOW, rs)
    experience_rules(m, "Detroit Pistons", row["p_home_win"])
    assert m["status"] == "OK" and len(m["scenarios"]) >= 4
    for s in m["scenarios"]:
        c = s["change"]
        if c["kind"] == "PLAYER_OUT":
            change = {"type": "player_absence", "key": c["key"], "side": "home" if c["team"] == row["home_team"] else "away"}
        else:
            eff = "back_to_back" if c["detail"] == "back-to-back" else "three_in_four"
            change = {"type": "schedule", "effect": eff, "side": "home" if c["team"] == row["home_team"] else "away"}
        r = rs.mod.scenario_probability(row["p_home_win"], row["home_team_id"], row["away_team_id"], [change],
                                        rs.absence, rs.schedule)
        assert s["p_team_win"] == f"{r['scenario_p_home']:.6f}"
        assert s["range"]["low"] == f"{r['ci95'][0]:.6f}" and s["range"]["high"] == f"{r['ci95'][1]:.6f}"
    b2b = next(s for s in m["scenarios"] if "back-to-back" in s["text"])
    assert b2b["verdict"] == "INSUFFICIENT_EVIDENCE" and b2b["caveats"][0].startswith("unproven")


def test_hidden_players_and_raw_only_in_evidence(rs):
    low = next(r for r in rs.absence.values() if "low_involvement_outcome_dependent_appearance" in r["flags"]
               and r.get("player_name") and r["n_games_missed"] >= 5)
    assert shown_by_default(low)[0] is False
    flagged = {**low, "flags": ["absences_mix_rest_injury_suspension_and_coach_decisions"], "shown_by_default": False}
    assert shown_by_default(flagged)[0] is False
    assert shown_by_default({**flagged, "shown_by_default": None, "flags": ["not_shown_by_default"]})[0] is False
    assert shown_by_default({**low, "flags": [], "shown_by_default": True})[0] is True
    for g in GAMES:
        for s in scenario_menu(g, DOC, False, SHA, NOW, rs)["scenarios"]:
            if s["change"]["kind"] == "PLAYER_OUT":
                row = rs.absence[s["change"]["key"]]
                assert shown_by_default(row)[0] and "2025-26" in row["seasons"]
                assert "raw" not in json.dumps({k: v for k, v in s.items() if k != "evidence"})
    assert name_matches("Jarrett Allen", "J. Allen") and name_matches("Allen", "J. Allen")
    assert not name_matches("Grayson Allen", "J. Allen")


def test_free_text_player_with_no_estimate_says_no_data(rs):
    e = est("Cleveland without Nobody Atall", G["191"], rs)
    assert e["scenario"] is None and e["effects"][0]["type"] == "NO_NUMBER" and "No data" in e["effects"][0]["text"]


def test_get_serves_researchs_own_answers_with_raw_only_in_evidence(rs):
    """GET /api/scenario = Research's scenario_api_answer() for the card's team; equals Research's committed
    data/scenario/scenario_answers.json apart from forecast_id/source and Max's added evidence field."""
    committed = json.loads((ROOT / "data" / "scenario" / "scenario_answers.json").read_text(encoding="utf-8"))["answers"]
    n = 0
    for g in GAMES:
        for team, tid in ((g["home_team"], g["home_team_id"]), (g["away_team"], g["away_team_id"])):
            a = rs.api_answer(g, team, SHA)
            want = committed[g["game_id"]][tid]
            assert a["baseline"]["p_team_win"] == want["baseline"]["p_team_win"]
            strip = lambda xs: [{k: v for k, v in x.items() if k != "evidence"} for x in xs]  # noqa: E731
            assert strip(a["scenarios"]) == want["scenarios"]
            experience_rules(a, team, float(want["baseline"]["p_team_win"]))
            for sc in a["scenarios"]:
                assert "\"raw_" not in json.dumps({k: v for k, v in sc.items() if k != "evidence"})
                if ":absent:" in sc["scenario_id"]:
                    ev = sc["evidence"]
                    assert ev["shown_by_default"] is True and "raw_estimate" in ev["raw"]["effect_log_odds"]
            n += len(a["scenarios"])
    assert n == 280


def test_free_text_estimate_shows_shrunk_and_keeps_raw_only_in_evidence(rs):
    e = est("What if Cleveland were without Jarrett Allen?", G["191"], rs)
    eff = e["effects"][0]
    assert eff["type"] == "ESTIMATE"
    raw = eff["evidence"]["raw"]["effect_log_odds"]
    row = next(v for v in rs.absence.values() if v.get("player_name") == "J. Allen")
    assert raw["raw_estimate"] == row["effect_log_odds"]["raw_estimate"]
    shown = {k: v for k, v in eff.items() if k != "evidence"}
    assert '"raw_' not in json.dumps(shown) and '"raw_' not in json.dumps({k: v for k, v in e.items() if k != "effects"})


def test_stamp_rule_estimate_from_data_your_assumption_from_user_numbers(rs):
    """ESTIMATE when the number comes from data (preset or typed); YOUR ASSUMPTION when the user
    supplied the number; SAMPLE; NO NUMBER."""
    cases = {
        "What if Detroit were without Cade Cunningham?": ("197", "ESTIMATE"),           # Research's data, typed
        "What if the Lakers were on a back-to-back?": ("197", "ESTIMATE"),
        "What if Boston and Milwaukee played on a neutral floor?": ("200", "ESTIMATE"),  # Elo model recalculation
        "Assume it costs Boston 5%": ("200", "YOUR ASSUMPTION"),
        "What if the Lakers were priced at 30% on Polymarket?": ("197", "YOUR ASSUMPTION"),
        "What if Detroit were without Cade Cunningham and it costs them 3%?": ("197", "YOUR ASSUMPTION"),
        "Detroit without Nobody Atall": ("197", "NO NUMBER"),
        "assume it costs Boston 3 points": ("200", "NO NUMBER"),
    }
    for msg, (g, want) in cases.items():
        e = est(msg, G[g], rs)
        assert e["stamp"] == want, (msg, e["stamp"], [x["type"] for x in e["effects"]])
        if want == "ESTIMATE":
            assert e["scenario"] is not None
    # preset scenarios (GET /api/scenario) are Research's data: label ESTIMATE on every one
    assert {s["label"] for s in rs.api_answer(G["197"], G["197"]["home_team"], SHA)["scenarios"]} == {"ESTIMATE"}


def test_confirmation_survives_the_browser_json_round_trip():
    """Regression (8 Nov 02:50): the page echoes amount -5.0 as -5 (JavaScript JSON), which changed the
    interpretation id and gave 409 'confirmation revoked' for every whole-number assumption."""
    row = G["200"]
    it = parse_scenario("Assume it costs Boston 5%", row, SHA)
    assert it["changes"][0]["amount"] == -5.0
    browser = [{**it["changes"][0], "amount": -5}]  # JSON.stringify(-5.0) === "-5"
    assert json.dumps(browser).count('"amount": -5,') == 1
    req = {"confirmed": True, "changes": browser, "focus_team": it["focus_team"],
           "interpretation_id": it["interpretation_id"]}
    changes, focus = check_confirmation(req, row, SHA)
    assert focus == "Boston Celtics"
    edited = {**req, "changes": [{**req["changes"][0], "amount": -6}]}
    with pytest.raises(ConfirmationError):
        check_confirmation(edited, row, SHA)  # a real edit still revokes
