"""Experience's own regression tests for the reviewer's RV-E findings on the E-001 adapters.

The reviewer's probes live in tests/review/ (their branch). These tests pin the boundaries
and the cases the probes do not cover: threshold edges, STALE records validating against
heatcheck-records/1, the NBA team table, and the overtime conflict rule.
"""

from __future__ import annotations

import copy
import importlib.util

import pytest
from conftest import ROOT

from heatcheck.contracts.records import validate_record
from heatcheck.markets.adapters import kalshi, polymarket
from heatcheck.markets.adapters.common import (
    NBA_TEAMS,
    AdapterError,
    Capture,
    overtime_convention,
    propose_mapping,
    team_tricode,
    teams_named,
)
from heatcheck.markets.adapters.live import check_request

_spec = importlib.util.spec_from_file_location(
    "make_e001_bundle", ROOT / "tests" / "experience" / "make_e001_bundle.py")
B = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(B)

RECEIVED = "2026-11-07T16:00:00.100Z"          # PM_BOOK timestamp is 16:00:00.050Z
CAP = Capture(source="t", fetch_start_utc="2026-11-07T16:00:00Z", received_utc=RECEIVED,
              data_mode="SYNTHETIC")


def raw(obj) -> bytes:
    return B.payload_bytes(obj)


def pm_book(cap=CAP, market_changes=None, **changes):
    mk = copy.deepcopy(B.PM_MARKET)
    mk.update(market_changes or {})
    market = polymarket.parse_market(raw(mk), cap)
    b = copy.deepcopy(B.PM_BOOK)
    b.update(changes)
    return polymarket.parse_book(raw(b), cap, market=market, contract_id=B.PM_TOKEN_HOME,
                                 game_id=B.GAME_ID, paused=None)


# ------------------------------------------------------------------ provider time bounds

@pytest.mark.parametrize("ms, status", [
    ("1794067205100", "OK"),       # 5.0 s after receipt: inside the skew allowance
    ("1794067140100", "OK"),       # exactly 60 s old: still OK
    ("1794067140099", "STALE"),    # 60.001 s old
    ("1793980800100", "STALE"),    # exactly 1 day old: stale, still plausible
])
def test_provider_time_boundaries(ms, status):
    q = pm_book(timestamp=ms)
    assert q["body"]["status"] == status
    validate_record(q)                          # STALE records are valid heatcheck-records/1
    if status == "STALE":
        assert "stale" in q["body"]["status_reason"]


@pytest.mark.parametrize("ms", ["1794067205101", "1793980800099"])
def test_provider_time_outside_plausible_range_refused(ms):
    with pytest.raises(AdapterError, match="provider time"):
        pm_book(timestamp=ms)


def test_paused_wins_over_stale_and_empty_wins_over_both():
    market = polymarket.parse_market(raw(B.PM_MARKET), CAP)
    old = copy.deepcopy(B.PM_BOOK)
    old["timestamp"] = "1794060000050"
    q = polymarket.parse_book(raw(old), CAP, market=market, contract_id=B.PM_TOKEN_HOME,
                              game_id=B.GAME_ID, paused="market not open")
    assert q["body"]["status"] == "PAUSED"
    old.update(bids=[], asks=[])
    q = polymarket.parse_book(raw(old), CAP, market=market, contract_id=B.PM_TOKEN_HOME,
                              game_id=B.GAME_ID, paused=None)
    assert q["body"]["status"] == "EMPTY"


def test_fetch_window_bound():
    ok = Capture(source="t", fetch_start_utc="2026-11-07T15:59:00.100Z", received_utc=RECEIVED,
                 data_mode="SYNTHETIC")
    assert ok.checked() is ok                   # exactly 60 s
    late = Capture(source="t", fetch_start_utc="2026-11-07T15:59:00.099Z",
                   received_utc=RECEIVED, data_mode="SYNTHETIC")
    with pytest.raises(AdapterError, match="fetch window"):
        late.checked()


# ------------------------------------------------------------------ tick and size

