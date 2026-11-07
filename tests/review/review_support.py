"""Independent-reviewer helpers. Not imported by product code.

Everything here is derived from docs/DATA_FORMAT.md and the task files, not from the
Research or Experience implementations, so it can be used to check them.
"""

from __future__ import annotations

import copy
import importlib
import json
import os
import socket
from collections import defaultdict
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from heatcheck.contracts.bundle import build_manifest, load_bundle, write_bundle
from heatcheck.contracts.records import (
    FORMAT_VERSION,
    PROTOCOL_VERSION,
    canonical_bytes,
    record_hash,
    sha256_hex,
    validate_record,
)

ROOT = Path(__file__).resolve().parents[2]
REF_BUNDLE = ROOT / "tests" / "fixtures" / "contracts" / "syn_reference_bundle"

# Candidate hooks. Unset means the candidate check is skipped and must be reported NOT_RUN.
ENV_RESEARCH_BUNDLE = "HEATCHECK_REVIEW_RESEARCH_BUNDLE"  # dir, e.g. data/bundles/r001-<game>
ENV_RESEARCH_SYN_BUNDLE = "HEATCHECK_REVIEW_RESEARCH_SYN_BUNDLE"  # committed synthetic fixture
ENV_FEATURE_BUILDER = "HEATCHECK_REVIEW_FEATURE_BUILDER"  # "module:function"
ENV_EXPERIENCE_BUNDLE = "HEATCHECK_REVIEW_EXPERIENCE_BUNDLE"  # default tests/fixtures/quotes/e001
# The project has not configured a freshness threshold yet (DATA_PIPELINE.md §4 step 4 asks
# for one). This default is a REVIEWER choice, recorded in the report, not a project rule.
ENV_STALE_SECONDS = "HEATCHECK_REVIEW_STALE_SECONDS"
DEFAULT_STALE_SECONDS = 60

SYN_SNAPSHOT = "0" * 63 + "1"


# --------------------------------------------------------------------------- generic helpers


def envelope(rtype: str, rid: str, mode: str, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "protocol_version": PROTOCOL_VERSION,
        "format_version": FORMAT_VERSION,
        "record_type": rtype,
        "record_id": rid,
        "data_mode": mode,
        "body": body,
    }


def reference_records() -> list[dict[str, Any]]:
    _, recs = load_bundle(REF_BUNDLE)
    return copy.deepcopy(recs)


def first(recs: list[dict[str, Any]], rtype: str) -> dict[str, Any]:
    return next(r for r in recs if r["record_type"] == rtype)


def of_type(recs: list[dict[str, Any]], rtype: str) -> list[dict[str, Any]]:
    return [r for r in recs if r["record_type"] == rtype]


def write_temp_bundle(tmp: Path, recs: list[dict[str, Any]], raw: dict[str, bytes]) -> Path:
    manifest, body = build_manifest(
        recs,
        bundle_id="review-probe",
        created_by_role="MAX",
        created_utc="2026-11-07T12:00:00Z",
        producer={"tool": "tests/review", "version": "1"},
    )
    write_bundle(tmp, manifest, body, raw)
    return tmp


def reference_raw() -> dict[str, bytes]:
    return {
        f"raw/{p.name}": p.read_bytes() for p in sorted((REF_BUNDLE / "raw").iterdir())
    }


def env_path(name: str, default: Path | None = None) -> Path | None:
    value = os.environ.get(name)
    if value:
        p = Path(value)
        return p if p.is_absolute() else ROOT / p
    return default if default is not None and default.exists() else None


def require_bundle(name: str, default: Path | None = None) -> tuple[dict, list[dict]]:
    path = env_path(name, default)
    if path is None:
        pytest.skip(f"NOT_RUN: set {name} to the candidate bundle directory")
    return load_bundle(path)


def load_callable(spec: str) -> Callable[..., Any]:
    module, _, attr = spec.partition(":")
    return getattr(importlib.import_module(module), attr)


