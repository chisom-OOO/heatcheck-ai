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


class UpstreamRevisionError(RuntimeError):
    pass


def upstream_revision(repo: str | Path) -> str:
    """Upstream commit of a raw data checkout. Reads ``<repo>/COMMIT`` first. Falls back to git only when
    ``repo`` is itself the top level of a git checkout: ``git -C`` walks up the directories, so a
    bundled copy inside another repository must never resolve to that parent's HEAD."""
    import os
    import re
    import subprocess
    repo = Path(repo)
    commit_file = repo / "COMMIT"
    if commit_file.exists():
        rev = commit_file.read_text().strip()
        if not re.fullmatch(r"[0-9a-f]{40}", rev):
            raise UpstreamRevisionError(f"{commit_file} is not a 40-hex commit id")
        return rev
    try:
        top = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "--show-toplevel"], text=True,
                                      stderr=subprocess.DEVNULL).strip()
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise UpstreamRevisionError(f"{repo} has no COMMIT file and is not a git checkout") from exc
    if os.path.realpath(top) != os.path.realpath(repo):
        raise UpstreamRevisionError(f"{repo} has no COMMIT file and git resolves to a PARENT repository "
                                    f"({top}); refusing to record its HEAD as the upstream revision")
    return subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def et_date(ts_utc: pd.Series) -> pd.Series:
    return ts_utc.dt.tz_convert(ET).dt.date
