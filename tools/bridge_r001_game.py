"""Build the R-001 bundle for ONE real game (nba:0022300061) from Research's canonical tables.

    uv run --frozen python tools/bridge_r001_game.py <research_data_dir> [--out DIR] [--check]

<research_data_dir> is the output of Research's own build (incoming/research-20261107/scripts/
build_dataset.py): public.sqlite + restricted_labels.sqlite. Reads with stdlib sqlite3 in
read-only mode. Writes data/bundles/r001-nba-0022300061 (git-ignored: raw redistribution rights
are unverified). Also replays Research's builder on its NATIVE event rows and compares every
emitted feature value with the bridged rows, so translation errors are visible.
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from heatcheck.contracts.bundle import build_manifest, load_bundle, write_bundle  # noqa: E402
from heatcheck.contracts.records import FORMAT_VERSION, PROTOCOL_VERSION, sha256_hex  # noqa: E402
from heatcheck.contracts.research_bridge import (  # noqa: E402
    FEATURE_MAP,
    build_preshot_rows,
    research_features,
)

NBA_GAME = "0022300061"
GAME_ID = f"nba:{NBA_GAME}"
MODE = "REAL_NBA_RETROSPECTIVE"
INCOMING = ROOT / "incoming" / "research-20261107"
ACTIONS = {
    "rebound": "REBOUND", "turnover": "TURNOVER", "foul": "FOUL",
    "substitution": "SUBSTITUTION", "timeout": "TIMEOUT", "jumpball": "JUMP_BALL",
    "violation": "VIOLATION",
}
TRIP = re.compile(r"(\d+) of (\d+)")


def rec(rtype: str, rid: str, body: dict) -> dict:
    return {"protocol_version": PROTOCOL_VERSION, "format_version": FORMAT_VERSION,
            "record_type": rtype, "record_id": rid, "data_mode": MODE, "body": body}


def team(v) -> str | None:
    return None if v is None else f"nba-team:{int(v)}"


def player(v) -> str | None:
    return None if v in (None, 0) else f"nba-player:{int(v)}"


def dec(v: float | None) -> str | None:
    if v is None:
        return None
    d = Decimal(repr(float(v)))
    return format(d, "f")


def query(db: Path, sql: str, args=()) -> list[dict]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute(sql, args)]
    finally:
        con.close()


def snapshot_record() -> dict:
    ev = json.loads((INCOMING / "evidence" / "season_manifest_2023-24.json").read_text("utf-8"))
    snap = next(s for s in ev["raw_snapshots"] if s["path_in_upstream"].endswith("cdnnba_2023.tar.xz"))
    return rec("RAW_SNAPSHOT", snap["payload_sha256"], {
        "snapshot_sha256": snap["payload_sha256"],
        "provider": "cdnnba",
        "source": f"{snap['upstream']}@{snap['upstream_revision']}:{snap['path_in_upstream']}",
        "redacted_params": {},
        "retrieved_utc": snap["retrieval_utc"],
        "byte_count": snap.get("byte_count") or snap.get("bytes"),
        "media_type": "application/x-xz",
        "schema_version": "shufinskiy/nba_data cdnnba",
        "rights_note": snap["rights_note"] if "rights_note" in snap else ev["rights_note"],
        "bundle_path": None,
    }), snap


def event_record(r: dict, sid: str) -> dict:
    at = r["action_type"]
    shot = None
    if at in ("2pt", "3pt", "freethrow"):
        made = r["shot_result"] == "Made"
        if at == "freethrow":
            m = TRIP.search(r["sub_type"] or "")
            shot = {"kind": "FREE_THROW", "made": made, "points_if_made": 1,
                    "shot_type": r["sub_type"] or None, "distance_ft": None,
                    "assisted_post_outcome": None,
                    "free_throw_trip": ({"attempt": int(m[1]), "of": int(m[2])} if m else None)}
        else:
            shot = {"kind": "FIELD_GOAL", "made": made, "points_if_made": 3 if at == "3pt" else 2,
                    "shot_type": r["sub_type"] or None, "distance_ft": r["shot_distance"],
                    "assisted_post_outcome": (r["assist_person_id"] is not None) if made else None,
                    "free_throw_trip": None}
        action = "SHOT"
    elif at == "period":
        action = {"start": "PERIOD_START", "end": "PERIOD_END"}.get(r["sub_type"], "OTHER")
    else:
        action = ACTIONS.get(at, "OTHER")
    peid = str(r["provider_event_id"])
    return rec("EVENT", f"{GAME_ID}:{peid}:r1", {
        "game_id": GAME_ID, "provider": "cdnnba", "provider_event_id": peid, "revision": 1,
        "period": r["period"], "sequence": r["sequence"],
        "clock_seconds_remaining": dec(r["clock_sec_left"]),
        "event_time_utc": r["event_time_utc"], "team_id": team(r["team_id"]),
        "player_id": player(r["person_id"]), "action": action,
        "provider_action": f"{at}:{r['sub_type'] or ''}", "shot": shot,
        "source_snapshot_ids": [sid],
    })


def native_cross_check(data: Path, rows: list[dict], home_team: int) -> list[str]:
    """Run Research's builder on its own native rows; compare emitted values with the bridge."""
    import pandas as pd

    F = research_features()
    con = sqlite3.connect(f"file:{data / 'public.sqlite'}?mode=ro", uri=True)
    ev = pd.read_sql("SELECT * FROM events WHERE game_id = ?", con, params=[NBA_GAME])
    con.close()
    feat = F.add_shooter_margin(F.preshot_features(ev),
                                pd.DataFrame([{"game_id": NBA_GAME, "home_team_id": home_team}]))
    native = {int(r["sequence"]): r for r in feat.to_dict("records")}
    problems = []
    if len(native) != len(rows):
        problems.append(f"row count native {len(native)} vs bridge {len(rows)}")
    for r in rows:
        seq = r["body"]["cutoff"]["before_sequence"]
        n = native.get(seq)
        if n is None:
            problems.append(f"seq {seq}: no native row")
            continue
        for col, name in FEATURE_MAP.items():
            a, b = n.get(col), r["body"]["features"][name]["value"]
            a = None if a is None or (isinstance(a, float) and math.isnan(a)) else float(a)
            b = None if b is None else float(b)
            if a != b:
                problems.append(f"seq {seq} {name}: native {a} bridge {b}")
    return problems


