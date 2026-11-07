"""Max-owned bridge: run Research's imported pre-shot builder on heatcheck-records/1 EVENTs.

Translation only. Research's code is loaded unchanged from incoming/research-20261107 under
an alias package (its top-level name ``heatcheck`` would shadow this repository's). No
feature logic lives here: events are mapped to Research's column schema, Research's
``preshot_features`` and ``add_shooter_margin`` run as shipped, and their output columns are
renamed into FEATURE_ROW records. Free throws get no row because Research's builder emits
rows for field-goal attempts only.

Harness entry point: ``heatcheck.contracts.research_bridge:harness_builder``.
"""

from __future__ import annotations

import importlib.util
import math
import re
import sys
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any

from heatcheck.contracts.records import FORMAT_VERSION, PROTOCOL_VERSION, record_hash

ROOT = Path(__file__).resolve().parents[2]
RESEARCH_SRC = ROOT / "incoming" / "research-20261107" / "src" / "heatcheck"
ALIAS = "heatcheck_research_20261107"
BRIDGE_VERSION = "max-bridge/1"

# Research output column -> shared feature name. Only pre-shot columns are emitted.
FEATURE_MAP = {
    "margin_pre": "pre_shot_margin_shooting_team",
    "prior_fga": "player_prior_attempts_in_game",
    "prior_makes": "player_prior_makes_in_game",
    "period": "period",
    "clock_sec_left": "clock_seconds_remaining",
    "prev3_all_made": "prev3_all_made",
    "prev3_all_missed": "prev3_all_missed",
    "prev_shot_made": "prev_shot_made",
    "shot_value": "attempted_shot_value",
    "shot_distance": "shot_distance_ft",
}

_TRIP = re.compile(r"(\d+) of (\d+)")


