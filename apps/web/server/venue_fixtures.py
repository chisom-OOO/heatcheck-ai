"""AUTHORED SYNTHETIC venue payloads (not captures of real markets).

Shapes follow the vendor docs read on 7 Nov 2026. Tickers/slugs contain 'FIX'/'fixture' so they
cannot be mistaken for real listings. data_mode of everything built from these is SYNTHETIC.
Each scenario exercises one market-semantics case from DATA_PIPELINE.md section 5.
"""
import copy

from .venues import KALSHI_BASE, FixtureTransport, PolymarketAdapter

GAME = {"game_id": "FIX-G0001", "home_team": "BOS", "away_team": "NYK",
        "scheduled_tip_utc": "2026-11-08T00:30:00+00:00", "season": "fixture", "data_mode": "SYNTHETIC"}
FORECAST = {"forecast_id": "FIX-F0001", "game_id": GAME["game_id"], "team": "BOS",
            "probability": 0.59, "cutoff_utc": "2026-11-08T00:00:00+00:00",
            "model": "fixture-forecast-0", "evidence_hash": "fixture-no-evidence",
            "calibration_scope": "none: authored fixture, not a model output",
            "data_mode": "SYNTHETIC"}

K_TICKER = "KXNBAGAME-FIX26NOV08NYKBOS-BOS"
PM_SLUG = "fixture-nba-nyk-bos-2026-11-08"

_K_MARKET = {"market": {
    "ticker": K_TICKER, "event_ticker": "KXNBAGAME-FIX26NOV08NYKBOS",
    "title": "New York Knicks at Boston Celtics: Winner?", "yes_sub_title": "Boston Celtics",
    "rules_primary": "If the Boston Celtics win the New York Knicks vs Boston Celtics game scheduled for "
                     "Nov 8, 2026, including any overtime, then the market resolves to Yes.",
    "rules_secondary": "If the game is postponed, the market remains open until the rescheduled game is played. "
                       "If the game is cancelled, the market resolves per the exchange's cancellation rules.",
    "occurrence_datetime": "2026-11-08T00:30:00Z", "status": "active", "tick_size_dollars": "0.01"}}
_K_BOOK = {"orderbook_fp": {"yes_dollars": [["0.5100", "300.00"], ["0.5200", "120.00"]],
                            "no_dollars": [["0.4000", "200.00"], ["0.4200", "80.00"]]},
           "_provider_time": "2026-11-07T23:58:00Z"}

_PM_MARKET = {
    "id": "fixture-pm-1", "version": "v2", "question": "Knicks vs. Celtics",
    "outcomes": "[\"Knicks\", \"Celtics\"]", "clobTokenIds": None, "positionIds": ["111001", "222002"],
    "gameStartTime": "2026-11-08 00:30:00+00", "endDateIso": "2026-11-08",
    "description": "This market resolves to the team that wins the game, including any overtime. "
                   "If the game is postponed, the market stays open until it is played; if cancelled, it resolves 50-50.",
    "orderPriceMinTickSize": 0.01, "active": True, "closed": False, "acceptingOrders": True}
_PM_BOOK = {"market": "0xfixture", "asset_id": "222002", "timestamp": "1794095940000", "hash": "fixture",
            "bids": [{"price": "0.52", "size": "900"}, {"price": "0.53", "size": "410"}],
            "asks": [{"price": "0.58", "size": "700"}, {"price": "0.57", "size": "350"}],
            "tick_size": "0.01", "min_order_size": "5"}

K_MKT_URL = f"{KALSHI_BASE}/markets/{K_TICKER}"
K_BOOK_URL = f"{KALSHI_BASE}/markets/{K_TICKER}/orderbook"
PM_MKT_URL = f"{PolymarketAdapter.GAMMA}/markets/slug/{PM_SLUG}"
PM_BOOK_URL = f"{PolymarketAdapter.CLOB}/book?token_id=222002"


def _k(market=None, book=None):
    m, b = copy.deepcopy(_K_MARKET), copy.deepcopy(_K_BOOK)
    if market:
        m["market"].update(market)
    if book is not None:
        b = book
    return {K_MKT_URL: m, K_BOOK_URL: b}


def _pm(market=None, book=None):
    m, b = copy.deepcopy(_PM_MARKET), copy.deepcopy(_PM_BOOK)
    if market:
        m.update(market)
    if book is not None:
        b = book
    return {PM_MKT_URL: m, PM_BOOK_URL: b}


SCENARIOS = {
    "kalshi_ok": ("kalshi", K_TICKER, lambda: _k(), "matched contract; YES ask derived from NO bid"),
    "polymarket_ok": ("polymarket", PM_SLUG, lambda: _pm(), "matched; outcome order is [away, home], not YES-first"),
    "kalshi_reversed_outcome": ("kalshi", K_TICKER, lambda: _k({"yes_sub_title": "New York Knicks"}),
                                "YES means the other team"),
    "kalshi_other_date": ("kalshi", K_TICKER, lambda: _k({"occurrence_datetime": "2026-12-25T17:00:00Z"}),
                          "same teams, different game date"),
    "kalshi_regulation_only": ("kalshi", K_TICKER, lambda: _k({"rules_primary":
                               "Resolves Yes if the Boston Celtics lead the New York Knicks at the end of regulation."}),
                               "contract excludes overtime"),
    "kalshi_cents_legacy": ("kalshi", K_TICKER, lambda: _k(book={"orderbook": {"yes": [[52, 120], [51, 300]],
                            "no": [[42, 80], [40, 200]]}, "_provider_time": "2026-11-07T23:58:00Z"}),
                            "legacy integer-cent levels converted explicitly"),
    "kalshi_unknown_units": ("kalshi", K_TICKER, lambda: _k(book={"levels": [[0.5, 1]]}), "unrecognised book shape"),
    "kalshi_stale_book": ("kalshi", K_TICKER, lambda: _k(book={**copy.deepcopy(_K_BOOK), "_provider_time": "2026-11-07T21:00:00Z"}),
                          "book observed 3h before cutoff"),
    "kalshi_after_cutoff": ("kalshi", K_TICKER, lambda: _k(book={**copy.deepcopy(_K_BOOK), "_provider_time": "2026-11-08T00:05:00Z"}),
                            "quote observed after the forecast cutoff"),
    "kalshi_paused": ("kalshi", K_TICKER, lambda: _k({"status": "closed"}), "market not open"),
    "polymarket_missing_ask": ("polymarket", PM_SLUG, lambda: _pm(book={**copy.deepcopy(_PM_BOOK), "asks": []}),
                               "no ask side"),
    "polymarket_crossed": ("polymarket", PM_SLUG, lambda: _pm(book={**copy.deepcopy(_PM_BOOK),
                           "bids": [{"price": "0.60", "size": "10"}], "asks": [{"price": "0.55", "size": "10"}]}),
                           "crossed book"),
    "polymarket_rate_limited": ("polymarket", PM_SLUG, lambda: {**_pm(), PM_BOOK_URL: (429, {"Retry-After": "0"}, b"{}")},
                                "venue keeps returning 429"),
    "polymarket_no_listing": ("polymarket", PM_SLUG, lambda: {}, "market slug not found (absent listing)"),
}


def transport(name):
    if name not in SCENARIOS:
        raise KeyError(name)
    return FixtureTransport(SCENARIOS[name][2](), data_mode="SYNTHETIC", captured_at=None)


def scenario_list():
    return [{"id": k, "venue": v[0], "ref": v[1], "description": v[3]} for k, v in SCENARIOS.items()]
