"""Pure quote-eligibility selection for MARKET_COMPARISON (M-002). No I/O.

Implements DATA_PIPELINE.md §4.4: for a forecast cutoff, select the latest quote that
was actually *received* by the cutoff for a verified mapping. Quotes received after the
cutoff are never eligible; quotes older than the configured freshness threshold are
STALE. The result is descriptive selection only; no arithmetic on prices happens here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from heatcheck.contracts.records import parse_utc, validate_record

# Freshness thresholds fixed before any demo (docs/DECISIONS.md, 7 November).
HISTORICAL_MAX_AGE = timedelta(seconds=600)  # quote received <= 600 s before forecast cutoff
LIVE_MAX_AGE = timedelta(seconds=60)  # live display: quote no more than 60 s old


@dataclass(frozen=True)
class QuoteSelection:
    status: str  # ELIGIBLE | NO_QUOTE_BY_CUTOFF | STALE | MAPPING_NOT_VERIFIED | QUOTE_NOT_OK
    quote_record_id: str | None
    reason: str
    age_seconds: float | None


def select_quote_for_cutoff(
    mapping: dict[str, Any],
    quotes: list[dict[str, Any]],
    cutoff_utc: str,
    max_age: timedelta,
) -> QuoteSelection:
    validate_record(mapping)
    if mapping["record_type"] != "VENUE_MAPPING":
        raise ValueError("mapping must be a VENUE_MAPPING record")
    if max_age <= timedelta(0):
        raise ValueError("max_age must be positive and configured before use")
    cutoff = parse_utc(cutoff_utc)
    m = mapping["body"]
    if m["status"] != "VERIFIED":
        return QuoteSelection("MAPPING_NOT_VERIFIED", None, f"mapping {m['status']}", None)

    candidates = []
    for q in quotes:
        validate_record(q)
        if q["record_type"] != "QUOTE" or q["body"]["mapping_id"] != m["mapping_id"]:
            continue
        received = parse_utc(q["body"]["received_utc"])
        if received <= cutoff:
            candidates.append((received, q["record_id"], q))
    if not candidates:
        return QuoteSelection(
            "NO_QUOTE_BY_CUTOFF", None, "no quote received at or before cutoff", None
        )

    received, rid, q = max(candidates, key=lambda c: (c[0], c[1]))
    age = (cutoff - received).total_seconds()
    if q["body"]["status"] != "OK":
        return QuoteSelection(
            "QUOTE_NOT_OK", rid, f"latest quote status {q['body']['status']}", age
        )
    if cutoff - received > max_age:
        return QuoteSelection("STALE", rid, f"quote age {age}s exceeds {max_age}", age)
    return QuoteSelection("ELIGIBLE", rid, "latest OK quote received by cutoff", age)