def test_tick_follows_the_market_metadata():
    q = pm_book(market_changes={"orderPriceMinTickSize": 0.001},
                bids=[{"price": "0.537", "size": "10"}])
    assert q["body"]["levels"][0]["price"] == "0.537"
    with pytest.raises(AdapterError, match="tick"):
        pm_book(bids=[{"price": "0.537", "size": "10"}])


def test_unknown_tick_refuses_levels_but_not_an_empty_book():
    with pytest.raises(AdapterError, match="tick size unknown"):
        pm_book(market_changes={"orderPriceMinTickSize": None})
    q = pm_book(market_changes={"orderPriceMinTickSize": None}, bids=[], asks=[])
    assert q["body"]["status"] == "EMPTY"


@pytest.mark.parametrize("size", ["0", "0.00", "0.0000"])
def test_zero_size_refused_in_any_spelling(size):
    with pytest.raises(AdapterError, match="zero"):
        pm_book(asks=[{"price": "0.55", "size": size}])
    bad = {"orderbook_fp": {"yes_dollars": [["0.51", size]], "no_dollars": []}}
    market = kalshi.parse_market(raw(B.K_MARKET), CAP)
    with pytest.raises(AdapterError, match="zero"):
        kalshi.parse_book(raw(bad), CAP, market=market, contract_id=f"{B.K_TICKER}:yes",
                          game_id=B.GAME_ID, paused=None)


# ------------------------------------------------------------------ team naming

def test_team_table_is_thirty_distinct_teams():
    assert len(NBA_TEAMS) == 30
    assert len({nba_id for nba_id, _ in NBA_TEAMS.values()}) == 30
    assert team_tricode("nba-team:1610612754") == "IND"     # the recorded DEN@IND capture
    assert team_tricode("nba-team:1610612743") == "DEN"
    assert team_tricode("syn-team:BOS") == "BOS"


@pytest.mark.parametrize("team_id", ["syn-team:XYZ", "nba-team:42", "team:BOS", "BOS", ""])
def test_unknown_team_id_refused(team_id):
    with pytest.raises(AdapterError, match="not a known NBA team"):
        team_tricode(team_id)


@pytest.mark.parametrize("label, named", [
    ("YES (Indiana)", {"IND"}),
    ("Pacers", {"IND"}),
    ("YES (Boston Celtics)", {"BOS"}),
    ("NO", set()),
    ("Los Angeles", set()),                     # ambiguous city names no team
    ("LA Clippers", {"LAC"}),
    ("Celtics vs Knicks", {"BOS", "NYK"}),
    ("Netsuke", set()),                         # whole words only
])
def test_teams_named(label, named):
    assert teams_named(label) == named


def test_label_naming_two_teams_refused():
    mk = copy.deepcopy(B.PM_MARKET)
    mk["outcomes"] = '["Knicks", "Celtics or Knicks"]'
    market = polymarket.parse_market(raw(mk), CAP)
    with pytest.raises(AdapterError, match="no other"):
        propose_mapping(game_id=B.GAME_ID, team_id="syn-team:BOS", market=market,
                        contract_id=B.PM_TOKEN_HOME, expected_label="Celtics or Knicks",
                        rules_text=B.PM_MARKET["description"])


def test_correct_mappings_still_propose():
    pm = polymarket.parse_market(raw(B.PM_MARKET), CAP)
    m = propose_mapping(game_id=B.GAME_ID, team_id="syn-team:BOS", market=pm,
                        contract_id=B.PM_TOKEN_HOME, expected_label="Celtics",
                        rules_text=B.PM_MARKET["description"])
    assert (m["body"]["status"], m["body"]["team_id"]) == ("PROPOSED", "syn-team:BOS")
    validate_record(m)


def _kalshi_market(ticker_suffix: str, yes_sub_title: str):
    mk = copy.deepcopy(B.K_MARKET)
    ticker = mk["market"]["ticker"].rsplit("-", 1)[0] + "-" + ticker_suffix
    mk["market"].update(ticker=ticker, yes_sub_title=yes_sub_title)
    return kalshi.parse_market(raw(mk), CAP), ticker, kalshi.rules_text(raw(mk))