def stale_seconds() -> int:
    return int(os.environ.get(ENV_STALE_SECONDS, DEFAULT_STALE_SECONDS))


class NetworkBlocked(RuntimeError):
    pass


@pytest.fixture()
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_a: Any, **_k: Any) -> None:
        raise NetworkBlocked("network disabled by reviewer test")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)


# --------------------------------------------------------------------------- synthetic game

GAME_ID = "syn:RV0001"
HOME = "syn-team:RVH"
AWAY = "syn-team:RVA"


def _event(seq: int, period: int, clock: str, action: str, team: str | None,
           player: str | None, shot: dict[str, Any] | None) -> dict[str, Any]:
    eid = f"e{seq}"
    return envelope("EVENT", f"{GAME_ID}:{eid}:r1", "SYNTHETIC", {
        "game_id": GAME_ID,
        "provider": "synthetic",
        "provider_event_id": eid,
        "revision": 1,
        "period": period,
        "sequence": seq,
        "clock_seconds_remaining": clock,
        "event_time_utc": None,
        "team_id": team,
        "player_id": player,
        "action": action,
        "provider_action": action.lower(),
        "shot": shot,
        "source_snapshot_ids": [SYN_SNAPSHOT],
    })


def _shot(kind: str, made: bool, pts: int, trip: tuple[int, int] | None = None,
          assisted: bool | None = None) -> dict[str, Any]:
    return {
        "kind": kind,
        "made": made,
        "points_if_made": pts,
        "shot_type": None,
        "distance_ft": None,
        "assisted_post_outcome": assisted,
        "free_throw_trip": None if trip is None else {"attempt": trip[0], "of": trip[1]},
    }


def synthetic_game() -> list[dict[str, Any]]:
    """An invented game: 4 periods + 1 overtime, both teams, FT trips, assisted makes,
    interleaved non-shot events and same-clock events. 8-8 after e18; ends 10-8 HOME in OT."""
    p1, p2, p3 = "syn-player:RV1", "syn-player:RV2", "syn-player:RV3"
    fg, ft = "FIELD_GOAL", "FREE_THROW"
    spec = [
        (1, "720.0", "PERIOD_START", None, None, None),
        (1, "700.0", "SHOT", HOME, p1, _shot(fg, True, 2, assisted=True)),
        (1, "690.0", "SHOT", AWAY, p3, _shot(fg, False, 3)),
        (1, "689.0", "REBOUND", HOME, p2, None),
        (1, "650.0", "SHOT", HOME, p1, _shot(fg, False, 2)),
        (1, "600.0", "FOUL", HOME, p2, None),
        (1, "600.0", "SHOT", AWAY, p3, _shot(ft, True, 1, (1, 2))),
        (1, "600.0", "SHOT", AWAY, p3, _shot(ft, False, 1, (2, 2))),
        (1, "0.0", "PERIOD_END", None, None, None),
        (2, "500.0", "SHOT", HOME, p2, _shot(fg, True, 3, assisted=True)),
        (3, "400.0", "SHOT", AWAY, p3, _shot(fg, True, 3)),
        (4, "10.0", "SHOT", HOME, p1, _shot(fg, False, 2)),
        (4, "5.0", "SHOT", AWAY, p3, _shot(fg, True, 2)),
        (4, "0.0", "PERIOD_END", None, None, None),
        (5, "300.0", "PERIOD_START", None, None, None),
        (5, "100.0", "SHOT", HOME, p1, _shot(fg, True, 2)),
        (5, "50.0", "SHOT", AWAY, p3, _shot(fg, True, 2)),
        (5, "1.0", "SHOT", HOME, p2, _shot(ft, True, 1, (1, 1))),
        (5, "1.0", "SHOT", HOME, p1, _shot(fg, True, 2)),
        (5, "0.0", "PERIOD_END", None, None, None),
    ]
    events = [_event(i + 1, *row) for i, row in enumerate(spec)]
    for e in events:
        validate_record(e)
    return events


