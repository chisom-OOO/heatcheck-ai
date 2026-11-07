"""Read-only NBA market comparison: forecast vs one typed, timestamped quote for the same event.

Pipeline: spec -> mapping proposal -> human approval -> book -> freshness/eligibility -> typed
difference. Every non-OK outcome is a visible status with reasons; nothing is zero-filled.
The arithmetic calls quotes.compare (stand-in for Research's normaliser, gate G11).
"""
import hashlib
import json
import uuid
from datetime import datetime, timezone

from . import mapping as mapping_mod
from . import quotes
from .contracts import validate_envelope
from .venues import VenueError, adapter

FRESHNESS_SECONDS_HISTORICAL = 600   # configured before the demo; recorded in every comparison
FRESHNESS_SECONDS_LIVE = 60


def _sha(o):
    return hashlib.sha256(json.dumps(quotes.to_jsonable(o), sort_keys=True, default=str).encode()).hexdigest()


def _dt(s):
    if not s:
        return None
    d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def propose(venue, ref, game, forecast, transport):
    ad = adapter(venue, transport)
    try:
        spec = ad.get_market_spec(ref)
    except VenueError as e:
        return {"stage": "spec", "status": e.status, "reason": e.reason, "spec": None, "mapping": None}
    m = mapping_mod.propose(game, forecast["team"], spec)
    return {"stage": "mapping", "status": m["status"], "spec": spec, "mapping": m}


def compare(spec, mapping, forecast, transport, reviewer, quote_type="midpoint", plan_hash=None, now=None):
    blocked = []
    comp_status = "OK"
    snap = None
    result = None
    approved = None
    try:
        approved = mapping_mod.approve(mapping, reviewer, spec["rules_hash"])
    except PermissionError as e:
        blocked.append(str(e))
        comp_status = mapping["status"] if mapping["status"] != "PROPOSED" else "MAPPING_NOT_APPROVED"

    if approved:
        try:
            snap = adapter(spec["venue"], transport).get_book(spec, approved["outcome_direction"]["contract_id"])
        except VenueError as e:
            comp_status, snap = e.status, None
            blocked.append(e.reason)

    fresh = None
    if snap:
        historical = transport.name != "live"
        observed = _dt(snap["provider_time"]) or _dt(snap["received_at_utc"])
        cutoff = _dt(forecast["cutoff_utc"])
        if historical:
            # eligibility is judged at the forecast cutoff, never against today's clock
            fresh = quotes.freshness(observed, now_utc=cutoff, threshold_seconds=FRESHNESS_SECONDS_HISTORICAL,
                                     cutoff_utc=cutoff)
        else:
            fresh = quotes.freshness(_dt(snap["received_at_utc"]), now_utc=now or datetime.now(timezone.utc),
                                     threshold_seconds=FRESHNESS_SECONDS_LIVE)
        fresh["observed_at"] = observed.isoformat() if observed else None
        fresh["basis"] = "forecast cutoff" if historical else "local clock at comparison"
        if fresh["status"] != "FRESH":
            comp_status = fresh["status"]
            blocked.append({"STALE_BOOK": f"quote older than {fresh.get('threshold_seconds')}s at the {fresh['basis']}",
                            "FUTURE_QUOTE": "quote observed after the forecast cutoff is ineligible"}[fresh["status"]])
        elif snap["crossed"]:
            comp_status = "CROSSED_BOOK"
            blocked.append("book is crossed (best bid above best ask); no quote type is compared")
        elif spec.get("market_status") == "PAUSED_MARKET":
            comp_status = "PAUSED_MARKET"
            blocked.append("market is not open")
        else:
            book = {"best_bid": snap["best_bid"], "best_ask": snap["best_ask"], "midpoint": snap["midpoint"],
                    "midpoint_unavailable_reason": snap["midpoint_unavailable_reason"],
                    "ask_is_derived": snap["ask_is_derived"]}
            result = quotes.compare(forecast["probability"], book, quote_type)
            if result["status"] != "OK":
                comp_status = result["status"]
                blocked.append(result["reason"])

    env = {
        "comparison_id": "cmp_" + uuid.uuid4().hex[:12],
        "confirmed_plan_hash": plan_hash,
        "forecast_evidence_hash": forecast.get("evidence_hash"),
        "event_mapping_hash": _sha(approved or mapping),
        "book_snapshot_hash": _sha(snap) if snap else None,
        "quote_type_unit": {"type": quote_type, "unit": "probability (dollars per $1 payout)",
                            "derived": bool(result and result.get("ask_is_derived"))},
        "forecast_probability": float(forecast["probability"]),
        "observed_quote": result["observed_quote"] if result and result["status"] == "OK" else None,
        "signed_probability_difference": result["signed_probability_difference"] if result and result["status"] == "OK" else None,
        "timestamps_freshness": fresh,
        "data_mode": "LIVE_MARKET" if transport.name == "live" else getattr(transport, "data_mode", "SYNTHETIC"),
        "status": comp_status,
        "blocked_reasons": blocked,
        "forecast": forecast,
        "mapping": approved or mapping,
        "book": snap,
        "venue": spec["venue"],
        "note": "Descriptive difference only. Not an expected profit, edge, fill estimate or instruction to trade.",
        "arithmetic_owner": "quotes.py stand-in (Research canonical normaliser not yet integrated)",
    }
    validate_envelope("MarketComparison", quotes.to_jsonable(env))
    return env
