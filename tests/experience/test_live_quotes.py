"""Live quotes for a heatcheck-live-forecast/1 file: format rules, strict matching, offline replay.

The fake client serves the response bodies recorded by the live run of 2026-11-07T22:29:50Z
(``data/experience/quotes/20261107T222950Z``), so no test touches the network. Mutated copies
of those bodies exercise each rejection.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from conftest import ROOT

from heatcheck.contracts import bundle
from heatcheck.markets import live_quotes as lq
from heatcheck.markets.adapters import capture

RUN = ROOT / "data" / "experience" / "quotes" / "20261107T222950Z"
SAMPLE = ROOT / "tests" / "fixtures" / "live" / "forecasts.SAMPLE.json"
SUMMARY = json.loads((RUN / "quotes.json").read_text(encoding="utf-8"))
GAMMA = "https://gamma-api.polymarket.com/markets/slug/"
KALSHI = "https://api.elections.kalshi.com/trade-api/v2/"


class FakeClient:
    """URL -> recorded (status, body, fetch_start, received); unknown URLs answer 404."""

    def __init__(self):
        self.routes = {}
        for r in SUMMARY["requests"]:
            body = (RUN / "raw" / f"{r['payload_sha256']}.json").read_bytes()
            self.routes[r["source"][4:]] = (r["http_status"], body, r["fetch_start_utc"],
                                           r["received_utc"])
        self.calls: list[str] = []

    def get(self, url):
        self.calls.append(url)
        first = SUMMARY["requests"][0]
        return self.routes.get(url, (404, b'{"error":"not found"}', first["fetch_start_utc"],
                                     first["received_utc"]))

    def mutate(self, url, fn):
        status, body, start, received = self.routes[url]
        obj = json.loads(body)
        fn(obj)
        self.routes[url] = (status, json.dumps(obj).encode(), start, received)


def sample():
    return json.loads(SAMPLE.read_text(encoding="utf-8"))


def write(tmp_path, doc):
    p = tmp_path / "forecasts.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


@pytest.fixture
def fixed_clock(monkeypatch):
    monkeypatch.setattr(lq, "utc_now", lambda: "2026-11-07T22:29:58.548346Z")


def statuses(summary):
    return {(g["game_id"], v["venue"]): v["status"] for g in summary["games"] for v in g["venues"]}


# ---------------------------------------------------------------- format rules


def test_sample_file_is_valid_and_labelled_sample():
    doc = sample()
    assert lq.validate_forecast(doc) == []
    assert lq.is_sample(doc)
    assert "SAMPLE" in doc["source"]["results"]


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda d: d.update(format="heatcheck-live-forecast/2"), "format is"),
        (lambda d: d.update(data_cutoff_utc="2026-11-08T00:30:00Z"), "not before tip_utc"),
        (lambda d: d.update(data_cutoff_utc="2026-11-07T22:00:00+00:00"), "ending in Z"),
        (lambda d: d["games"][0].update(tip_utc="2026-11-08 00:30:00"), "ending in Z"),
        (lambda d: d["games"][0].update(p_home_win=1.2), "probability in [0, 1]"),
        (lambda d: d["games"][0].update(p_home_win=True), "probability in [0, 1]"),
        (lambda d: d["games"][0].update(p_home_win=float("nan")), "probability in [0, 1]"),
        (lambda d: d["games"][0].update(home_team_id="nba-team:1"), "not a known nba-team"),
        (lambda d: d["games"][0].update(home_team_id="syn-team:ATL"), "not a known nba-team"),
        (lambda d: d["games"][0].update(home_team="Brooklyn Nets"), "does not name ATL"),
        (lambda d: d["games"][0].update(game_id="nba:22600190"), "10-digit"),
        (lambda d: d["games"][1].update(game_id=d["games"][0]["game_id"]), "repeated"),
        (lambda d: d["games"][0].update(away_team_id=d["games"][0]["home_team_id"],
                                        away_team="Atlanta Hawks"), "same team"),
        (lambda d: d["backtest_2024_25"].update(brier=1.5), "brier"),
        (lambda d: d.update(games=[]), "non-empty list"),
    ],
)
def test_format_rules_are_enforced(change, message):
    doc = sample()
    change(doc)
    assert any(message in e for e in lq.validate_forecast(doc)), lq.validate_forecast(doc)


def test_a_real_file_needs_a_real_hash_and_fetch_time():
    doc = sample()
    doc["source"] = {"results": "cdn.nba.com schedule JSON", "fetched_utc": "today",
                     "sha256": "abc", "cross_check": "NOT_RUN"}
    errs = lq.validate_forecast(doc)
    assert not lq.is_sample(doc)
    assert any("fetched_utc" in e for e in errs) and any("64 lowercase hex" in e for e in errs)


# ---------------------------------------------------------------- derived identifiers


@pytest.mark.parametrize(
    ("utc", "local"),
    [
        ("2026-11-08T00:30:00Z", "2026-11-07"),  # EST: 19:30 on the 7th
        ("2026-11-08T04:59:00Z", "2026-11-07"),
        ("2026-11-08T05:00:00Z", "2026-11-08"),
        ("2026-04-15T03:30:00Z", "2026-04-14"),  # EDT: 23:30 on the 14th
        ("2026-04-15T04:00:00Z", "2026-04-15"),
        ("2026-03-08T06:59:00Z", "2026-03-08"),  # 01:59 EST, before DST starts at 07:00Z
        ("2026-11-01T05:30:00Z", "2026-11-01"),  # 01:30 EDT, before DST ends at 06:00Z
    ],
)
def test_us_eastern_date(utc, local):
    assert lq.us_eastern_date(lq.parse_utc(utc)).isoformat() == local


def test_slug_and_ticker_match_the_earlier_recorded_game():
    ref = lq.game_ref({"game_id": "nba:0022600189", "tip_utc": "2026-11-07T22:00:00Z",
                       "home_team_id": "nba-team:1610612754",
                       "away_team_id": "nba-team:1610612743"})
    assert lq.polymarket_slug(ref) == "nba-den-ind-2026-11-07"
    assert lq.kalshi_event_ticker(ref) == "KXNBAGAME-26NOV07DENIND"


# ---------------------------------------------------------------- offline replay of the live run


def test_replay_of_the_live_run_reproduces_every_match(tmp_path, no_network, fixed_clock):
    client = FakeClient()
    s = lq.run(SAMPLE, tmp_path / "out", client)
    assert s["counts"] == {"MATCHED": 12}
    assert statuses(s) == statuses(SUMMARY)
    keep = ("label", "contract_id", "best_bid", "best_ask", "received_utc", "quote_status")
    for got, want in zip(s["games"], SUMMARY["games"], strict=True):
        for gv, wv in zip(got["venues"], want["venues"], strict=True):
            assert {k: gv[k] for k in keep} == {k: wv[k] for k in keep}
    assert all(u.startswith("https://") for u in client.calls)


def test_committed_run_is_labelled_sample_and_carries_no_forecast_value():
    keys: set[str] = set()

    def walk(o):
        if isinstance(o, dict):
            keys.update(o)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(SUMMARY)
    assert SUMMARY["forecast_input"]["is_sample"] is True
    assert "SAMPLE" in SUMMARY["label"] and SUMMARY["sample_warning"].startswith("SAMPLE")
    assert not keys & {"p_home_win", "elo_home", "elo_away", "backtest_2024_25", "model"}
    for g in SUMMARY["games"]:
        for v in g["venues"]:
            assert v["status"] == "MATCHED" and v["team_id"] == g["home_team_id"]
            assert v["received_before_tip"] is True
            assert lq.parse_utc(v["received_utc"]) < lq.parse_utc(g["tip_utc"])
            m, _ = bundle.load_bundle(RUN / v["bundle"])
            assert "SAMPLE INPUT" in m["notes"] and m["data_modes"] == ["RECORDED_MARKET"]


@pytest.mark.parametrize("name", sorted(p.name for p in RUN.iterdir() if p.is_dir()
                                        and p.name != "raw"))
def test_committed_bundles_rebuild_byte_identically(name, no_network):
    b = RUN / name
    manifest, records = bundle.load_bundle(b)
    m2, body, raw = capture.build(b, lq.RIGHTS_NOTE, manifest["notes"], manifest["created_utc"])
    assert m2 == manifest and (b / "records.jsonl").read_bytes() == body
    assert all((b / rel).read_bytes() == data for rel, data in raw.items())


# ---------------------------------------------------------------- rejections


def one_game(index=0):
    doc = sample()
    doc["games"] = [doc["games"][index]]
    return doc


PM_ATL = f"{GAMMA}nba-bkn-atl-2026-11-07"
KX_ATL = f"{KALSHI}markets/KXNBAGAME-26NOV07BKNATL-ATL"
KX_EV = f"{KALSHI}events/KXNBAGAME-26NOV07BKNATL"


@pytest.mark.parametrize(
    ("url", "fn", "venue", "reason"),
    [
        (PM_ATL, lambda m: m.update(gameStartTime="2026-11-08 01:30:00+00"), "POLYMARKET",
         "is not the tip"),
        (PM_ATL, lambda m: m.pop("gameStartTime"), "POLYMARKET", "missing or not a UTC time"),
        (PM_ATL, lambda m: m.update(outcomes='["Nets", "Celtics"]'), "POLYMARKET",
         "not one ATL outcome"),
        (PM_ATL, lambda m: m.update(outcomes='["Nets", "Hawks", "Draw"]'), "POLYMARKET",
         "not one ATL outcome"),
        (PM_ATL, lambda m: m.update(question="Nets vs. Celtics"), "POLYMARKET",
         "does not name exactly"),
        (PM_ATL, lambda m: m.update(sportsMarketType="spreads"), "POLYMARKET", "moneyline"),
        (PM_ATL, lambda m: m.update(closed=True), "POLYMARKET", "market not open"),
        (KX_ATL, lambda m: m["market"].update(yes_sub_title="Brooklyn"), "KALSHI",
         "does not name ATL alone"),
        (KX_ATL, lambda m: m["market"].update(status="closed"), "KALSHI", "is not open"),
        (KX_ATL, lambda m: m["market"].update(expected_expiration_time="2026-11-09T03:00:00Z"),
         "KALSHI", "is not within"),
        (KX_ATL, lambda m: m["market"].update(expected_expiration_time="2026-11-08T00:00:00Z"),
         "KALSHI", "is not within"),
        (KX_EV, lambda e: e["event"].update(title="Brooklyn at Boston"), "KALSHI",
         "does not name exactly"),
    ],
)
def test_uncertain_candidates_are_rejected(tmp_path, no_network, fixed_clock, url, fn, venue,
                                           reason):
    client = FakeClient()
    client.mutate(url, fn)
    s = lq.run(write(tmp_path, one_game()), tmp_path / "out", client)
    (v,) = [v for v in s["games"][0]["venues"] if v["venue"] == venue]
    assert v["status"] == "REJECTED" and reason in v["reason"], v
    assert "book_get" not in v  # no book is fetched for a rejected market
    assert not list((tmp_path / "out").glob(f"*-{'pm' if venue == 'POLYMARKET' else 'kx'}-*"))
    (other,) = [o for o in s["games"][0]["venues"] if o["venue"] != venue]
    assert other["status"] == "MATCHED"


def test_swapped_home_and_away_finds_nothing(tmp_path, no_network, fixed_clock):
    doc = one_game()
    g = doc["games"][0]
    g["home_team_id"], g["away_team_id"] = g["away_team_id"], g["home_team_id"]
    g["home_team"], g["away_team"] = g["away_team"], g["home_team"]
    s = lq.run(write(tmp_path, doc), tmp_path / "out", FakeClient())
    assert {v["status"] for v in s["games"][0]["venues"]} == {"NOT_FOUND"}
    assert "nba-atl-bkn-2026-11-07" in s["games"][0]["venues"][0]["reason"]


def test_wrong_date_finds_nothing(tmp_path, no_network, fixed_clock):
    doc = one_game()
    doc["games"][0]["tip_utc"] = "2026-11-09T00:30:00Z"
    s = lq.run(write(tmp_path, doc), tmp_path / "out", FakeClient())
    assert {v["status"] for v in s["games"][0]["venues"]} == {"NOT_FOUND"}


def test_slug_found_but_tip_differs_is_rejected_not_matched(tmp_path, no_network, fixed_clock):
    doc = one_game()
    doc["games"][0]["tip_utc"] = "2026-11-08T01:00:00Z"  # same date and teams, other tip
    s = lq.run(write(tmp_path, doc), tmp_path / "out", FakeClient())
    pm, kx = s["games"][0]["venues"]
    assert pm["status"] == "REJECTED" and "is not the tip" in pm["reason"]
    assert kx["status"] == "MATCHED"  # expiry 03:30Z is within 6 h after 01:00Z


def test_network_failure_is_an_error_not_a_quote(tmp_path, no_network, fixed_clock):
    class Down(FakeClient):
        def get(self, url):
            raise lq.AdapterError("network error: down")

    s = lq.run(write(tmp_path, one_game()), tmp_path / "out", Down())
    assert {v["status"] for v in s["games"][0]["venues"]} == {"ERROR"}


def test_invalid_forecast_is_refused_before_any_request(tmp_path, no_network):
    doc = sample()
    doc["data_cutoff_utc"] = "2026-11-08T03:00:00Z"
    client = FakeClient()
    with pytest.raises(lq.AdapterError, match="not before tip_utc"):
        lq.run(write(tmp_path, doc), tmp_path / "out", client)
    assert client.calls == []


def test_run_times_are_utc_z():
    for g in SUMMARY["games"]:
        for v in g["venues"]:
            for k in ("received_utc", "fetch_start_utc"):
                assert lq.parse_utc(v[k]).tzinfo == UTC
    assert lq.parse_utc(SUMMARY["run_finished_utc"]) > datetime(2026, 11, 7, 22, tzinfo=UTC)