def synthetic_game_header(status: str = "FINAL") -> dict[str, Any]:
    return envelope("GAME", GAME_ID, "SYNTHETIC", {
        "game_id": GAME_ID,
        "season": "2023-24",
        "competition": "REGULAR_SEASON",
        "provider_ids": {"synthetic": "RV0001"},
        "home_team_id": HOME,
        "away_team_id": AWAY,
        "scheduled_tip_utc": "2024-01-02T00:30:00Z",
        "status": status,
        "source_snapshot_ids": [SYN_SNAPSHOT],
    })


def flip_made(events: list[dict[str, Any]], index: int) -> list[dict[str, Any]]:
    out = copy.deepcopy(events)
    shot = out[index]["body"]["shot"]
    shot["made"] = not shot["made"]
    if not shot["made"]:
        shot["assisted_post_outcome"] = None  # a miss has no assist
    return out


def shot_indices(events: list[dict[str, Any]]) -> list[int]:
    return [i for i, e in enumerate(events) if e["body"]["action"] == "SHOT"]


# --------------------------------------------------------------------------- reference builder

MIN_FEATURES = (
    "pre_shot_margin_shooting_team",
    "player_prior_attempts_in_game",
    "player_prior_makes_in_game",
    "period",
    "clock_seconds_remaining",
)


