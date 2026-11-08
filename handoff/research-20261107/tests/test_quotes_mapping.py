from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from heatcheck import quotes as Q
from heatcheck.mapping import ContractSpec, ForecastTarget, map_contract

T = ForecastTarget("0022300500", "2024-01-05", "BOS", "MIN", "BOS")
GOOD = ContractSpec("kalshi", "M1", "NBA", "2024-01-05", frozenset({"BOS", "MIN"}), "BOS", True, "VOID", "abc")


def test_kalshi_derived_yes_ask_fixture_research():
    b = Q.kalshi_yes_book(yes_bids=[("0.6000", 5)], no_bids=[("0.3700", 12)], unit="dollars")
    assert b.best_ask.price == Decimal("0.6300") and b.best_ask.size == Decimal(12)
    assert b.best_ask.derived_from == "kalshi:no_bid"


def test_kalshi_derived_yes_ask_fixture_pipeline():
    b = Q.kalshi_yes_book(yes_bids=[("0.55", 1)], no_bids=[("0.42", 3)], unit="dollars")
    assert b.best_ask.price == Decimal("0.58")


def test_cents_vs_dollars():
    a = Q.kalshi_yes_book([(60, 1)], [(37, 12)], unit="cents")
    b = Q.kalshi_yes_book([("0.60", 1)], [("0.37", 12)], unit="dollars")
    assert a.best_ask.price == b.best_ask.price == Decimal("0.63")
    with pytest.raises(Q.QuoteError, match="PRICE_OUT_OF_RANGE"):
        Q.kalshi_yes_book([("37", 1)], [], unit="dollars")   # cents integer misread as dollars
    with pytest.raises(Q.QuoteError, match="UNKNOWN_UNIT"):
        Q.to_prob("0.5", "basis_points")
    with pytest.raises(Q.QuoteError, match="FLOAT_PRICE_REJECTED"):
        Q.to_prob(0.5, "dollars")


def test_missing_side_gives_unavailable_never_zero():
    b = Q.kalshi_yes_book(yes_bids=[("0.60", 1)], no_bids=[], unit="dollars")
    assert b.best_ask is None and b.midpoint is None and b.status == "ONE_SIDED"
    c = Q.compare(0.6, b, "best_ask", mapping_status="MATCHED")
    assert c.status == "BLOCKED" and "BEST_ASK_UNAVAILABLE" in c.blocked_reasons


def test_crossed_book_omits_midpoint():
    b = Q.polymarket_book("tok", bids=[("0.60", 10)], asks=[("0.55", 10)])
    assert b.status == "CROSSED" and b.midpoint is None


def test_polymarket_synthetic_midpoint_example():
    b = Q.polymarket_book("tok", bids=[("0.52", 10), ("0.50", 5)], asks=[("0.56", 7), ("0.60", 3)])
    assert b.midpoint == Decimal("0.54") and b.spread == Decimal("0.04")
    c = Q.compare(0.59, b, "midpoint", mapping_status="MATCHED")
    assert c.status == "AVAILABLE" and c.quote_type == "midpoint"
    assert c.signed_probability_difference == pytest.approx(0.05, abs=1e-12)


def test_research_difference_fixture():
    b = Q.polymarket_book("tok", bids=[("0.50", 1)], asks=[("0.55", 1)])
    assert Q.compare(0.60, b, "best_ask", mapping_status="MATCHED").signed_probability_difference == pytest.approx(0.05)


def test_stale_and_future_quotes():
    cutoff = datetime(2024, 1, 5, 23, 0, tzinfo=timezone.utc)
    b = Q.polymarket_book("tok", [("0.5", 1)], [("0.52", 1)])
    obs = [(cutoff - timedelta(hours=3), b), (cutoff + timedelta(minutes=1), b)]
    t, bk, r = Q.eligible_quote(obs, cutoff, timedelta(minutes=30))
    assert r == ["STALE_QUOTE"] and t == cutoff - timedelta(hours=3)   # future quote ignored
    t, bk, r = Q.eligible_quote([(cutoff + timedelta(seconds=1), b)], cutoff, timedelta(minutes=30))
    assert bk is None and r == ["NO_QUOTE_AT_OR_BEFORE_CUTOFF"]


def test_mapping_matched():
    assert map_contract(T, GOOD).status == "MATCHED"


@pytest.mark.parametrize("change,reason", [
    (dict(yes_team="MIN"), "REVERSED_OUTCOME"),
    (dict(game_date_et="2024-03-10"), "DIFFERENT_GAME_DATE"),        # same teams, different date
    (dict(includes_overtime=False), "OVERTIME_MISMATCH"),            # regulation-only contract
    (dict(league="WNBA"), "LEAGUE_WNBA"),
    (dict(teams=frozenset({"BOS", "NYK"})), "TEAMS_DIFFER"),
])
def test_mapping_incompatible(change, reason):
    m = map_contract(T, ContractSpec(**{**GOOD.__dict__, **change}))
    assert m.status == "INCOMPATIBLE" and reason in m.reasons


def test_mapping_ambiguous_blocks_comparison():
    m = map_contract(T, ContractSpec(**{**GOOD.__dict__, "postponement_rule": None}))
    assert m.status == "AMBIGUOUS"
    b = Q.polymarket_book("tok", [("0.5", 1)], [("0.52", 1)])
    c = Q.compare(0.6, b, "best_ask", mapping_status=m.status)
    assert c.status == "BLOCKED" and c.signed_probability_difference is None
