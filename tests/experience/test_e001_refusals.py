"""E-001 A4: unit and semantics refusals. A refusal raises AdapterError and emits nothing;
an empty book becomes status EMPTY with a reason, never a zero price."""

from __future__ import annotations

import copy

import pytest

from heatcheck.contracts.records import validate_record
from heatcheck.markets.adapters import kalshi, polymarket
from heatcheck.markets.adapters.common import AdapterError, Capture, propose_mapping

CAP = Capture(
    source="test",
    fetch_start_utc="2026-11-07T16:00:00Z",
    received_utc="2026-11-07T16:00:00.100Z",
    data_mode="SYNTHETIC",
)
GAME = "syn:FIX-G0001"


@pytest.fixture
def pm(builder):
    market = polymarket.parse_market(builder.payload_bytes(builder.PM_MARKET), CAP)

    def book(payload, contract=builder.PM_TOKEN_HOME, cap=CAP):
        return polymarket.parse_book(
            builder.payload_bytes(payload), cap, market=market, contract_id=contract,
            game_id=GAME, paused=None,
        )

    return builder, market, book


@pytest.fixture
def ks(builder):
    market = kalshi.parse_market(builder.payload_bytes(builder.K_MARKET), CAP)
    yes = f"{builder.K_TICKER}:yes"

    def book(payload, contract=yes, cap=CAP):
        return kalshi.parse_book(
            builder.payload_bytes(payload), cap, market=market, contract_id=contract,
            game_id=GAME, paused=None,
        )

    return builder, market, book


def pm_book(builder, **changes):
    b = copy.deepcopy(builder.PM_BOOK)
    b.update(changes)
    return b


# ---------------------------------------------------------------- cents

def test_polymarket_price_in_cents_refused(pm):
    builder, _, book = pm
    with pytest.raises(AdapterError, match="cents are refused"):
        book(pm_book(builder, bids=[{"price": "53", "size": "10"}]))


def test_kalshi_price_in_cents_refused(ks):
    _, _, book = ks
    with pytest.raises(AdapterError, match="cents are refused"):
        book({"orderbook_fp": {"yes_dollars": [["53", "10.00"]], "no_dollars": []}})


def test_kalshi_legacy_integer_cent_book_refused(ks):
    _, _, book = ks
    with pytest.raises(AdapterError, match="cents are refused"):
        book({"orderbook": {"yes": [[52, 120]], "no": [[42, 80]]}})


def test_numeric_price_refused_as_unknown_unit(pm):
    builder, _, book = pm
    with pytest.raises(AdapterError, match="unit unknown"):
        book(pm_book(builder, bids=[{"price": 0.53, "size": "10"}]))


# ---------------------------------------------------------------- capture metadata

@pytest.mark.parametrize("venue", ["pm", "ks"])
def test_missing_received_utc_refused(request, venue):
    _, _, book = request.getfixturevalue(venue)
    builder = request.getfixturevalue("builder")
    payload = builder.PM_BOOK if venue == "pm" else builder.K_BOOK
    cap = Capture(source="test", fetch_start_utc=CAP.fetch_start_utc, received_utc=None,
                  data_mode="SYNTHETIC")
    with pytest.raises(AdapterError, match="missing received_utc"):
        book(payload, cap=cap)


def test_received_before_fetch_start_refused(pm):
    builder, _, book = pm
    cap = Capture(source="t", fetch_start_utc="2026-11-07T16:00:00.5Z",
                  received_utc="2026-11-07T16:00:00.25Z", data_mode="SYNTHETIC")
    with pytest.raises(AdapterError, match="before fetch_start"):
        book(builder.PM_BOOK, cap=cap)


# ---------------------------------------------------------------- outcome identity

@pytest.mark.parametrize("venue", ["pm", "ks"])
def test_outcome_absent_from_metadata_refused(request, venue):
    builder, _, book = request.getfixturevalue(venue)
    payload = builder.PM_BOOK if venue == "pm" else builder.K_BOOK
    with pytest.raises(AdapterError, match="not an outcome in the market metadata"):
        book(payload, contract="999999")


def test_book_for_another_token_refused(pm):
    builder, _, book = pm
    with pytest.raises(AdapterError, match="asset_id"):
        book(pm_book(builder, asset_id="111001"))


