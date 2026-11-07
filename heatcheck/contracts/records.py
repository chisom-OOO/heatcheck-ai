"""Shared record format heatcheck-records/1 (protocol heatcheck-nba/1).

Pure, stdlib-only validation of the records that Research and Experience exchange.
No HTTP, provider, database or file side effects live here; see ``bundle.py`` for
reading a bundle directory. Specification: docs/DATA_FORMAT.md.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable, Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

PROTOCOL_VERSION = "heatcheck-nba/1"
FORMAT_VERSION = "heatcheck-records/1"

DATA_MODES = ("REAL_NBA_RETROSPECTIVE", "SYNTHETIC", "LIVE_MARKET", "RECORDED_MARKET")
NBA_DATA_MODES = ("REAL_NBA_RETROSPECTIVE", "SYNTHETIC")
MARKET_DATA_MODES = ("LIVE_MARKET", "RECORDED_MARKET", "SYNTHETIC")

# Order used for canonical records.jsonl sorting.
RECORD_TYPES = (
    "RAW_SNAPSHOT",
    "GAME",
    "EVENT",
    "FEATURE_ROW",
    "RESTRICTED_LABEL",
    "VENUE_MARKET",
    "VENUE_MAPPING",
    "QUOTE",
)

ENVELOPE_FIELDS = ("protocol_version", "format_version", "record_type", "record_id", "data_mode")

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$")
SEASON_RE = re.compile(r"^(\d{4})-(\d{2})$")
DECIMAL_RE = re.compile(r"^(0|[1-9][0-9]*)(\.[0-9]+)?$")
ID_BODY = r"[0-9A-Za-z][0-9A-Za-z_.\-]{0,63}"
GAME_ID_RE = re.compile(rf"^(nba|syn):{ID_BODY}$")
TEAM_ID_RE = re.compile(rf"^(nba|syn)-team:{ID_BODY}$")
PLAYER_ID_RE = re.compile(rf"^(nba|syn)-player:{ID_BODY}$")
TOKEN_RE = re.compile(rf"^{ID_BODY}$")
FEATURE_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

MAX_STRING = 4096
MAX_LIST = 10_000


class RecordError(ValueError):
    """A record violates heatcheck-records/1. ``path`` locates the offending field."""

    def __init__(self, path: str, message: str):
        super().__init__(f"{path}: {message}")
        self.path = path
        self.message = message


# --------------------------------------------------------------------------- canonical bytes


def _reject_constant(name: str) -> Any:
    raise ValueError(f"non-finite JSON constant {name} is not allowed")


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"duplicate JSON key {key!r}")
        out[key] = value
    return out


def loads_strict(text: str) -> Any:
    """Parse JSON rejecting NaN/Infinity and duplicate keys."""
    return json.loads(text, parse_constant=_reject_constant, object_pairs_hook=_no_duplicate_keys)


def canonical_bytes(value: Any) -> bytes:
    """Canonical UTF-8 JSON: sorted keys, no whitespace, finite numbers only."""
    _assert_finite(value, "$")
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def record_hash(record: Mapping[str, Any]) -> str:
    return sha256_hex(canonical_bytes(record))


def _assert_finite(value: Any, path: str) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise RecordError(path, "non-finite number")
    if isinstance(value, dict):
        for k, v in value.items():
            if not isinstance(k, str):
                raise RecordError(path, "object keys must be strings")
            _assert_finite(v, f"{path}.{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            _assert_finite(v, f"{path}[{i}]")


# --------------------------------------------------------------------------- field checkers

Check = Callable[[Any, str], None]


def _string(value: Any, path: str) -> None:
    if not isinstance(value, str) or not value or len(value) > MAX_STRING:
        raise RecordError(path, f"expected non-empty string of at most {MAX_STRING} chars")


def _pattern(regex: re.Pattern[str], label: str) -> Check:
    def check(value: Any, path: str) -> None:
        if not isinstance(value, str) or not regex.match(value):
            raise RecordError(path, f"expected {label}")

    return check


def _enum(*choices: str) -> Check:
    def check(value: Any, path: str) -> None:
        if value not in choices:
            raise RecordError(path, f"expected one of {list(choices)}")

    return check


def _int(minimum: int | None = None) -> Check:
    def check(value: Any, path: str) -> None:
        if isinstance(value, bool) or not isinstance(value, int):
            raise RecordError(path, "expected integer")
        if minimum is not None and value < minimum:
            raise RecordError(path, f"expected integer >= {minimum}")

    return check


def _bool(value: Any, path: str) -> None:
    if not isinstance(value, bool):
        raise RecordError(path, "expected boolean")


def _number(value: Any, path: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RecordError(path, "expected finite number")
    if not math.isfinite(value):
        raise RecordError(path, "non-finite number")


def parse_utc(value: str) -> datetime:
    """Parse a validated UTC timestamp. Never compare timestamp strings lexically."""
    return datetime.fromisoformat(value[:-1] + "+00:00")


def _utc(value: Any, path: str) -> None:
    if not isinstance(value, str) or not UTC_RE.match(value):
        raise RecordError(path, "expected UTC timestamp YYYY-MM-DDTHH:MM:SS[.ffffff]Z")
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise RecordError(path, f"invalid calendar timestamp ({exc})") from None


def _season(value: Any, path: str) -> None:
    m = SEASON_RE.match(value) if isinstance(value, str) else None
    if not m or (int(m.group(1)) + 1) % 100 != int(m.group(2)):
        raise RecordError(path, "expected season like 2023-24")


def _decimal(minimum: Decimal | None = None, maximum: Decimal | None = None) -> Check:
    def check(value: Any, path: str) -> None:
        if not isinstance(value, str) or not DECIMAL_RE.match(value):
            raise RecordError(path, "expected non-negative decimal string such as '0.5300'")
        try:
            d = Decimal(value)
        except InvalidOperation:
            raise RecordError(path, "invalid decimal") from None
        if minimum is not None and d < minimum:
            raise RecordError(path, f"expected >= {minimum}")
        if maximum is not None and d > maximum:
            raise RecordError(path, f"expected <= {maximum}")

    return check


def _nullable(check: Check) -> Check:
    def wrapped(value: Any, path: str) -> None:
        if value is not None:
            check(value, path)

    return wrapped


def _list(item: Check, *, min_len: int = 0, unique: bool = False) -> Check:
    def check(value: Any, path: str) -> None:
        if not isinstance(value, list) or not (min_len <= len(value) <= MAX_LIST):
            raise RecordError(path, f"expected list with {min_len}..{MAX_LIST} items")
        for i, v in enumerate(value):
            item(v, f"{path}[{i}]")
        if unique and len({json.dumps(v, sort_keys=True) for v in value}) != len(value):
            raise RecordError(path, "list items must be unique")

    return check


def _object(fields: Mapping[str, Check], optional: Mapping[str, Check] | None = None) -> Check:
    optional = optional or {}

    def check(value: Any, path: str) -> None:
        if not isinstance(value, dict):
            raise RecordError(path, "expected object")
        unknown = set(value) - set(fields) - set(optional)
        if unknown:
            raise RecordError(path, f"unknown fields {sorted(unknown)}")
        for name, field_check in fields.items():
            if name not in value:
                raise RecordError(f"{path}.{name}", "required field missing")
            field_check(value[name], f"{path}.{name}")
        for name, field_check in optional.items():
            if name in value:
                field_check(value[name], f"{path}.{name}")

    return check


def _str_map(key: Check, val: Check) -> Check:
    def check(value: Any, path: str) -> None:
        if not isinstance(value, dict) or len(value) > MAX_LIST:
            raise RecordError(path, "expected object map")
        for k, v in value.items():
            key(k, f"{path}<key {k!r}>")
            val(v, f"{path}.{k}")

    return check


SHA = _pattern(SHA256_RE, "lowercase sha256 hex")
GAME_ID = _pattern(GAME_ID_RE, "game id 'nba:<id>' or 'syn:<id>'")
TEAM_ID = _pattern(TEAM_ID_RE, "team id 'nba-team:<id>' or 'syn-team:<id>'")
PLAYER_ID = _pattern(PLAYER_ID_RE, "player id 'nba-player:<id>' or 'syn-player:<id>'")
TOKEN = _pattern(TOKEN_RE, "identifier token")
PROB = _decimal(Decimal(0), Decimal(1))
QTY = _decimal(Decimal(0))

# --------------------------------------------------------------------------- record bodies

RAW_SNAPSHOT = _object(
    {
        "snapshot_sha256": SHA,
        "provider": TOKEN,
        "source": _string,  # upstream repo@commit/file or endpoint path, never a key
        "redacted_params": _str_map(_string, _string),
        "retrieved_utc": _utc,
        "byte_count": _int(0),
        "media_type": _string,
        "schema_version": _string,
        "rights_note": _string,
        "bundle_path": _nullable(_string),  # null => not redistributed; fetch manifest only
    }
)

GAME = _object(
    {
        "game_id": GAME_ID,
        "season": _season,
        "competition": _enum("REGULAR_SEASON", "PLAY_IN", "PLAYOFFS", "PRESEASON", "OTHER"),
        "provider_ids": _str_map(TOKEN, _string),
        "home_team_id": TEAM_ID,
        "away_team_id": TEAM_ID,
        # Scheduled tip as published before the game; null when the source does not supply it.
        "scheduled_tip_utc": _nullable(_utc),
        "status": _enum("SCHEDULED", "FINAL", "POSTPONED", "CANCELLED", "UNKNOWN"),
        "source_snapshot_ids": _list(SHA, min_len=1, unique=True),
    },
    # Actual tip observed in play-by-play (e.g. first period-start event). Known only after the
    # game starts, so it must never serve as a pre-tip cutoff. Optional key for compatibility.
    {"observed_tip_utc": _nullable(_utc)},
)

SHOT = _object(
    {
        "kind": _enum("FIELD_GOAL", "FREE_THROW"),
        "made": _bool,
        "points_if_made": _int(1),
        "shot_type": _nullable(_string),
        "distance_ft": _nullable(_number),
        # Post-outcome attribution. Never a pre-shot feature of the same shot.
        "assisted_post_outcome": _nullable(_bool),
        "free_throw_trip": _nullable(_object({"attempt": _int(1), "of": _int(1)})),
    }
)

EVENT = _object(
    {
        "game_id": GAME_ID,
        "provider": TOKEN,
        "provider_event_id": _string,
        "revision": _int(1),
        "period": _int(1),
        "sequence": _int(0),  # provider-documented order within the game
        "clock_seconds_remaining": _nullable(_decimal(Decimal(0), Decimal(720))),
        "event_time_utc": _nullable(_utc),
        "team_id": _nullable(TEAM_ID),
        "player_id": _nullable(PLAYER_ID),
        "action": _enum(
            "SHOT",
            "REBOUND",
            "TURNOVER",
            "FOUL",
            "SUBSTITUTION",
            "TIMEOUT",
            "JUMP_BALL",
            "VIOLATION",
            "PERIOD_START",
            "PERIOD_END",
            "OTHER",
        ),
        "provider_action": _string,
        "shot": _nullable(SHOT),
        "source_snapshot_ids": _list(SHA, min_len=1, unique=True),
    }
)

FEATURE_VALUE = _object(
    {"value": _nullable(_number), "missing_reason": _nullable(_string)},
)

CUTOFF = _object(
    {
        "kind": _enum("UTC", "GAME_SEQUENCE"),
        "utc": _nullable(_utc),
        "game_id": _nullable(GAME_ID),
        "before_sequence": _nullable(_int(0)),
    }
)

FEATURE_ROW = _object(
    {
        "target_id": _string,
        "target_kind": _enum("PRE_TIP_TEAM_WIN", "PRE_SHOT_MAKE"),
        "game_id": GAME_ID,
        "cutoff": CUTOFF,
        "feature_version": _string,
        "features": _str_map(_pattern(FEATURE_NAME_RE, "snake_case feature name"), FEATURE_VALUE),
        "max_input_sequence": _nullable(_int(0)),
        "max_input_available_utc": _nullable(_utc),
        "availability_assumption": _string,
        "source_record_hashes": _list(SHA, unique=True),
    }
)

RESTRICTED_LABEL = _object(
    {
        "target_id": _string,
        "label_kind": _enum("GAME_FINAL_SCORE", "TEAM_WIN", "SHOT_MADE"),
        "game_id": GAME_ID,
        "value": _object(
            {},
            {
                "home_points": _int(0),
                "away_points": _int(0),
                "team_id": TEAM_ID,
                "won": _bool,
                "made": _bool,
            },
        ),
        "first_observed_utc": _nullable(_utc),
        "revision": _int(1),
        "reconciliation": _enum("RECONCILED", "UNVERIFIED", "QUARANTINED"),
        "source_snapshot_ids": _list(SHA, min_len=1, unique=True),
    }
)

OUTCOME = _object({"contract_id": _string, "label": _string})

VENUE_MARKET = _object(
    {
        "venue": _enum("POLYMARKET", "KALSHI", "SYNTHETIC_VENUE"),
        "venue_api_version": _string,
        "event_id": _string,
        "market_id": _string,
        "title": _string,
        "outcomes": _list(OUTCOME, min_len=1, unique=True),
        "rules_text_sha256": _nullable(SHA),
        "settlement_source": _nullable(_string),
        "price_unit": _enum("PROBABILITY_DOLLARS"),
        "quantity_unit": _enum("CONTRACTS", "SHARES"),
        "tick_size": _nullable(PROB),
        "source_snapshot_ids": _list(SHA, min_len=1, unique=True),
    }
)

VENUE_MAPPING = _object(
    {
        "mapping_id": _string,
        "game_id": GAME_ID,
        "venue_market_record_id": _string,
        "contract_id": _string,
        "team_id": TEAM_ID,
        "outcome_direction": _enum("TEAM_WINS"),
        "overtime_convention": _enum("INCLUDES_OVERTIME", "REGULATION_ONLY", "UNKNOWN"),
        "cancel_postpone_convention": _string,
        "status": _enum("PROPOSED", "VERIFIED", "BLOCKED_RULES_UNVERIFIED"),
        "reason": _string,
        "mapping_provenance": _string,
    }
)

LEVEL = _object(
    {
        "side": _enum("BID", "ASK"),
        "price": PROB,
        "size": QTY,
        "derivation": _enum("DIRECT", "DERIVED_COMPLEMENT"),
    }
)

QUOTE = _object(
    {
        "mapping_id": _string,
        "venue": _enum("POLYMARKET", "KALSHI", "SYNTHETIC_VENUE"),
        "market_id": _string,
        "contract_id": _string,
        "levels": _list(LEVEL),
        "provider_time_utc": _nullable(_utc),
        "fetch_start_utc": _utc,
        "received_utc": _utc,
        "adapter_version": _string,
        "status": _enum("OK", "EMPTY", "STALE", "PAUSED", "ERROR"),
        "status_reason": _nullable(_string),
        "raw_snapshot_id": SHA,
    }
)

BODIES: dict[str, Check] = {
    "RAW_SNAPSHOT": RAW_SNAPSHOT,
    "GAME": GAME,
    "EVENT": EVENT,
    "FEATURE_ROW": FEATURE_ROW,
    "RESTRICTED_LABEL": RESTRICTED_LABEL,
    "VENUE_MARKET": VENUE_MARKET,
    "VENUE_MAPPING": VENUE_MAPPING,
    "QUOTE": QUOTE,
}

ALLOWED_MODES: dict[str, tuple[str, ...]] = {
    "RAW_SNAPSHOT": DATA_MODES,
    # A GAME in a market mode is a schedule reference captured alongside a quote; events,
    # features and labels may only attach to GAME records in an NBA data mode (bundle check).
    "GAME": DATA_MODES,
    "EVENT": NBA_DATA_MODES,
    "FEATURE_ROW": NBA_DATA_MODES,
    "RESTRICTED_LABEL": NBA_DATA_MODES,
    "VENUE_MARKET": MARKET_DATA_MODES,
    "VENUE_MAPPING": MARKET_DATA_MODES,
    "QUOTE": MARKET_DATA_MODES,
}


def validate_record(record: Any) -> None:
    """Raise RecordError if ``record`` is not a valid heatcheck-records/1 record."""
    if not isinstance(record, dict):
        raise RecordError("$", "record must be an object")
    _assert_finite(record, "$")
    missing = [f for f in (*ENVELOPE_FIELDS, "body") if f not in record]
    if missing:
        raise RecordError("$", f"missing envelope fields {missing}")
    unknown = set(record) - {*ENVELOPE_FIELDS, "body"}
    if unknown:
        raise RecordError("$", f"unknown envelope fields {sorted(unknown)}")
    if record["protocol_version"] != PROTOCOL_VERSION:
        raise RecordError("$.protocol_version", f"expected {PROTOCOL_VERSION}")
    if record["format_version"] != FORMAT_VERSION:
        raise RecordError("$.format_version", f"expected {FORMAT_VERSION}")
    rtype = record["record_type"]
    if rtype not in BODIES:
        raise RecordError("$.record_type", f"expected one of {list(RECORD_TYPES)}")
    _string(record["record_id"], "$.record_id")
    mode = record["data_mode"]
    if mode not in ALLOWED_MODES[rtype]:
        raise RecordError("$.data_mode", f"{rtype} allows {list(ALLOWED_MODES[rtype])}")
    body = record["body"]
    BODIES[rtype](body, "$.body")
    _semantic_checks(rtype, mode, body)


def _id_namespace_ok(identifier: str, mode: str) -> bool:
    synthetic = identifier.startswith("syn")
    return synthetic == (mode == "SYNTHETIC")


def _semantic_checks(rtype: str, mode: str, body: dict[str, Any]) -> None:
    # Synthetic identifiers can never masquerade as real NBA ones, and vice versa.
    for key in ("game_id", "home_team_id", "away_team_id", "team_id", "player_id"):
        value = body.get(key)
        if isinstance(value, str) and not _id_namespace_ok(value, mode):
            raise RecordError(f"$.body.{key}", f"id namespace does not match data_mode {mode}")
    if rtype == "GAME":
        if body["home_team_id"] == body["away_team_id"]:
            raise RecordError("$.body.away_team_id", "home and away teams must differ")
        if body["scheduled_tip_utc"] is None and body.get("observed_tip_utc") is None:
            raise RecordError("$.body", "need scheduled_tip_utc or observed_tip_utc")
    if rtype == "EVENT":
        shot = body["shot"]
        if (body["action"] == "SHOT") != (shot is not None):
            raise RecordError("$.body.shot", "shot object required iff action == SHOT")
        if shot is not None:
            if shot["kind"] == "FREE_THROW" and shot["points_if_made"] != 1:
                raise RecordError("$.body.shot.points_if_made", "free throw is worth 1")
            if shot["kind"] == "FIELD_GOAL" and shot["points_if_made"] not in (2, 3):
                raise RecordError("$.body.shot.points_if_made", "field goal is worth 2 or 3")
            trip = shot["free_throw_trip"]
            if trip is not None and (shot["kind"] != "FREE_THROW" or trip["attempt"] > trip["of"]):
                raise RecordError("$.body.shot.free_throw_trip", "invalid free-throw trip")
            if shot["kind"] == "FREE_THROW" and shot["assisted_post_outcome"]:
                raise RecordError("$.body.shot.assisted_post_outcome", "free throws are unassisted")
    if rtype == "FEATURE_ROW":
        cutoff = body["cutoff"]
        if cutoff["kind"] == "UTC" and cutoff["utc"] is None:
            raise RecordError("$.body.cutoff.utc", "UTC cutoff requires utc")
        if cutoff["kind"] == "GAME_SEQUENCE":
            if cutoff["before_sequence"] is None or cutoff["game_id"] != body["game_id"]:
                raise RecordError("$.body.cutoff", "sequence cutoff needs game_id and sequence")
            mis = body["max_input_sequence"]
            if mis is not None and mis >= cutoff["before_sequence"]:
                raise RecordError(
                    "$.body.max_input_sequence", "inputs must be strictly before the cutoff"
                )
        if cutoff["kind"] == "UTC" and body["max_input_available_utc"] is not None:
            if parse_utc(body["max_input_available_utc"]) > parse_utc(cutoff["utc"]):
                raise RecordError("$.body.max_input_available_utc", "input available after cutoff")
        for name, fv in body["features"].items():
            if (fv["value"] is None) == (fv["missing_reason"] is None):
                raise RecordError(
                    f"$.body.features.{name}", "exactly one of value/missing_reason must be set"
                )
            if "assist" in name:
                raise RecordError(f"$.body.features.{name}", "assist attribution is post-outcome")
    if rtype == "RESTRICTED_LABEL":
        required = {
            "GAME_FINAL_SCORE": {"home_points", "away_points"},
            "TEAM_WIN": {"team_id", "won"},
            "SHOT_MADE": {"made"},
        }[body["label_kind"]]
        if set(body["value"]) != required:
            raise RecordError("$.body.value", f"{body['label_kind']} needs exactly {sorted(required)}")
    if rtype == "QUOTE":
        if parse_utc(body["received_utc"]) < parse_utc(body["fetch_start_utc"]):
            raise RecordError("$.body.received_utc", "received before fetch started")
        if body["status"] == "OK" and not body["levels"]:
            raise RecordError("$.body.levels", "OK quote needs at least one level; use EMPTY")
        if body["status"] != "OK" and body["status_reason"] is None:
            raise RecordError("$.body.status_reason", "non-OK quote needs a reason")
        bids = [Decimal(lv["price"]) for lv in body["levels"] if lv["side"] == "BID"]
        asks = [Decimal(lv["price"]) for lv in body["levels"] if lv["side"] == "ASK"]
        if bids and asks and max(bids) > min(asks) and body["status"] == "OK":
            raise RecordError("$.body.levels", "crossed book cannot have status OK")
    if rtype == "VENUE_MAPPING" and body["status"] == "VERIFIED":
        if body["overtime_convention"] == "UNKNOWN":
            raise RecordError("$.body.status", "VERIFIED mapping needs a known overtime rule")


def sort_key(record: Mapping[str, Any]) -> tuple[int, str]:
    return (RECORD_TYPES.index(record["record_type"]), record["record_id"])


def encode_records(records: list[dict[str, Any]]) -> bytes:
    """Canonical records.jsonl bytes: validated, sorted, one canonical record per line."""
    for r in records:
        validate_record(r)
    ordered = sorted(records, key=sort_key)
    return b"".join(canonical_bytes(r) + b"\n" for r in ordered)
