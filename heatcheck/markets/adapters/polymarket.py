"""Polymarket read-only parser: Gamma market metadata and CLOB book -> heatcheck-records/1.

Shapes follow the vendor docs as read by the Experience build on 7 Nov 2026 (Gamma
``GET /markets/slug/{slug}``, CLOB ``GET /book?token_id=...``). They have only been
exercised against authored payloads; verify against a real capture before gate G12.
Each outcome has its own token; the book is that token's own bids and asks.
"""

from __future__ import annotations

import json
from typing import Any

from heatcheck.contracts.records import sha256_hex
from heatcheck.markets.adapters.common import (
    AdapterError,
    Capture,
    envelope,
    level,
    load_payload,
    ms_to_utc,
    price,
    quote_record,
    refuse_summary_levels,
    require_outcome,
)

VENUE = "POLYMARKET"


def _json_list(value: Any, field: str) -> list[Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            raise AdapterError(f"{field} is not valid JSON") from None
    if not isinstance(value, list) or not value:
        raise AdapterError(f"{field} must be a non-empty list")
    return value


def _market_obj(raw: bytes) -> dict[str, Any]:
    m = load_payload(raw)
    if not isinstance(m, dict):
        raise AdapterError("market payload is not an object")
    return m


def rules_text(raw_market: bytes) -> str:
    return _market_obj(raw_market).get("description") or ""


def paused_reason(raw_market: bytes) -> str | None:
    m = _market_obj(raw_market)
    if m.get("active") and not m.get("closed") and m.get("acceptingOrders", True):
        return None
    return (
        f"market not open: active={m.get('active')!r} closed={m.get('closed')!r} "
        f"acceptingOrders={m.get('acceptingOrders')!r}"
    )


def parse_market(raw: bytes, capture: Capture) -> dict:
    capture.checked()
    m = _market_obj(raw)
    version = m.get("version") or ("v1" if m.get("clobTokenIds") else None)
    if version not in ("v1", "v2"):
        raise AdapterError(f"market version {version!r} is not supported")
    outcomes = _json_list(m.get("outcomes"), "outcomes")
    id_field = "positionIds" if version == "v2" else "clobTokenIds"
    tokens = _json_list(m.get(id_field), id_field)
    if len(outcomes) != len(tokens):
        raise AdapterError("outcomes and token ids are misaligned")
    if not all(isinstance(t, str) and t for t in tokens):
        raise AdapterError(f"{id_field} must be non-empty strings")
    events = m.get("events")
    event_id = events[0].get("id") if isinstance(events, list) and events else m.get("eventId")
    market_id = m.get("id")
    title = m.get("question") or m.get("title")
    for name, value in (("events[0].id", event_id), ("id", market_id), ("question", title)):
        if not isinstance(value, str) or not value:
            raise AdapterError(f"market payload lacks {name}")
    rules = m.get("description")
    tick = m.get("orderPriceMinTickSize")
    if isinstance(tick, (int, float)) and not isinstance(tick, bool):
        tick = repr(tick)
    return envelope(
        "VENUE_MARKET",
        f"{VENUE}:{market_id}",
        capture.data_mode,
        {
            "venue": VENUE,
            "venue_api_version": f"polymarket-gamma/{version}",
            "event_id": event_id,
            "market_id": market_id,
            "title": title,
            "outcomes": [
                {"contract_id": t, "label": str(o)} for o, t in zip(outcomes, tokens, strict=True)
            ],
            "rules_text_sha256": sha256_hex(rules.encode("utf-8")) if rules else None,
            "settlement_source": m.get("resolutionSource") or None,
            "price_unit": "PROBABILITY_DOLLARS",
            "quantity_unit": "SHARES",
            "tick_size": price(tick, "orderPriceMinTickSize") if tick is not None else None,
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
    b = load_payload(raw)
    if not isinstance(b, dict):
        raise AdapterError("book payload is not an object")
    refuse_summary_levels(b, ("bids", "asks"))
    # The book must say whose book it is; without asset_id another token's book would pass.
    if b.get("asset_id") != contract_id:
        raise AdapterError(f"book asset_id {b.get('asset_id')!r} is not {contract_id!r}")
    tick = market["body"]["tick_size"]
    levels = []
    for key, side in (("bids", "BID"), ("asks", "ASK")):
        rows = b.get(key)
        if not isinstance(rows, list):
            raise AdapterError(f"book {key} must be a list")
        for i, row in enumerate(rows):
            where = f"{key}[{i}]"
            if not isinstance(row, dict) or set(row) != {"price", "size"}:
                extra = sorted(set(row) - {"price", "size"}) if isinstance(row, dict) else row
                raise AdapterError(f"{where}: a level has only price and size; got {extra!r}")
            levels.append(level(side, row["price"], row["size"], where, tick=tick))
    sides = {lv["side"] for lv in levels}
    note = None
    if levels and sides != {"BID", "ASK"}:
        missing = ({"BID", "ASK"} - sides).pop()
        note = f"one-sided: venue reported no {missing} levels"
    return quote_record(
        capture=capture,
        raw=raw,
        venue=VENUE,
        market=market,
        contract_id=contract_id,
        game_id=game_id,
        levels=levels,
        provider_time_utc=ms_to_utc(b.get("timestamp"), "book timestamp"),
        paused_reason=paused,
        note=note,
    )
