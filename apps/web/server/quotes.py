"""STAND-IN quote normaliser and comparison arithmetic.

Research owns the canonical implementation (gate G11). This module exists so the Experience
layer can run offline against fixtures; replace calls with Research's normaliser when delivered.
All money/probability math uses Decimal. No fees, no profit, no sizing, no ranking.
"""
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

ZERO, ONE = Decimal("0"), Decimal("1")
# The only unit label in heatcheck-records/1 (docs/DATA_FORMAT.md): decimal-string probability
# dollars per $1 payout, in [0, 1]. Cents and any other unit are refused, never converted.
PRICE_UNIT = "PROBABILITY_DOLLARS"


class QuoteError(ValueError):
    def __init__(self, status, msg):
        super().__init__(msg)
        self.status = status


def parse_price(raw, unit=PRICE_UNIT):
    """Only PROBABILITY_DOLLARS decimal strings in [0,1]. Any other unit is UNKNOWN_UNITS."""
    if unit != PRICE_UNIT:
        raise QuoteError("UNKNOWN_UNITS", f"price unit {unit!r} refused; only {PRICE_UNIT} is accepted")
    if not isinstance(raw, str):
        raise QuoteError("MALFORMED", f"{type(raw).__name__} price rejected; venues send decimal strings")
    try:
        d = Decimal(raw.strip())
    except InvalidOperation:
        raise QuoteError("MALFORMED", f"unparseable price {raw!r}") from None
    if not d.is_finite():
        raise QuoteError("MALFORMED", "non-finite price")
    if d < ZERO or d > ONE:
        raise QuoteError("UNKNOWN_UNITS", f"price {d} outside [0,1]; not {PRICE_UNIT}")
    return d


def parse_qty(raw):
    try:
        d = Decimal(str(raw).strip())
    except InvalidOperation:
        raise QuoteError("MALFORMED", f"unparseable quantity {raw!r}") from None
    if not d.is_finite() or d < 0:
        raise QuoteError("MALFORMED", "negative or non-finite quantity")
    return d


def check_grid(price, tick):
    if tick and (price % Decimal(str(tick))) != 0:
        raise QuoteError("OFF_GRID", f"price {price} is not on the {tick} tick grid")


def normalise_kalshi(orderbook_fp, tick="0.01"):
    """Kalshi gives only bids for YES and NO. YES ask is DERIVED as 1 - best NO bid."""
    if not isinstance(orderbook_fp, dict) or "yes_dollars" not in orderbook_fp or "no_dollars" not in orderbook_fp:
        raise QuoteError("MALFORMED", "orderbook_fp must contain yes_dollars and no_dollars")
    yes_bids, no_bids = [], []
    for price, qty in orderbook_fp["yes_dollars"]:
        p = parse_price(price)
        check_grid(p, tick)
        yes_bids.append({"price": p, "qty": parse_qty(qty), "derived": False, "raw_side": "yes_bid"})
    derived_yes_asks = []
    for price, qty in orderbook_fp["no_dollars"]:
        p = parse_price(price)
        check_grid(p, tick)
        no_bids.append({"price": p, "qty": parse_qty(qty)})
        derived_yes_asks.append({"price": ONE - p, "qty": parse_qty(qty), "derived": True, "raw_side": "no_bid"})
    return _book(yes_bids, derived_yes_asks, raw_no_bids=no_bids)


def normalise_polymarket(book, tick=None):
    """Use the selected outcome token's own bids/asks. Sort ourselves; never trust ordering."""
    if not isinstance(book, dict) or "bids" not in book or "asks" not in book:
        raise QuoteError("MALFORMED", "book must contain bids and asks")
    tick = tick or book.get("tick_size")
    bids = []
    asks = []
    for lv in book["bids"]:
        p = parse_price(lv["price"])
        check_grid(p, tick)
        bids.append({"price": p, "qty": parse_qty(lv["size"]), "derived": False, "raw_side": "bid"})
    for lv in book["asks"]:
        p = parse_price(lv["price"])
        check_grid(p, tick)
        asks.append({"price": p, "qty": parse_qty(lv["size"]), "derived": False, "raw_side": "ask"})
    return _book(bids, asks)


def _book(bids, asks, raw_no_bids=None):
    bids = sorted(bids, key=lambda lv: lv["price"], reverse=True)
    asks = sorted(asks, key=lambda lv: lv["price"])
    bb = bids[0]["price"] if bids else None
    ba = asks[0]["price"] if asks else None
    crossed = bb is not None and ba is not None and bb > ba
    mid = None
    reason = None
    if bb is None or ba is None:
        reason = "midpoint unavailable: missing " + ("bid" if bb is None else "ask") + " side"
    elif crossed:
        reason = "midpoint unavailable: book is crossed"
    else:
        mid = (bb + ba) / 2
    return {
        "bids": bids, "asks": asks, "best_bid": bb, "best_ask": ba,
        "midpoint": mid, "midpoint_unavailable_reason": reason,
        "spread": (ba - bb) if (bb is not None and ba is not None and not crossed) else None,
        "crossed": crossed,
        "ask_is_derived": bool(asks and asks[0].get("derived")),
    }


def freshness(received_utc, now_utc=None, threshold_seconds=30, cutoff_utc=None):
    """Explicit status; a historical comparison never accepts a quote received after its cutoff."""
    now_utc = now_utc or datetime.now(UTC)
    age = (now_utc - received_utc).total_seconds()
    if cutoff_utc is not None and received_utc > cutoff_utc:
        return {"status": "FUTURE_QUOTE", "age_seconds": age}
    if age < 0:
        return {"status": "FUTURE_QUOTE", "age_seconds": age}
    if age > threshold_seconds:
        return {"status": "STALE_BOOK", "age_seconds": age, "threshold_seconds": threshold_seconds}
    return {"status": "FRESH", "age_seconds": age, "threshold_seconds": threshold_seconds}


def compare(forecast_probability, book, quote_type="midpoint"):
    """signed difference = forecast - typed quote. Descriptive only; not profit, not a recommendation."""
    if not (isinstance(forecast_probability, (int, float, Decimal)) and ZERO <= Decimal(str(forecast_probability)) <= ONE):
        raise QuoteError("MALFORMED", "forecast probability must be in [0,1]")
    key = {"bid": "best_bid", "ask": "best_ask", "midpoint": "midpoint"}.get(quote_type)
    if key is None:
        raise QuoteError("UNSUPPORTED_QUOTE_TYPE", quote_type)
    q = book.get(key)
    if q is None:
        why = book.get("midpoint_unavailable_reason") if quote_type == "midpoint" else f"{quote_type} side missing"
        return {"status": "QUOTE_UNAVAILABLE", "reason": why, "signed_probability_difference": None}
    diff = Decimal(str(forecast_probability)) - q
    return {
        "status": "OK", "quote_type": quote_type, "observed_quote": q,
        "forecast_probability": Decimal(str(forecast_probability)),
        "signed_probability_difference": diff,
        "percentage_points": diff * 100,
        "ask_is_derived": book["ask_is_derived"] if quote_type == "ask" else False,
        "note": "Descriptive difference only. Not an expected profit, edge, or instruction to trade.",
    }


def to_jsonable(o):
    if isinstance(o, Decimal):
        return format(o, "f")
    if isinstance(o, dict):
        return {k: to_jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [to_jsonable(v) for v in o]
    return o
