"""Shared pieces of the read-only venue adapters (heatcheck-records/1 output).

Pure functions only: no HTTP, file or clock access. An adapter turns exact raw payload
bytes plus capture metadata into VENUE_MARKET / VENUE_MAPPING / QUOTE records. It stores
levels exactly as the venue reported them (``derivation: DIRECT``); complements,
midpoints and spreads belong to Research's normaliser, not here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from heatcheck.contracts.records import (
    FORMAT_VERSION,
    PROTOCOL_VERSION,
    UTC_RE,
    loads_strict,
    parse_utc,
    sha256_hex,
)

ADAPTER_VERSION = "experience-adapters/1"

# Prices must look like probability dollars: "0.53", never cents ("53") or numbers.
_PRICE_RE = re.compile(r"^(0|1)(\.[0-9]{1,6})?$")
_QTY_RE = re.compile(r"^(0|[1-9][0-9]*)(\.[0-9]+)?$")
# Fields that summarise a book. They are never levels and are never stored as one.
SUMMARY_FIELDS = frozenset(
    {"mid", "midpoint", "mid_price", "last", "last_price", "last_trade", "last_trade_price"}
)


class AdapterError(ValueError):
    """The payload cannot be turned into records. No record is emitted."""


@dataclass(frozen=True)
class Capture:
    """How one raw payload was obtained. ``source`` is the endpoint, never a key."""

    source: str
    fetch_start_utc: str | None
    received_utc: str | None
    data_mode: str

    def checked(self) -> Capture:
        for name in ("fetch_start_utc", "received_utc"):
            value = getattr(self, name)
            if value is None:
                raise AdapterError(f"capture metadata is missing {name}")
            if not isinstance(value, str) or not UTC_RE.match(value):
                raise AdapterError(f"capture {name} is not a UTC timestamp: {value!r}")
        if parse_utc(self.received_utc) < parse_utc(self.fetch_start_utc):
            raise AdapterError("capture received_utc is before fetch_start_utc")
        if self.data_mode not in ("LIVE_MARKET", "RECORDED_MARKET", "SYNTHETIC"):
            raise AdapterError(f"data_mode {self.data_mode!r} is not a market data mode")
        return self


def load_payload(raw: bytes) -> Any:
    """Strict JSON (no NaN, no duplicate keys) from the exact raw bytes."""
    try:
        return loads_strict(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise AdapterError(f"raw payload is not strict JSON: {exc}") from None


def price(value: Any, where: str) -> str:
    """Return a venue price string unchanged if it is probability dollars in (0, 1]."""
    if not isinstance(value, str):
        raise AdapterError(f"{where}: price {value!r} is not a decimal string; unit unknown")
    if not _PRICE_RE.match(value):
        try:
            looks_like_cents = Decimal(value) > 1
        except InvalidOperation:
            looks_like_cents = False
        if looks_like_cents:
            raise AdapterError(f"{where}: price {value!r} is above 1; cents are refused")
        raise AdapterError(f"{where}: price {value!r} is not probability dollars")
    d = Decimal(value)
    if d <= 0 or d > 1:
        raise AdapterError(f"{where}: price {value!r} is outside (0, 1]")
    return value


def quantity(value: Any, where: str) -> str:
    if not isinstance(value, str) or not _QTY_RE.match(value):
        raise AdapterError(f"{where}: size {value!r} is not a non-negative decimal string")
    return value


def level(side: str, price_value: Any, size_value: Any, where: str) -> dict[str, str]:
    return {
        "side": side,
        "price": price(price_value, where),
        "size": quantity(size_value, where),
        "derivation": "DIRECT",
    }


def refuse_summary_levels(book: dict[str, Any], sides: tuple[str, ...]) -> None:
    """A midpoint or last trade offered where levels belong is refused, never stored."""
    if not any(s in book for s in sides):
        offered = sorted(SUMMARY_FIELDS & set(book))
        if offered:
            raise AdapterError(f"book offers {offered} instead of levels; refused")
        raise AdapterError(f"book has none of the level fields {list(sides)}")


def envelope(record_type: str, record_id: str, data_mode: str, body: dict[str, Any]) -> dict:
    return {
        "protocol_version": PROTOCOL_VERSION,
        "format_version": FORMAT_VERSION,
        "record_type": record_type,
        "record_id": record_id,
        "data_mode": data_mode,
        "body": body,
    }


def mapping_id(game_id: str, venue: str, contract_id: str) -> str:
    return f"map:{game_id}:{venue}:{contract_id}"


def quote_record(
    *,
    capture: Capture,
    raw: bytes,
    venue: str,
    market: dict[str, Any],
    contract_id: str,
    game_id: str,
    levels: list[dict[str, str]],
    provider_time_utc: str | None,
    paused_reason: str | None,
    note: str | None,
) -> dict:
    """Build a QUOTE. Status is decided only from facts in the payloads."""
    bids = [Decimal(lv["price"]) for lv in levels if lv["side"] == "BID"]
    asks = [Decimal(lv["price"]) for lv in levels if lv["side"] == "ASK"]
    if not levels:
        status, reason = "EMPTY", "venue reported no bid and no ask levels"
    elif bids and asks and max(bids) > min(asks):
        status, reason = "ERROR", "crossed book: best bid above best ask as reported"
    elif paused_reason:
        status, reason = "PAUSED", paused_reason
    else:
        status, reason = "OK", note
    mid = mapping_id(game_id, venue, contract_id)
    raw_sha = sha256_hex(raw)
    return envelope(
        "QUOTE",
        f"quote:{mid}:{raw_sha[:16]}",
        capture.data_mode,
        {
            "mapping_id": mid,
            "venue": venue,
            "market_id": market["body"]["market_id"],
            "contract_id": contract_id,
            "levels": levels,
            "provider_time_utc": provider_time_utc,
            "fetch_start_utc": capture.fetch_start_utc,
            "received_utc": capture.received_utc,
            "adapter_version": ADAPTER_VERSION,
            "status": status,
            "status_reason": reason,
            "raw_snapshot_id": raw_sha,
        },
    )


def require_outcome(market: dict[str, Any], contract_id: str) -> None:
    ids = {o["contract_id"] for o in market["body"]["outcomes"]}
    if contract_id not in ids:
        raise AdapterError(f"contract id {contract_id!r} is not an outcome in the market metadata")


# ------------------------------------------------------------------ mapping proposal (rules text)

_REGULATION = re.compile(
    r"regulation (time )?only|excluding overtime|not including overtime|at the end of regulation"
)
_OVERTIME = re.compile(r"including (any )?overtime|includes overtime|overtime (periods )?count")
_POSTPONE_SENTENCE = re.compile(r"[^.]*\b(postpone|cancel|reschedul)[^.]*\.")


def overtime_convention(rules_text: str) -> str:
    text = rules_text.lower()
    if _REGULATION.search(text):
        return "REGULATION_ONLY"
    if _OVERTIME.search(text):
        return "INCLUDES_OVERTIME"
    return "UNKNOWN"


def postpone_convention(rules_text: str) -> str:
    """The rules' own postpone/cancel sentences, verbatim, or UNKNOWN with a reason."""
    sentences = [m.group(0).strip() for m in _POSTPONE_SENTENCE.finditer(rules_text)]
    if not sentences:
        return "UNKNOWN: the rules text does not mention postponement or cancellation"
    return "RULES TEXT: " + " ".join(sentences)


