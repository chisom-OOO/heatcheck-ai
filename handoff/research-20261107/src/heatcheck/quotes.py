"""Pure venue-quote normalisation and descriptive comparison (Research §09/§10).

Prices are Decimal in a declared unit; converted exactly once to probability-unit Decimal.
Nothing here fetches data, ranks opportunities, or computes profit.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

ONE = Decimal(1)
UNITS = {"dollars": Decimal(1), "cents": Decimal("0.01"), "probability": Decimal(1)}


class QuoteError(ValueError):
    pass


def to_prob(raw: str | int, unit: str) -> Decimal:
    if unit not in UNITS:
        raise QuoteError(f"UNKNOWN_UNIT:{unit}")
    if isinstance(raw, float):
        raise QuoteError("FLOAT_PRICE_REJECTED: pass the provider string/int")
    try:
        v = Decimal(str(raw)) * UNITS[unit]
    except InvalidOperation as e:
        raise QuoteError(f"UNPARSEABLE_PRICE:{raw!r}") from e
    if not v.is_finite() or v < 0 or v > 1:
        raise QuoteError(f"PRICE_OUT_OF_RANGE:{v}")
    return v


@dataclass(frozen=True)
class Level:
    price: Decimal      # probability units
    size: Decimal | None
    derived_from: str | None = None   # e.g. "kalshi:no_bid"


@dataclass
class NormalizedBook:
    venue: str
    contract: str          # e.g. "YES" or outcome token id
    best_bid: Level | None
    best_ask: Level | None
    midpoint: Decimal | None
    spread: Decimal | None
    status: str
    reasons: list[str] = field(default_factory=list)


def _finish(venue, contract, bid, ask, reasons) -> NormalizedBook:
    status = "OK"; mid = spread = None
    if bid and ask:
        if bid.price > ask.price:
            reasons.append("CROSSED_BOOK"); status = "CROSSED"
        else:
            mid = (bid.price + ask.price) / 2; spread = ask.price - bid.price
    else:
        reasons.append("MISSING_SIDE"); status = "ONE_SIDED" if (bid or ask) else "EMPTY"
    return NormalizedBook(venue, contract, bid, ask, mid, spread, status, reasons)


def kalshi_yes_book(yes_bids: list[tuple], no_bids: list[tuple], unit: str) -> NormalizedBook:
    """Kalshi binary book lists bids for YES and NO. YES ask = 1 − best NO bid at that NO-bid size."""
    yb = [Level(to_prob(p, unit), Decimal(str(q))) for p, q in yes_bids]
    nb = [Level(to_prob(p, unit), Decimal(str(q))) for p, q in no_bids]
    best_yes_bid = max(yb, key=lambda l: l.price) if yb else None
    best_no_bid = max(nb, key=lambda l: l.price) if nb else None
    ask = Level(ONE - best_no_bid.price, best_no_bid.size, "kalshi:no_bid") if best_no_bid else None
    return _finish("kalshi", "YES", best_yes_bid, ask, [])


def polymarket_book(token_id: str, bids: list[tuple], asks: list[tuple]) -> NormalizedBook:
    """Polymarket CLOB book for ONE outcome token; prices already in probability units (strings)."""
    b = [Level(to_prob(p, "probability"), Decimal(str(q))) for p, q in bids]
    a = [Level(to_prob(p, "probability"), Decimal(str(q))) for p, q in asks]
    return _finish("polymarket", token_id, max(b, key=lambda l: l.price) if b else None,
                   min(a, key=lambda l: l.price) if a else None, [])


@dataclass
class Comparison:
    status: str
    quote_type: str | None
    forecast_probability: float | None
    observed_quote: Decimal | None
    signed_probability_difference: float | None
    blocked_reasons: list[str]


def eligible_quote(observations: list[tuple[datetime, NormalizedBook]], cutoff: datetime,
                   max_age: timedelta) -> tuple[datetime | None, NormalizedBook | None, list[str]]:
    """Latest observation received at or before cutoff; stale/future/absent get explicit reasons."""
    past = [(t, b) for t, b in observations if t <= cutoff]
    if not past:
        return None, None, ["NO_QUOTE_AT_OR_BEFORE_CUTOFF" if observations else "NO_QUOTE"]
    t, b = max(past, key=lambda x: x[0])
    if cutoff - t > max_age:
        return t, b, ["STALE_QUOTE"]
    return t, b, []


def compare(forecast_p: float, book: NormalizedBook | None, quote_type: str, *,
            mapping_status: str, extra_reasons: list[str] | None = None) -> Comparison:
    reasons = list(extra_reasons or [])
    if mapping_status != "MATCHED":
        reasons.append(f"MAPPING_{mapping_status}")
    if not (isinstance(forecast_p, float) and 0.0 <= forecast_p <= 1.0):
        reasons.append("INVALID_FORECAST")
    q = None
    if book is None:
        reasons.append("NO_BOOK")
    else:
        q = {"best_ask": book.best_ask.price if book.best_ask else None,
             "best_bid": book.best_bid.price if book.best_bid else None,
             "midpoint": book.midpoint}.get(quote_type, "UNKNOWN")
        if q == "UNKNOWN":
            reasons.append(f"UNKNOWN_QUOTE_TYPE:{quote_type}"); q = None
        elif q is None:
            reasons.append(f"{quote_type.upper()}_UNAVAILABLE")
    if reasons:
        return Comparison("BLOCKED", quote_type, forecast_p, q, None, reasons)
    return Comparison("AVAILABLE", quote_type, forecast_p, q, float(Decimal(repr(forecast_p)) - q), [])