def research_features() -> ModuleType:
    """Load Research's features.py unchanged, under an alias package name."""
    name = f"{ALIAS}.features"
    if name in sys.modules:
        return sys.modules[name]
    pkg_spec = importlib.util.spec_from_file_location(
        ALIAS, RESEARCH_SRC / "__init__.py", submodule_search_locations=[str(RESEARCH_SRC)]
    )
    pkg = importlib.util.module_from_spec(pkg_spec)
    sys.modules[ALIAS] = pkg
    pkg_spec.loader.exec_module(pkg)
    spec = importlib.util.spec_from_file_location(name, RESEARCH_SRC / "features.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def latest_revisions(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best: dict[tuple[str, str], dict[str, Any]] = {}
    for e in events:
        b = e["body"]
        key = (b["game_id"], b["provider_event_id"])
        if key not in best or b["revision"] > best[key]["body"]["revision"]:
            best[key] = e
    return sorted(best.values(), key=lambda e: (e["body"]["game_id"], e["body"]["sequence"]))


def _clock(value: str | None) -> float:
    return float("nan") if value is None else float(Decimal(value))


def events_to_research_frame(events: list[dict[str, Any]], home_team_id: str):
    """Map EVENT records of ONE game to the columns Research's builder reads."""
    import pandas as pd

    evs = latest_revisions(events)
    if len({e["body"]["game_id"] for e in evs}) != 1:
        raise ValueError("bridge handles exactly one game per call")
    rows, home, away = [], 0, 0
    last_clock: dict[int, float] = {}
    for e in evs:
        b, shot = e["body"], e["body"]["shot"]
        made = bool(shot and shot["made"])
        if made:  # running score AFTER this event, as the provider's score columns are
            if b["team_id"] == home_team_id:
                home += shot["points_if_made"]
            else:
                away += shot["points_if_made"]
        clock = _clock(b["clock_seconds_remaining"])
        prev = last_clock.get(b["period"])
        regress = int(prev is not None and not math.isnan(clock) and clock > prev)
        if not math.isnan(clock):
            last_clock[b["period"]] = clock
        is_fg = bool(shot and shot["kind"] == "FIELD_GOAL")
        if shot is None:
            action = b["action"].lower()
        elif is_fg:
            action = "3pt" if shot["points_if_made"] == 3 else "2pt"
        else:
            action = "freethrow"
        rows.append({
            "game_id": b["game_id"],
            "sequence": b["sequence"],
            "period": b["period"],
            "clock_sec_left": clock,
            "elapsed_sec": float("nan"),
            "team_id": b["team_id"],
            "person_id": b["player_id"],
            "action_type": action,
            "sub_type": (shot or {}).get("shot_type") or "",
            "qualifiers": "",
            "is_field_goal": int(is_fg),
            "shot_result": None if shot is None else ("Made" if made else "Missed"),
            "shot_distance": (shot or {}).get("distance_ft"),
            "area": None,
            "x": None,
            "y": None,
            "score_home_after": home,
            "score_away_after": away,
            "clock_regress": regress,
            "descriptor": None,
            "assist_person_id": None,
            "block_person_id": None,
            "_peid": b["provider_event_id"],
        })
    return pd.DataFrame(rows)


def research_rows_to_records(
    feat, events: list[dict[str, Any]], data_mode: str
) -> list[dict[str, Any]]:
    """Wrap Research's output rows as FEATURE_ROW records (inputs = strictly earlier events)."""
    evs = latest_revisions(events)
    by_seq = {e["body"]["sequence"]: e for e in evs}
    hashes = [(e["body"]["sequence"], record_hash(e)) for e in evs]
    out = []
    for row in feat.to_dict("records"):
        seq = int(row["sequence"])
        ev = by_seq[seq]["body"]
        game = ev["game_id"]
        target = f"{game}:shot:{ev['provider_event_id']}"
        prior = [h for s, h in hashes if s < seq]
        features = {}
        for col, name in FEATURE_MAP.items():
            v = row.get(col)
            if v is None or (isinstance(v, float) and math.isnan(v)):
                reason = ("ordering unresolved (clock regression in period)"
                          if row.get("ordering_unresolved") else "not available before this shot")
                features[name] = {"value": None, "missing_reason": reason}
            else:
                v = float(v) if isinstance(v, float) else int(v)
                features[name] = {"value": v, "missing_reason": None}
        features["ordering_unresolved"] = {
            "value": int(bool(row.get("ordering_unresolved"))), "missing_reason": None}
        out.append({
            "protocol_version": PROTOCOL_VERSION,
            "format_version": FORMAT_VERSION,
            "record_type": "FEATURE_ROW",
            "record_id": f"{target}:{row['feature_version']}",
            "data_mode": data_mode,
            "body": {
                "target_id": target,
                "target_kind": "PRE_SHOT_MAKE",
                "game_id": game,
                "cutoff": {"kind": "GAME_SEQUENCE", "utc": None, "game_id": game,
                           "before_sequence": seq},
                "feature_version": f"{row['feature_version']}+{BRIDGE_VERSION}",
                "features": features,
                "max_input_sequence": max((s for s, _ in hashes if s < seq), default=None),
                "max_input_available_utc": None,
                "availability_assumption": (
                    "RETROSPECTIVE: Research preshot/1 reads events with a smaller provider "
                    "sequence in the same game; bulk history has no publication times"),
                "source_record_hashes": sorted(set(prior)),
            },
        })
    return out


def build_preshot_rows(events: list[dict[str, Any]], home_team_id: str) -> list[dict[str, Any]]:
    import pandas as pd

    F = research_features()
    frame = events_to_research_frame(events, home_team_id)
    feat = F.preshot_features(frame.drop(columns=["_peid"]))
    games = pd.DataFrame([{"game_id": frame.game_id.iloc[0], "home_team_id": home_team_id}])
    feat = F.add_shooter_margin(feat, games)
    return research_rows_to_records(feat, events, events[0]["data_mode"])


def harness_builder(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Reviewer-harness entry point. Events carry no home flag, so one participant is taken
    as 'home' by sort order; the shooter-perspective margin does not depend on that choice."""
    teams = sorted({e["body"]["team_id"] for e in events if e["body"]["team_id"]})
    return build_preshot_rows(events, teams[0])