def build(data: Path) -> tuple[dict, bytes, list[str], dict]:
    snap_rec, snap = snapshot_record()
    sid = snap_rec["record_id"]
    g = query(data / "public.sqlite", "SELECT * FROM games WHERE game_id = ?", (NBA_GAME,))[0]
    game = rec("GAME", GAME_ID, {
        "game_id": GAME_ID, "season": g["season"], "competition": "REGULAR_SEASON",
        "provider_ids": {"cdnnba": g["provider_game_id_cdnnba"]},
        "home_team_id": team(g["home_team_id"]), "away_team_id": team(g["away_team_id"]),
        "scheduled_tip_utc": None, "observed_tip_utc": g["tip_utc"],
        "status": g["status"], "source_snapshot_ids": [sid],
    })
    raw_events = query(data / "public.sqlite",
                       "SELECT * FROM events WHERE game_id = ? ORDER BY sequence", (NBA_GAME,))
    events = [event_record(r, sid) for r in raw_events]
    feats = build_preshot_rows(events, game["body"]["home_team_id"])
    peid_by_seq = {e["body"]["sequence"]: e["body"]["provider_event_id"] for e in events}

    gl = query(data / "restricted_labels.sqlite",
               "SELECT * FROM game_labels WHERE game_id = ?", (NBA_GAME,))[0]
    labels = [rec("RESTRICTED_LABEL", f"{GAME_ID}:final_score:r1", {
        "target_id": f"{GAME_ID}:final_score", "label_kind": "GAME_FINAL_SCORE",
        "game_id": GAME_ID, "value": {"home_points": gl["final_home"], "away_points": gl["final_away"]},
        "first_observed_utc": gl["finalization_utc"], "revision": 1,
        "reconciliation": "UNVERIFIED", "source_snapshot_ids": [sid]})]
    for s in query(data / "restricted_labels.sqlite",
                   "SELECT * FROM shot_labels WHERE game_id = ? ORDER BY sequence", (NBA_GAME,)):
        tid = f"{GAME_ID}:shot:{peid_by_seq[s['sequence']]}"
        labels.append(rec("RESTRICTED_LABEL", f"{tid}:r1", {
            "target_id": tid, "label_kind": "SHOT_MADE", "game_id": GAME_ID,
            "value": {"made": bool(s["made"])}, "first_observed_utc": s["first_observation_utc"],
            "revision": 1, "reconciliation": "UNVERIFIED", "source_snapshot_ids": [sid]}))

    with_rows = {r["body"]["target_id"] for r in feats}
    exclusions = [{"id": f"{GAME_ID}:shot:{e['body']['provider_event_id']}",
                   "reason": "no PRE_SHOT_MAKE row: Research preshot/1 emits field-goal rows only"}
                  for e in events if e["body"]["action"] == "SHOT"
                  and f"{GAME_ID}:shot:{e['body']['provider_event_id']}" not in with_rows]
    records = [snap_rec, game, *events, *feats, *labels]
    research_code = {p: sha256_hex((INCOMING / p).read_bytes())
                     for p in ("src/heatcheck/features.py", "src/heatcheck/canonical.py",
                               "scripts/build_dataset.py")}
    manifest, body = build_manifest(
        records, bundle_id=f"r001-{GAME_ID}", created_by_role="MAX",
        created_utc="2026-11-07T00:00:00Z",
        producer={"tool": "tools/bridge_r001_game.py", "version": "1",
                  "research_import": "incoming/research-20261107",
                  "research_code_sha256": json.dumps(research_code, sort_keys=True)},
        exclusions=exclusions,
        notes=("R-001 bridge of ONE real game. Events/labels from Research's canonical build of "
               f"{snap['source'] if 'source' in snap else snap['path_in_upstream']}. Final score "
               "UNVERIFIED: BALLDONTLIE NOT_RUN; Research's stats.nba.com check uses the same "
               "upstream repository. Scheduled tip unavailable; observed_tip_utc is the first "
               "play-by-play event. created_utc is fixed so rebuilds are byte-identical."),
    )
    return manifest, body, native_cross_check(data, feats, g["home_team_id"]), {"events": len(events)}


def main(argv: list[str]) -> int:
    data = Path(argv[0])
    out = ROOT / "data" / "bundles" / f"r001-nba-{NBA_GAME}"
    if "--out" in argv:
        out = Path(argv[argv.index("--out") + 1])
    manifest, body, problems, _ = build(data)
    if "--check" in argv:
        disk, _ = load_bundle(out)
        same = disk == manifest and (out / "records.jsonl").read_bytes() == body
        print(("PASS" if same else "FAIL") + f": rebuild records_sha256={manifest['records_sha256']}")
        return 0 if same else 1
    write_bundle(out, manifest, body, {})
    load_bundle(out)
    print(f"wrote {out} records_sha256={manifest['records_sha256']} counts={manifest['record_counts']}")
    print(f"exclusions={len(manifest['exclusions'])} native_vs_bridge_mismatches={len(problems)}")
    for p in problems[:40]:
        print("  MISMATCH", p)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