def test_kalshi_ticker_team_code_must_be_the_mapped_team():
    # Label names Boston but the ticker is the Knicks' market: refused on the id.
    market, ticker, rules = _kalshi_market("NYK", "Boston Celtics")
    with pytest.raises(AdapterError, match="ticker .* is for NYK"):
        propose_mapping(game_id=B.GAME_ID, team_id="syn-team:BOS", market=market,
                        contract_id=f"{ticker}:yes", expected_label="YES (Boston Celtics)",
                        rules_text=rules)
    # Consistent ticker, label and team id: proposed.
    market, ticker, rules = _kalshi_market("BOS", "Boston Celtics")
    m = propose_mapping(game_id=B.GAME_ID, team_id="syn-team:BOS", market=market,
                        contract_id=f"{ticker}:yes", expected_label="YES (Boston Celtics)",
                        rules_text=rules)
    assert m["body"]["status"] == "PROPOSED"


def test_kalshi_no_contract_refused_even_with_matching_ticker():
    market, ticker, rules = _kalshi_market("BOS", "Boston Celtics")
    with pytest.raises(AdapterError, match="names no team"):
        propose_mapping(game_id=B.GAME_ID, team_id="syn-team:BOS", market=market,
                        contract_id=f"{ticker}:no", expected_label="NO", rules_text=rules)


@pytest.mark.parametrize("ts, msg", [
    ("1794067200", "epoch seconds, not milliseconds"),
    ("1794067200050000", "not epoch milliseconds"),      # microseconds
    ("179406720005", "not epoch milliseconds"),
    ("１７９４０６７２０００５０", "not epoch milliseconds"),   # full-width digits
])
def test_timestamp_unit_refused_with_reason(ts, msg):
    with pytest.raises(AdapterError, match=msg):
        pm_book(timestamp=ts)


# ------------------------------------------------------------------ overtime

@pytest.mark.parametrize("text, expected", [
    ("Resolves Yes if Boston lead at the end of regulation.", "REGULATION_ONLY"),
    ("If tied at the end of regulation, the game goes to overtime.", "UNKNOWN"),
    ("Not including overtime.", "REGULATION_ONLY"),
    ("The market does not include any overtime.", "REGULATION_ONLY"),
    ("Final score including overtime.", "INCLUDES_OVERTIME"),
    ("Regulation time only. Final score including any overtime.", "UNKNOWN"),   # conflict
])
def test_overtime_reading_edges(text, expected):
    assert overtime_convention(text) == expected


# ------------------------------------------------------------------ allowlist

@pytest.mark.parametrize("url", [
    "https://gamma-api.polymarket.com/markets/slug/nba-den-ind-2026-11-07",
    "https://gamma-api.polymarket.com/markets?slug=nba-den-ind-2026-11-07",
    "https://gamma-api.polymarket.com/events?tag=nba",
    "https://clob.polymarket.com/book?token_id=1001",
    "https://api.elections.kalshi.com/trade-api/v2/markets/KXNBAGAME-26NOV07DENIND-IND",
    "https://api.elections.kalshi.com/trade-api/v2/markets/KXNBAGAME-26NOV07DENIND-IND/orderbook",
    "https://api.elections.kalshi.com/trade-api/v2/markets?event_ticker=KXNBAGAME-26NOV07DENIND",
    "https://api.elections.kalshi.com/trade-api/v2/events/KXNBAGAME-26NOV07DENIND",
])
def test_public_reads_still_allowed(url):
    assert check_request("GET", url)


@pytest.mark.parametrize("url", [
    "https://clob.polymarket.com/book/",
    "https://clob.polymarket.com/books",
    "https://gamma-api.polymarket.com/markets/slug/a/b",
    "https://gamma-api.polymarket.com/markets/slug/..",
    "https://gamma-api.polymarket.com/markets/slug/a%2F..",
    "https://api.elections.kalshi.com/trade-api/v2/markets/X/orderbook/extra",
    "https://api.elections.kalshi.com/trade-api/v2/markets/./orderbook",
    "https://api.elections.kalshi.com/trade-api/v2/portfolio/balance",
])
def test_near_miss_paths_refused(url):
    with pytest.raises(AdapterError, match="allowlisted"):
        check_request("GET", url)
