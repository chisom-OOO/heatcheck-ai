"""Shared pieces of the read-only venue adapters (heatcheck-records/1 output).

Pure functions only: no HTTP, file or clock access. An adapter turns exact raw payload
bytes plus capture metadata into VENUE_MARKET / VENUE_MAPPING / QUOTE records. It stores
levels exactly as the venue reported them (``derivation: DIRECT``); complements,
midpoints and spreads belong to Research's normaliser, not here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
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

# Capture-time bounds (adapter-level; Max's eligibility max_age is a separate, later check).
# One GET is one request/response; a longer window means the capture metadata is wrong.
MAX_FETCH_WINDOW = timedelta(seconds=60)
# A provider clock this far AHEAD of our receipt is a clock or unit error, not skew.
MAX_PROVIDER_AHEAD = timedelta(seconds=5)
# A book whose provider time is older than this at receipt is stored as STALE, never OK.
MAX_PROVIDER_AGE_OK = timedelta(seconds=60)
# Older than this is not a plausible book time at all (e.g. epoch seconds read as ms).
MAX_PROVIDER_AGE_PLAUSIBLE = timedelta(days=1)

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
        window = parse_utc(self.received_utc) - parse_utc(self.fetch_start_utc)
        if window < timedelta(0):
            raise AdapterError("capture received_utc is before fetch_start_utc")
        if window > MAX_FETCH_WINDOW:
            raise AdapterError(
                f"capture fetch window {window.total_seconds()}s exceeds "
                f"{MAX_FETCH_WINDOW.total_seconds()}s; capture times are not one request"
            )
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


def level(
    side: str, price_value: Any, size_value: Any, where: str, *, tick: str | None
) -> dict[str, str]:
    """One DIRECT level. Off-tick prices and zero sizes are refused (RV-E U1, U2, U4).

    ``tick`` is the market's own tick size from its metadata. A price off that grid is a
    unit or scaling error (e.g. cents divided by 100 twice), never rounded onto it.
    """
    p = price(price_value, where)
    q = quantity(size_value, where)
    if Decimal(q) == 0:
        raise AdapterError(f"{where}: size {q!r} is zero; a level with no size is not a level")
    if tick is None:
        raise AdapterError(f"{where}: market tick size unknown; price grid cannot be checked")
    if Decimal(p) % Decimal(tick) != 0:
        raise AdapterError(f"{where}: price {p!r} is not on the market tick {tick!r}")
    return {"side": side, "price": p, "size": q, "derivation": "DIRECT"}


def provider_time_status(provider_time_utc: str | None, capture: Capture) -> str | None:
    """Check a provider book time against our receipt time.

    Raises AdapterError when the time is implausible (far in the future relative to
    receipt, or older than a day: a unit or timezone error). Returns a STALE reason
    when the book is older than MAX_PROVIDER_AGE_OK at receipt, otherwise None.
    """
    if provider_time_utc is None:
        return None
    age = parse_utc(capture.received_utc) - parse_utc(provider_time_utc)
    if -age > MAX_PROVIDER_AHEAD:
        raise AdapterError(
            f"provider time {provider_time_utc} is {(-age).total_seconds()}s after receipt "
            f"{capture.received_utc}; more than {MAX_PROVIDER_AHEAD.total_seconds()}s ahead "
            "is a clock or timezone error"
        )
    if age > MAX_PROVIDER_AGE_PLAUSIBLE:
        raise AdapterError(
            f"provider time {provider_time_utc} is {age} before receipt "
            f"{capture.received_utc}; implausible for a book (unit error?)"
        )
    if age > MAX_PROVIDER_AGE_OK:
        return (
            f"book provider time {provider_time_utc} is {age.total_seconds()}s older than "
            f"receipt; over {MAX_PROVIDER_AGE_OK.total_seconds()}s is stale"
        )
    return None


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
    stale_reason = provider_time_status(provider_time_utc, capture)
    bids = [Decimal(lv["price"]) for lv in levels if lv["side"] == "BID"]
    asks = [Decimal(lv["price"]) for lv in levels if lv["side"] == "ASK"]
    if not levels:
        status, reason = "EMPTY", "venue reported no bid and no ask levels"
    elif bids and asks and max(bids) > min(asks):
        status, reason = "ERROR", "crossed book: best bid above best ask as reported"
    elif paused_reason:
        status, reason = "PAUSED", paused_reason
    elif stale_reason:
        status, reason = "STALE", stale_reason
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

# Negations are read first and positive phrases may not match inside them
# ("not including overtime" is not "including overtime").
_REGULATION = re.compile(
    r"regulation (time )?only"
    r"|(excluding|not including|does not include|do not include) (any )?overtime"
    r"|overtime (periods? )?(is|are|will be) (not included|not counted|excluded)"
    r"|overtime (periods? )?(does|do|will) not count"
)
_OVERTIME = re.compile(
    r"(?<!not )(?<!does not )including (any )?overtime"
    r"|(?<!not )includes (any )?overtime"
    r"|overtime (periods? )?(count|counts|are counted|is counted|are included|is included)\b"
)
# "at the end of regulation" means regulation only when it states the deciding moment,
# not when it describes the tie that sends a game to overtime (RV-E OT1).
_END_OF_REGULATION = re.compile(r"at the end of regulation")
_MENTIONS_OT_OR_TIE = re.compile(r"overtime|\btied?\b|\bties\b")
_POSTPONE_SENTENCE = re.compile(r"[^.]*\b(postpone|cancel|reschedul)[^.]*\.")


def overtime_convention(rules_text: str) -> str:
    """REGULATION_ONLY / INCLUDES_OVERTIME only when the rules say so without conflict."""
    text = rules_text.lower()
    regulation = bool(_REGULATION.search(text)) or any(
        _END_OF_REGULATION.search(s) and not _MENTIONS_OT_OR_TIE.search(s)
        for s in text.split(".")
    )
    overtime = bool(_OVERTIME.search(text))
    if regulation and overtime:
        return "UNKNOWN"
    if regulation:
        return "REGULATION_ONLY"
    if overtime:
        return "INCLUDES_OVERTIME"
    return "UNKNOWN"


# ------------------------------------------------------------------ team naming (RV-E O1, O2)

# tricode: (NBA Stats team id, names that identify only that team in an outcome label).
# "Los Angeles" alone is ambiguous (Clippers, Lakers) and is not listed for either.
NBA_TEAMS: dict[str, tuple[str, tuple[str, ...]]] = {
    "ATL": ("1610612737", ("Atlanta", "Hawks")),
    "BOS": ("1610612738", ("Boston", "Celtics")),
    "CLE": ("1610612739", ("Cleveland", "Cavaliers", "Cavs")),
    "NOP": ("1610612740", ("New Orleans", "Pelicans")),
    "CHI": ("1610612741", ("Chicago", "Bulls")),
    "DAL": ("1610612742", ("Dallas", "Mavericks", "Mavs")),
    "DEN": ("1610612743", ("Denver", "Nuggets")),
    "GSW": ("1610612744", ("Golden State", "Warriors")),
    "HOU": ("1610612745", ("Houston", "Rockets")),
    "LAC": ("1610612746", ("Clippers", "LA Clippers")),
    "LAL": ("1610612747", ("Lakers", "LA Lakers")),
    "MIA": ("1610612748", ("Miami", "Heat")),
    "MIL": ("1610612749", ("Milwaukee", "Bucks")),
    "MIN": ("1610612750", ("Minnesota", "Timberwolves")),
    "BKN": ("1610612751", ("Brooklyn", "Nets")),
    "NYK": ("1610612752", ("New York", "Knicks")),
    "ORL": ("1610612753", ("Orlando", "Magic")),
    "IND": ("1610612754", ("Indiana", "Pacers")),
    "PHI": ("1610612755", ("Philadelphia", "76ers", "Sixers")),
    "PHX": ("1610612756", ("Phoenix", "Suns")),
    "POR": ("1610612757", ("Portland", "Trail Blazers", "Blazers")),
    "SAC": ("1610612758", ("Sacramento", "Kings")),
    "SAS": ("1610612759", ("San Antonio", "Spurs")),
    "OKC": ("1610612760", ("Oklahoma City", "Thunder")),
    "TOR": ("1610612761", ("Toronto", "Raptors")),
    "UTA": ("1610612762", ("Utah", "Jazz")),
    "MEM": ("1610612763", ("Memphis", "Grizzlies")),
    "WAS": ("1610612764", ("Washington", "Wizards")),
    "DET": ("1610612765", ("Detroit", "Pistons")),
    "CHA": ("1610612766", ("Charlotte", "Hornets")),
}
_BY_NBA_ID = {nba_id: tri for tri, (nba_id, _) in NBA_TEAMS.items()}


def team_tricode(team_id: str) -> str:
    """'nba-team:<NBA Stats id>' or 'syn-team:<tricode>' -> tricode; refuse anything else."""
    prefix, _, rest = team_id.partition(":")
    tri = _BY_NBA_ID.get(rest) if prefix == "nba-team" else rest if prefix == "syn-team" else None
    if tri not in NBA_TEAMS:
        raise AdapterError(
            f"team id {team_id!r} is not a known NBA team; the outcome label cannot be checked"
        )
    return tri


def teams_named(label: str) -> set[str]:
    """Tricodes of every team the label names (whole words; tricodes in capitals)."""
    named = set()
    for tri, (_, names) in NBA_TEAMS.items():
        if re.search(rf"\b{tri}\b", label) or any(
            re.search(rf"(?<![A-Za-z0-9]){re.escape(n)}(?![A-Za-z0-9])", label, re.IGNORECASE)
            for n in names
        ):
            named.add(tri)
    return named


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
    # TEAM_WINS needs an outcome that names exactly that team. A NO contract ("NO") names
    # nobody: it pays when the YES subject loses, so it is never that subject's win (O1).
    tri = team_tricode(team_id)
    named = teams_named(label)
    if named != {tri}:
        what = "names no team" if not named else f"names {sorted(named)}"
        raise AdapterError(
            f"outcome {contract_id!r} labelled {label!r} {what}; TEAM_WINS for {team_id} "
            f"({tri}) needs an outcome that names that team and no other"
        )
    # Kalshi game tickers end in the YES team's code (KXNBAGAME-26NOV07DENIND-IND). When that
    # code is a known tricode it must be the mapped team: an id check, not only a label check.
    if body["venue"] == "KALSHI":
        suffix = body["market_id"].rsplit("-", 1)[-1]
        if suffix in NBA_TEAMS and suffix != tri:
            raise AdapterError(
                f"Kalshi ticker {body['market_id']!r} is for {suffix}, not {team_id} ({tri})"
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
    if not isinstance(value, str) or not value.isascii() or not value.isdigit():
        raise AdapterError(f"{where}: timestamp {value!r} is not epoch milliseconds")
    # Epoch ms has 13 digits from 2001 to 2286; 10 digits is epoch SECONDS (RV-E4).
    if len(value) != 13:
        unit = "epoch seconds, not milliseconds" if len(value) == 10 else "not epoch milliseconds"
        raise AdapterError(f"{where}: timestamp {value!r} has {len(value)} digits: {unit}")
    ms = int(value)
    dt = datetime.fromtimestamp(ms // 1000, tz=UTC)
    frac = ms % 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + (f".{frac:03d}Z" if frac else "Z")
