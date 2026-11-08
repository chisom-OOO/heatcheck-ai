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
    estimate_scenario,
    home_court_in_forecast,
    p_from_elo,
    parse_changes,
    parse_scenario,
    route,
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
    assert it["status"] == "NEEDS_CONFIRMATION" and it["label"] == "HYPOTHETICAL"
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
    d = bos["elo_home"] - bos["elo_away"] + 100
    assert c["scenario"]["p"] == round(1 - p_from_elo(d + 84), 4)
    huge = est("Assume it costs Boston 90%", bos)
    assert huge["scenario"] is None and any(x["check_id"] == "RANGE" for x in huge["challenger_checks"])


def test_stub_gives_no_number_for_player_out_and_rest():
    e = est("Cleveland without Donovan Mitchell", G["191"])
    assert e["scenario"] is None and e["effects"][0]["type"] == "NO_NUMBER"
    assert "Can't quantify this with the current model; it would need" in e["effects"][0]["text"]
    assert e["provider"]["version"] == "STUB" and e["verdict"] == VERDICT


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
    d = cle["elo_home"] - cle["elo_away"] + 100
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
    assert e["ref_text"].startswith(VERDICT) and e["label"] == "HYPOTHETICAL"
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
    assert entry["lane"] == "SCENARIO" and entry["label"] == "HYPOTHETICAL" and entry["changes"] == it["changes"]
    assert entry["interpretation_id"] == it["interpretation_id"] and entry["outcome"] is None
    # a new forecast file revokes the confirmation
    fc.write_bytes(FORECAST.read_bytes() + b"\n")
    code, e = post(base, "/api/scenario/estimate", body)
    assert code == 409 and "revoked" in e["error"]
    code, r = post(base, "/api/scenario", {"message": "what if they were on a neutral floor?"})
    assert r["status"] == "NEEDS_GAME"
    assert post(base, "/api/route", {"message": ""})[0] == 400
    assert post(base, "/api/scenario/estimate", {"game_id": "x"})[0] == 400
