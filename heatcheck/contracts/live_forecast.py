"""Live forecast file heatcheck-live-forecast/1 (Research's data/live/forecasts.json).

Pure, stdlib-only validation. No HTTP, provider, database or file side effects; callers read
the bytes. Specification: docs/LIVE_FORECAST_FORMAT.md.

A file is a SAMPLE when its ``source.results`` starts with "SAMPLE". A sample may use the
literal "SAMPLE" in place of ``fetched_utc`` and ``sha256`` so it never carries an invented
provenance hash. A non-sample file may not contain "SAMPLE" anywhere in ``source``.
Consumers must show ``is_sample`` and never present sample values as real.

    uv run --frozen python -m heatcheck.contracts.live_forecast PATH [PATH ...]
"""

from __future__ import annotations

import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from heatcheck.contracts.records import RecordError, loads_strict, parse_utc, validate_utc

FORMAT = "heatcheck-live-forecast/1"
LABEL = "DESCRIPTIVE FORECAST"
SAMPLE = "SAMPLE"
MAX_GAMES = 500
MAX_STRING = 512
MAX_BYTES = 2 * 1024 * 1024

TOP_FIELDS = (
    "format", "label", "model", "inputs_used", "data_cutoff_utc", "source", "backtest_2024_25", "games",
)
SOURCE_FIELDS = ("results", "fetched_utc", "sha256", "cross_check")
BACKTEST_FIELDS = ("log_loss", "brier", "games")
GAME_FIELDS = (
    "game_id", "tip_utc", "home_team_id", "away_team_id", "home_team", "away_team",
    "p_home_win", "elo_home", "elo_away",
)