def propose_mapping(
    *,
    game_id: str,
    team_id: str,
    market: dict[str, Any],
    contract_id: str,
    expected_label: str,
    rules_text: str,
) -> dict:
    """PROPOSE a team-win mapping. Max verifies; this never sets VERIFIED."""
    body = market["body"]
    require_outcome(market, contract_id)
    if sha256_hex(rules_text.encode("utf-8")) != body["rules_text_sha256"]:
        raise AdapterError("rules text does not match the market's rules_text_sha256")
    label = next(o["label"] for o in body["outcomes"] if o["contract_id"] == contract_id)
    if label != expected_label:
        raise AdapterError(
            f"outcome {contract_id!r} is labelled {label!r}, not {expected_label!r}; "
            "outcome order is never assumed"
        )
    ot = overtime_convention(rules_text)
    reason = (
        "Proposed by the Experience adapter from the market's own outcome label and rules "
        f"text; overtime read as {ot}. Max verifies before any comparison."
    )
    return envelope(
        "VENUE_MAPPING",
        mapping_id(game_id, body["venue"], contract_id),
        market["data_mode"],
        {
            "mapping_id": mapping_id(game_id, body["venue"], contract_id),
            "game_id": game_id,
            "venue_market_record_id": market["record_id"],
            "contract_id": contract_id,
            "team_id": team_id,
            "outcome_direction": "TEAM_WINS",
            "overtime_convention": ot,
            "cancel_postpone_convention": postpone_convention(rules_text),
            "status": "PROPOSED",
            "reason": reason,
            "mapping_provenance": (
                f"{ADAPTER_VERSION} keyword read of rules_text_sha256 "
                f"{body['rules_text_sha256']} and outcome label {label!r}"
            ),
        },
    )


def ms_to_utc(value: Any, where: str) -> str | None:
    """Venue millisecond epoch string -> UTC 'Z' timestamp; None if absent."""
    if value is None:
        return None
    if not isinstance(value, str) or not value.isdigit():
        raise AdapterError(f"{where}: timestamp {value!r} is not epoch milliseconds")
    ms = int(value)
    dt = datetime.fromtimestamp(ms // 1000, tz=UTC)
    frac = ms % 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + (f".{frac:03d}Z" if frac else "Z")