def test_mapping_refuses_label_mismatch(pm):
    builder, market, _ = pm
    rules = builder.PM_MARKET["description"]
    with pytest.raises(AdapterError, match="outcome order is never assumed"):
        propose_mapping(game_id=GAME, team_id="syn-team:BOS", market=market,
                        contract_id="111001", expected_label="Celtics", rules_text=rules)


# ---------------------------------------------------------------- midpoint / last trade

def test_polymarket_midpoint_level_refused(pm):
    builder, _, book = pm
    bad = [{"price": "0.55", "size": "0", "type": "midpoint"}]
    with pytest.raises(AdapterError, match="only price and size"):
        book(pm_book(builder, bids=bad))


def test_polymarket_midpoint_instead_of_levels_refused(pm):
    _, _, book = pm
    with pytest.raises(AdapterError, match="instead of levels"):
        book({"asset_id": "222002", "midpoint": "0.55"})


def test_kalshi_last_trade_instead_of_levels_refused(ks):
    _, _, book = ks
    with pytest.raises(AdapterError, match="instead of levels"):
        book({"orderbook_fp": {"last_trade_price": "0.55"}})
    with pytest.raises(AdapterError, match="instead of levels"):
        book({"midpoint": "0.55"})


def test_last_trade_field_beside_levels_is_not_stored(pm):
    builder, _, book = pm
    quote = book(builder.PM_BOOK)
    assert "0.55" not in {lv["price"] for lv in quote["body"]["levels"]}


# ---------------------------------------------------------------- empty, crossed, paused

def test_polymarket_empty_book_is_empty_status(pm):
    builder, _, book = pm
    quote = book(pm_book(builder, bids=[], asks=[]))
    validate_record(quote)
    assert quote["body"]["status"] == "EMPTY"
    assert quote["body"]["levels"] == []
    assert quote["body"]["status_reason"]


def test_kalshi_empty_book_is_empty_status(ks):
    _, _, book = ks
    quote = book({"orderbook_fp": {"yes_dollars": None, "no_dollars": []}})
    validate_record(quote)
    assert (quote["body"]["status"], quote["body"]["levels"]) == ("EMPTY", [])
    assert quote["body"]["status_reason"]


def test_zero_price_level_refused(pm):
    builder, _, book = pm
    with pytest.raises(AdapterError, match=r"outside \(0, 1\]"):
        book(pm_book(builder, bids=[{"price": "0", "size": "10"}]))


def test_crossed_book_is_error_not_ok(pm):
    builder, _, book = pm
    quote = book(pm_book(builder, bids=[{"price": "0.60", "size": "10"}],
                         asks=[{"price": "0.55", "size": "10"}]))
    validate_record(quote)
    assert quote["body"]["status"] == "ERROR"
    assert "crossed" in quote["body"]["status_reason"]


def test_paused_market_quote_is_paused(builder):
    raw_market = builder.payload_bytes({**builder.PM_MARKET, "closed": True})
    market = polymarket.parse_market(raw_market, CAP)
    quote = polymarket.parse_book(
        builder.payload_bytes(builder.PM_BOOK), CAP, market=market,
        contract_id=builder.PM_TOKEN_HOME, game_id=GAME,
        paused=polymarket.paused_reason(raw_market),
    )
    validate_record(quote)
    assert quote["body"]["status"] == "PAUSED"


def test_regulation_only_rules_read_as_such(ks):
    builder, market, _ = ks
    raw = copy.deepcopy(builder.K_MARKET)
    raw["market"]["rules_primary"] = "Resolves Yes if Boston lead at the end of regulation."
    raw["market"].pop("rules_secondary")
    market = kalshi.parse_market(builder.payload_bytes(raw), CAP)
    mapping = propose_mapping(
        game_id=GAME, team_id="syn-team:BOS", market=market,
        contract_id=f"{builder.K_TICKER}:yes", expected_label="YES (Boston Celtics)",
        rules_text=kalshi.rules_text(builder.payload_bytes(raw)),
    )
    validate_record(mapping)
    assert mapping["body"]["overtime_convention"] == "REGULATION_ONLY"
    assert mapping["body"]["cancel_postpone_convention"].startswith("UNKNOWN")
    assert mapping["body"]["status"] == "PROPOSED"