def latest_revisions(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best: dict[tuple[str, str], dict[str, Any]] = {}
    for e in events:
        b = e["body"]
        key = (b["game_id"], b["provider_event_id"])
        if key not in best or b["revision"] > best[key]["body"]["revision"]:
            best[key] = e
    return sorted(best.values(), key=lambda e: e["body"]["sequence"])


def reference_features(events: list[dict[str, Any]], home: str, away: str) -> dict[str, dict]:
    """Reviewer's own minimum features keyed by provider_event_id of each shot.

    Uses only events with a strictly smaller provider sequence than the shot.
    """
    out: dict[str, dict] = {}
    evs = latest_revisions(events)
    for e in evs:
        b = e["body"]
        if b["action"] != "SHOT":
            continue
        prior = [p["body"] for p in evs if p["body"]["sequence"] < b["sequence"]]
        pts: dict[str, int] = defaultdict(int)
        for p in prior:
            if p["action"] == "SHOT" and p["shot"]["made"]:
                pts[p["team_id"]] += p["shot"]["points_if_made"]
        opp = away if b["team_id"] == home else home
        mine = [p for p in prior if p["action"] == "SHOT" and p["player_id"] == b["player_id"]]
        clock = b["clock_seconds_remaining"]
        out[b["provider_event_id"]] = {
            "pre_shot_margin_shooting_team": pts[b["team_id"]] - pts[opp],
            "player_prior_attempts_in_game": len(mine),
            "player_prior_makes_in_game": sum(1 for p in mine if p["shot"]["made"]),
            "period": b["period"],
            "clock_seconds_remaining": None if clock is None else float(Decimal(clock)),
        }
    return out


def reference_builder(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """FEATURE_ROW records built by the reviewer, used as the positive control."""
    game = events[0]["body"]["game_id"]
    mode = events[0]["data_mode"]
    teams = sorted({e["body"]["team_id"] for e in events if e["body"]["team_id"]})
    home, away = (HOME, AWAY) if set(teams) <= {HOME, AWAY} else (teams[0], teams[-1])
    feats = reference_features(events, home, away)
    by_id = {e["body"]["provider_event_id"]: e for e in latest_revisions(events)}
    rows = []
    for peid, f in feats.items():
        ev = by_id[peid]["body"]
        prior = [p for p in latest_revisions(events) if p["body"]["sequence"] < ev["sequence"]]
        rows.append(envelope("FEATURE_ROW", f"{game}:shot:{peid}:review-1", mode, {
            "target_id": f"{game}:shot:{peid}",
            "target_kind": "PRE_SHOT_MAKE",
            "game_id": game,
            "cutoff": {"kind": "GAME_SEQUENCE", "utc": None, "game_id": game,
                       "before_sequence": ev["sequence"]},
            "feature_version": "review-1",
            "features": {k: {"value": v, "missing_reason": None if v is not None else "none"}
                         for k, v in f.items()},
            "max_input_sequence": max((p["body"]["sequence"] for p in prior), default=None),
            "max_input_available_utc": None,
            "availability_assumption": "RETROSPECTIVE: strictly earlier provider sequence",
            "source_record_hashes": sorted({record_hash(p) for p in prior}),
        }))
    return rows


def leaky_builder(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Negative control: uses ``sequence <=`` so the current shot's outcome leaks in."""
    rows = reference_builder(events)
    evs = {e["body"]["provider_event_id"]: e["body"] for e in events}
    for r in rows:
        ev = evs[r["body"]["target_id"].rsplit(":", 1)[-1]]
        f = r["body"]["features"]["player_prior_makes_in_game"]
        f["value"] += int(ev["shot"]["made"])
    return rows


# --------------------------------------------------------------------------- invariance harness


def resolve_shot(row: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    """Map a FEATURE_ROW to its shot EVENT body by cutoff sequence or target_id suffix."""
    b = row["body"]
    shots = [e["body"] for e in latest_revisions(events) if e["body"]["action"] == "SHOT"
             and e["body"]["game_id"] == b["game_id"]]
    seq = b["cutoff"].get("before_sequence")
    by_seq = [s for s in shots if s["sequence"] == seq]
    by_tid = [s for s in shots if b["target_id"].endswith(":" + s["provider_event_id"])]
    if len(by_tid) == 1:
        return by_tid[0]
    if len(by_seq) == 1:
        return by_seq[0]
    raise AssertionError(f"cannot resolve FEATURE_ROW {b['target_id']} to exactly one shot")


def rows_by_shot(rows: list[dict[str, Any]], events: list[dict[str, Any]]) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    for r in rows:
        if r["body"]["target_kind"] != "PRE_SHOT_MAKE":
            continue
        peid = resolve_shot(r, events)["provider_event_id"]
        assert peid not in out, f"two PRE_SHOT_MAKE rows for shot {peid}"
        out[peid] = canonical_bytes(r)
    return out


def invariance_violations(builder: Callable[[list[dict]], list[dict]],
                          events: list[dict[str, Any]]) -> list[str]:
    """Flip every shot; the flipped shot's row and every earlier shot's row must not change."""
    base = rows_by_shot(builder(copy.deepcopy(events)), events)
    order = {e["body"]["provider_event_id"]: e["body"]["sequence"] for e in events}
    problems = []
    for i in shot_indices(events):
        flipped = flip_made(events, i)
        after = rows_by_shot(builder(copy.deepcopy(flipped)), flipped)
        peid = events[i]["body"]["provider_event_id"]
        for other, row in base.items():
            if order[other] <= order[peid] and after.get(other) != row:
                problems.append(f"flip {peid} changed row for shot {other}")
    return problems


def downstream_changes(builder: Callable[[list[dict]], list[dict]],
                       events: list[dict[str, Any]]) -> int:
    base = rows_by_shot(builder(copy.deepcopy(events)), events)
    n = 0
    for i in shot_indices(events):
        flipped = flip_made(events, i)
        after = rows_by_shot(builder(copy.deepcopy(flipped)), flipped)
        n += sum(1 for k in base if after.get(k) != base[k])
    return n


def raw_json(directory: Path, snapshot: dict[str, Any]) -> Any:
    path = snapshot["body"]["bundle_path"]
    if path is None:
        return None
    return json.loads((directory / path).read_bytes())


def walk_values(obj: Any, key: str = "") -> list[tuple[str, Any]]:
    out: list[tuple[str, Any]] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            out += walk_values(v, k)
    elif isinstance(obj, list):
        for v in obj:
            out += walk_values(v, key)
    else:
        out.append((key, obj))
    return out


__all__ = [n for n in dir() if not n.startswith("_")] + ["sha256_hex"]
