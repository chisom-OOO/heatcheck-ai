"""UTC timestamps for every record this app writes: ISO 8601 with a trailing Z.

docs/DATA_FORMAT.md (heatcheck-records/1) writes UTC instants as ...Z, never +00:00.
"""
from datetime import UTC, datetime


def iso_z(dt):
    """Format an aware datetime as UTC with a Z suffix. Naive datetimes are refused."""
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("naive datetime refused; timestamps must carry a UTC offset")
    s = dt.astimezone(UTC).isoformat()
    assert s.endswith("+00:00"), s
    return s[:-6] + "Z"


def now_z():
    return iso_z(datetime.now(UTC))


def parse_utc(s):
    """Parse an ISO 8601 instant ('Z' or explicit offset) to an aware UTC datetime."""
    d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    if d.tzinfo is None:
        raise ValueError(f"timestamp {s!r} has no UTC offset")
    return d.astimezone(UTC)