NBA_GAME_RE = re.compile(r"^nba:\d{10}$")
NBA_TEAM_RE = re.compile(r"^nba-team:\d{1,12}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
INPUT_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
CROSS_CHECK_RE = re.compile(r"^(NOT_RUN|balldontlie\b.*)$", re.S)


class LiveForecastError(RecordError):
    """The file violates heatcheck-live-forecast/1. ``path`` locates the offending field."""


@dataclass(frozen=True)
class LiveForecast:
    doc: dict[str, Any]
    is_sample: bool


def _fail(path: str, message: str) -> None:
    raise LiveForecastError(path, message)


def _exact_keys(obj: Any, fields: tuple[str, ...], path: str) -> dict[str, Any]:
    if not isinstance(obj, dict):
        _fail(path, "expected object")
    missing = [f for f in fields if f not in obj]
    if missing:
        _fail(f"{path}.{missing[0]}", "required field missing")
    unknown = sorted(set(obj) - set(fields))
    if unknown:
        _fail(path, f"unknown fields {unknown}")
    return obj


def _text(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_STRING:
        _fail(path, f"expected non-empty string of at most {MAX_STRING} chars")
    return value


def _num(value: Any, path: str, lo: float | None = None, hi: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        _fail(path, "expected finite number")
    if lo is not None and value < lo:
        _fail(path, f"expected >= {lo}")
    if hi is not None and value > hi:
        _fail(path, f"expected <= {hi}")
    return float(value)


def _utc(value: Any, path: str) -> None:
    try:
        validate_utc(value, path)
    except RecordError as exc:
        raise LiveForecastError(exc.path, exc.message) from None


def _source(src: Any, path: str) -> bool:
    src = _exact_keys(src, SOURCE_FIELDS, path)
    for f in SOURCE_FIELDS:
        _text(src[f], f"{path}.{f}")
    is_sample = src["results"].startswith(SAMPLE)
    if not is_sample:
        for f in SOURCE_FIELDS:
            if SAMPLE in src[f]:
                _fail(f"{path}.{f}", "contains SAMPLE but source.results does not start with SAMPLE")
    if not (is_sample and src["fetched_utc"] == SAMPLE):
        _utc(src["fetched_utc"], f"{path}.fetched_utc")
    if not (is_sample and src["sha256"] == SAMPLE) and not SHA_RE.match(src["sha256"]):
        _fail(f"{path}.sha256", "expected lowercase sha256 hex" + (" or SAMPLE" if is_sample else ""))
    if not CROSS_CHECK_RE.match(src["cross_check"]):
        _fail(f"{path}.cross_check", "expected 'NOT_RUN' or a result starting with 'balldontlie'")
    return is_sample


def validate_live_forecast(doc: Any) -> LiveForecast:
    """Validate a parsed heatcheck-live-forecast/1 document. Raises LiveForecastError."""
    doc = _exact_keys(doc, TOP_FIELDS, "$")
    if doc["format"] != FORMAT:
        _fail("$.format", f"expected {FORMAT!r}")
    if doc["label"] != LABEL:
        _fail("$.label", f"expected {LABEL!r}")
    _text(doc["model"], "$.model")

    inputs = doc["inputs_used"]
    if not isinstance(inputs, list) or not inputs or len(inputs) > 64:
        _fail("$.inputs_used", "expected list of 1..64 input names")
    for i, name in enumerate(inputs):
        if not isinstance(name, str) or not INPUT_RE.match(name):
            _fail(f"$.inputs_used[{i}]", "expected snake_case input name")
    if len(set(inputs)) != len(inputs):
        _fail("$.inputs_used", "input names must be unique")

    _utc(doc["data_cutoff_utc"], "$.data_cutoff_utc")
    cutoff = parse_utc(doc["data_cutoff_utc"])
    is_sample = _source(doc["source"], "$.source")

    bt = _exact_keys(doc["backtest_2024_25"], BACKTEST_FIELDS, "$.backtest_2024_25")
    _num(bt["log_loss"], "$.backtest_2024_25.log_loss", lo=0.0)
    _num(bt["brier"], "$.backtest_2024_25.brier", lo=0.0, hi=1.0)
    if isinstance(bt["games"], bool) or not isinstance(bt["games"], int) or bt["games"] < 0:
        _fail("$.backtest_2024_25.games", "expected integer >= 0")

    games = doc["games"]
    if not isinstance(games, list) or len(games) > MAX_GAMES:
        _fail("$.games", f"expected list of at most {MAX_GAMES} games")
    seen: set[str] = set()
    for i, g in enumerate(games):
        p = f"$.games[{i}]"
        g = _exact_keys(g, GAME_FIELDS, p)
        if not isinstance(g["game_id"], str) or not NBA_GAME_RE.match(g["game_id"]):
            _fail(f"{p}.game_id", "expected 'nba:' plus the 10-digit NBA game id")
        if g["game_id"] in seen:
            _fail(f"{p}.game_id", "duplicate game_id")
        seen.add(g["game_id"])
        _utc(g["tip_utc"], f"{p}.tip_utc")
        if not parse_utc(g["tip_utc"]) > cutoff:
            _fail(f"{p}.tip_utc", "data_cutoff_utc must be strictly before every tip_utc")
        for side in ("home_team_id", "away_team_id"):
            if not isinstance(g[side], str) or not NBA_TEAM_RE.match(g[side]):
                _fail(f"{p}.{side}", "expected 'nba-team:<NBA team id>'")
        if g["home_team_id"] == g["away_team_id"]:
            _fail(f"{p}.away_team_id", "home and away team ids are the same")
        _text(g["home_team"], f"{p}.home_team")
        _text(g["away_team"], f"{p}.away_team")
        _num(g["p_home_win"], f"{p}.p_home_win", lo=0.0, hi=1.0)
        _num(g["elo_home"], f"{p}.elo_home", lo=0.0)
        _num(g["elo_away"], f"{p}.elo_away", lo=0.0)
    return LiveForecast(doc=doc, is_sample=is_sample)


def parse_live_forecast(raw: bytes) -> LiveForecast:
    """Strictly decode (UTF-8, no NaN/Infinity, no duplicate keys) and validate."""
    if len(raw) > MAX_BYTES:
        raise LiveForecastError("$", f"file larger than {MAX_BYTES} bytes")
    try:
        doc = loads_strict(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise LiveForecastError("$", f"not strict UTF-8 JSON ({exc})") from None
    return validate_live_forecast(doc)


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    status = 0
    for arg in argv:
        try:
            lf = parse_live_forecast(Path(arg).read_bytes())
        except (LiveForecastError, OSError) as exc:
            print(f"FAIL {arg}: {exc}")
            status = 1
            continue
        kind = "SAMPLE (not real data)" if lf.is_sample else "non-sample"
        print(f"PASS {arg}: {FORMAT} {kind}, games={len(lf.doc['games'])}, "
              f"cutoff={lf.doc['data_cutoff_utc']}")
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
