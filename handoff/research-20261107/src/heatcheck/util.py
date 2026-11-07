"""Shared helpers: canonical hashing and time conventions."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

ET = ZoneInfo("America/New_York")
PROTOCOL = "heatcheck-nba/1"


def sha256_file(path: str | Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while b := f.read(chunk):
            h.update(b)
    return h.hexdigest()


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def canonical_json(obj) -> bytes:
    """Deterministic JSON: sorted keys, no whitespace, NaN forbidden."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode()


def frame_hash(df: pd.DataFrame, sort_by: list[str]) -> str:
    """Logical hash of a table: independent of row order and of retrieval metadata.

    Values are serialised via a fixed CSV dialect after sorting; floats use repr-stable
    formatting so reruns on identical input give identical bytes.
    """
    d = df.sort_values(sort_by, kind="mergesort").reset_index(drop=True)
    d = d[sorted(d.columns)]
    csv = d.to_csv(index=False, lineterminator="\n", float_format="%.12g", na_rep="\\N")
    return sha256_bytes(csv.encode())


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def et_date(ts_utc: pd.Series) -> pd.Series:
    return ts_utc.dt.tz_convert(ET).dt.date
