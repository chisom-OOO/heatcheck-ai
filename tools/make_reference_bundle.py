"""Regenerate the SYNTHETIC reference bundle for heatcheck-records/1.

Every value here is invented to exercise the format. It is not NBA data, not a
market observation and not a research result. Run:

    uv run python tools/make_reference_bundle.py [--check]
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from heatcheck.contracts.bundle import build_manifest, load_bundle, write_bundle  # noqa: E402
from heatcheck.contracts.records import (  # noqa: E402
    FORMAT_VERSION,
    PROTOCOL_VERSION,
    canonical_bytes,
    record_hash,
    sha256_hex,
)

OUT = ROOT / "tests" / "fixtures" / "contracts" / "syn_reference_bundle"
MODE = "SYNTHETIC"


def rec(rtype: str, rid: str, body: dict) -> dict:
    return {
        "protocol_version": PROTOCOL_VERSION,
        "format_version": FORMAT_VERSION,
        "record_type": rtype,
        "record_id": rid,
        "data_mode": MODE,
        "body": body,
    }


def build() -> tuple[dict, bytes, dict[str, bytes]]:
    pbp_payload = canonical_bytes(
        {"note": "INVENTED play-by-play payload for format tests", "rows": 3}
    ) + b"\n"
    book_payload = canonical_bytes(
        {"note": "INVENTED order book payload for format tests", "bids": [["0.52", "100"]],
         "asks": [["0.56", "40"]]}
    ) + b"\n"
    pbp_sha, book_sha = sha256_hex(pbp_payload), sha256_hex(book_payload)
    raw = {f"raw/{pbp_sha}.json": pbp_payload, f"raw/{book_sha}.json": book_payload}

    def snapshot(sha: str, data: bytes, provider: str, source: str) -> dict:
        return rec("RAW_SNAPSHOT", sha, {
            "snapshot_sha256": sha,
            "provider": provider,
            "source": source,
            "redacted_params": {},
            "retrieved_utc": "2026-11-07T12:00:00Z",
            "byte_count": len(data),
            "media_type": "application/json",
            "schema_version": "synthetic-1",
            "rights_note": "Invented test data; freely redistributable within this repository.",
            "bundle_path": f"raw/{sha}.json",
        })

    game_id = "syn:G0001"
    home, away = "syn-team:HOME", "syn-team:AWAY"
    game = rec("GAME", game_id, {
        "game_id": game_id,
        "season": "2023-24",
        "competition": "REGULAR_SEASON",
        "provider_ids": {"synthetic": "G0001"},
        "home_team_id": home,
        "away_team_id": away,
        "scheduled_tip_utc": "2024-01-01T00:30:00Z",
        "status": "FINAL",
        "source_snapshot_ids": [pbp_sha],
    })

    def event(seq: int, action: str, team: str | None, player: str | None, shot=None) -> dict:
        return rec("EVENT", f"{game_id}:e{seq}:r1", {
            "game_id": game_id,
            "provider": "synthetic",
            "provider_event_id": f"e{seq}",
            "revision": 1,
            "period": 1,
            "sequence": seq,
            "clock_seconds_remaining": f"{720 - 10 * seq}.0",
            "event_time_utc": None,
            "team_id": team,
            "player_id": player,
            "action": action,
            "provider_action": action.lower(),
            "shot": shot,
            "source_snapshot_ids": [pbp_sha],
        })

    def fg(made: bool, points: int) -> dict:
        return {"kind": "FIELD_GOAL", "made": made, "points_if_made": points, "shot_type": None,
                "distance_ft": None, "assisted_post_outcome": None, "free_throw_trip": None}

    e1 = event(1, "PERIOD_START", None, None)
    e2 = event(2, "SHOT", home, "syn-player:P1", fg(True, 2))
    e3 = event(3, "SHOT", home, "syn-player:P1", fg(False, 3))

    feature = rec("FEATURE_ROW", f"{game_id}:shot:e3:v1", {
        "target_id": f"{game_id}:shot:e3",
        "target_kind": "PRE_SHOT_MAKE",
        "game_id": game_id,
        "cutoff": {"kind": "GAME_SEQUENCE", "utc": None, "game_id": game_id,
                   "before_sequence": 3},
        "feature_version": "synthetic-preshot-1",
        "features": {
            "pre_shot_margin_shooting_team": {"value": 2, "missing_reason": None},
            "player_prior_attempts_in_game": {"value": 1, "missing_reason": None},
            "shot_distance_ft": {"value": None, "missing_reason": "not supplied by provider"},
        },
        "max_input_sequence": 2,
        "max_input_available_utc": None,
        "availability_assumption": "RETROSPECTIVE: events strictly earlier in provider sequence",
        "source_record_hashes": sorted([record_hash(e1), record_hash(e2)]),
    })
    label = rec("RESTRICTED_LABEL", f"{game_id}:final_score:r1", {
        "target_id": f"{game_id}:final_score",
        "label_kind": "GAME_FINAL_SCORE",
        "game_id": game_id,
        "value": {"home_points": 2, "away_points": 0},
        "first_observed_utc": None,
        "revision": 1,
        "reconciliation": "UNVERIFIED",
        "source_snapshot_ids": [pbp_sha],
    })
    market = rec("VENUE_MARKET", "SYNTHETIC_VENUE:M1", {
        "venue": "SYNTHETIC_VENUE",
        "venue_api_version": "synthetic-1",
        "event_id": "EV1",
        "market_id": "M1",
        "title": "Invented: Will HOME beat AWAY?",
        "outcomes": [{"contract_id": "M1-YES", "label": "HOME"},
                     {"contract_id": "M1-NO", "label": "AWAY"}],
        "rules_text_sha256": None,
        "settlement_source": None,
        "price_unit": "PROBABILITY_DOLLARS",
        "quantity_unit": "CONTRACTS",
        "tick_size": "0.01",
        "source_snapshot_ids": [book_sha],
    })
    mapping = rec("VENUE_MAPPING", "map:syn:G0001:M1-YES", {
        "mapping_id": "map:syn:G0001:M1-YES",
        "game_id": game_id,
        "venue_market_record_id": "SYNTHETIC_VENUE:M1",
        "contract_id": "M1-YES",
        "team_id": home,
        "outcome_direction": "TEAM_WINS",
        "overtime_convention": "UNKNOWN",
        "cancel_postpone_convention": "UNKNOWN",
        "status": "BLOCKED_RULES_UNVERIFIED",
        "reason": "Invented market; no rules text exists.",
        "mapping_provenance": "hand-written synthetic fixture",
    })
    quote = rec("QUOTE", f"quote:map:syn:G0001:M1-YES:{book_sha[:16]}", {
        "mapping_id": "map:syn:G0001:M1-YES",
        "venue": "SYNTHETIC_VENUE",
        "market_id": "M1",
        "contract_id": "M1-YES",
        "levels": [
            {"side": "BID", "price": "0.52", "size": "100", "derivation": "DIRECT"},
            {"side": "ASK", "price": "0.56", "size": "40", "derivation": "DIRECT"},
        ],
        "provider_time_utc": None,
        "fetch_start_utc": "2024-01-01T00:00:00Z",
        "received_utc": "2024-01-01T00:00:00.250Z",
        "adapter_version": "synthetic-1",
        "status": "OK",
        "status_reason": None,
        "raw_snapshot_id": book_sha,
    })
    records = [
        snapshot(pbp_sha, pbp_payload, "synthetic", "tools/make_reference_bundle.py"),
        snapshot(book_sha, book_payload, "synthetic", "tools/make_reference_bundle.py"),
        game, e1, e2, e3, feature, label, market, mapping, quote,
    ]
    manifest, body = build_manifest(
        records,
        bundle_id="syn-reference-1",
        created_by_role="MAX",
        created_utc="2026-11-07T00:00:00Z",
        producer={"tool": "tools/make_reference_bundle.py", "version": "1"},
        notes="SYNTHETIC format reference. Invented values; not NBA or market data.",
    )
    return manifest, body, raw


def main() -> int:
    manifest, body, raw = build()
    if "--check" in sys.argv:
        on_disk, _ = load_bundle(OUT)
        if on_disk != manifest or (OUT / "records.jsonl").read_bytes() != body:
            print("FAIL: committed reference bundle differs from generator output")
            return 1
        print(f"PASS: reference bundle reproducible, records_sha256={manifest['records_sha256']}")
        return 0
    write_bundle(OUT, manifest, body, raw)
    load_bundle(OUT)
    print(f"wrote {OUT.relative_to(ROOT)} records_sha256={manifest['records_sha256']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
