"""Kalshi read-only parser: market metadata and order book -> heatcheck-records/1.

Shapes follow the vendor docs as read by the Experience build on 7 Nov 2026
(``GET /trade-api/v2/markets/{ticker}`` and ``.../orderbook`` returning ``orderbook_fp``
with ``yes_dollars``/``no_dollars`` bid ladders). Only authored payloads have been parsed.

Kalshi reports BIDS ONLY, for YES and for NO. A YES ask is the complement of the best NO
bid; that arithmetic is Research's normaliser, so this adapter stores each contract's own
bids as ``DIRECT`` and keeps the other ladder in the raw payload. The legacy integer-cent
``orderbook`` shape is refused rather than converted.
"""

from __future__ import annotations

from typing import Any

from heatcheck.contracts.records import sha256_hex
from heatcheck.markets.adapters.common import (
    AdapterError,
    Capture,
    envelope,
    level,
    load_payload,
    price,
    quote_record,
    refuse_summary_levels,
    require_outcome,
)

VENUE = "KALSHI"


def _market_obj(raw: bytes) -> dict[str, Any]:
    obj = load_payload(raw)
    m = obj.get("market") if isinstance(obj, dict) else None
    if not isinstance(m, dict):
        raise AdapterError("payload has no market object")
    return m


def rules_text(raw_market: bytes) -> str:
    m = _market_obj(raw_market)
    return "\n".join(x for x in (m.get("rules_primary"), m.get("rules_secondary")) if x)


def paused_reason(raw_market: bytes) -> str | None:
    status = _market_obj(raw_market).get("status")
    return None if status in ("active", "open") else f"market status is {status!r}"


def parse_market(raw: bytes, capture: Capture) -> dict:
    capture.checked()
    m = _market_obj(raw)
    ticker, event, title = m.get("ticker"), m.get("event_ticker"), m.get("title")
    yes_means = m.get("yes_sub_title")
    for name, value in (
        ("ticker", ticker),
        ("event_ticker", event),
        ("title", title),
        ("yes_sub_title", yes_means),
    ):
        if not isinstance(value, str) or not value:
            raise AdapterError(f"market payload lacks {name}")
    # ``no_sub_title`` names the same subject as YES (e.g. "Indiana"), not what NO means,
    # so the NO outcome is labelled plainly. Recorded 2026-11-07 capture confirms this.
    rules = rules_text(raw)
    tick = m.get("tick_size_dollars")
    ranges = m.get("price_ranges")
    if tick is None and isinstance(ranges, list) and len(ranges) == 1:
        tick = ranges[0].get("step") if isinstance(ranges[0], dict) else None
    sources = m.get("settlement_sources")
    source = None
    if isinstance(sources, list) and sources and isinstance(sources[0], dict):
        source = sources[0].get("name") or sources[0].get("url")
    return envelope(
        "VENUE_MARKET",
        f"{VENUE}:{ticker}",
        capture.data_mode,
        {
            "venue": VENUE,
            "venue_api_version": "kalshi-trade-api/v2",
            "event_id": event,
            "market_id": ticker,
            "title": title,
            "outcomes": [
                {"contract_id": f"{ticker}:yes", "label": f"YES ({yes_means})"},
                {"contract_id": f"{ticker}:no", "label": "NO"},
            ],
            "rules_text_sha256": sha256_hex(rules.encode("utf-8")) if rules else None,
            "settlement_source": source,
            "price_unit": "PROBABILITY_DOLLARS",
            "quantity_unit": "CONTRACTS",
            "tick_size": price(tick, "tick_size_dollars") if tick is not None else None,
            "source_snapshot_ids": [sha256_hex(raw)],
        },
    )


def parse_book(
    raw: bytes,
    capture: Capture,
    *,
    market: dict,
    contract_id: str,
    game_id: str,
    paused: str | None,
) -> dict:
    capture.checked()
    require_outcome(market, contract_id)
    obj = load_payload(raw)
    if not isinstance(obj, dict):
        raise AdapterError("orderbook payload is not an object")
    if "orderbook" in obj and "orderbook_fp" not in obj:
        raise AdapterError("legacy integer-cent orderbook; cents are refused, not converted")
    refuse_summary_levels(obj, ("orderbook_fp",))
    book = obj["orderbook_fp"]
    if not isinstance(book, dict):
        raise AdapterError("orderbook_fp is not an object")
    refuse_summary_levels(book, ("yes_dollars", "no_dollars"))
    key = "yes_dollars" if contract_id.endswith(":yes") else "no_dollars"
    rows = book.get(key) or []
    if not isinstance(rows, list):
        raise AdapterError(f"{key} must be a list")
    levels = []
    for i, row in enumerate(rows):
        where = f"{key}[{i}]"
        if not isinstance(row, list) or len(row) != 2:
            raise AdapterError(f"{where}: a level is [price, size]; got {row!r}")
        levels.append(level("BID", row[0], row[1], where))
    note = (
        "Kalshi reports bids only; no ask is stored. The complement of the other "
        "contract's bids stays in the raw payload for Research's normaliser."
        if levels
        else None
    )
    return quote_record(
        capture=capture,
        raw=raw,
        venue=VENUE,
        market=market,
        contract_id=contract_id,
        game_id=game_id,
        levels=levels,
        provider_time_utc=None,
        paused_reason=paused,
        note=note,
    )
