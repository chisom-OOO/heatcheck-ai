"""Read, write and validate heatcheck-records/1 bundle directories (offline, no network).

A bundle is::

    <bundle>/manifest.json   canonical JSON manifest
    <bundle>/records.jsonl   canonical records, sorted, one per line
    <bundle>/raw/<sha256>.<ext>   raw payloads that may be redistributed

Usage: ``python -m heatcheck.contracts.bundle <bundle_dir> [<bundle_dir> ...]``
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any

from heatcheck.contracts.records import (
    FORMAT_VERSION,
    PROTOCOL_VERSION,
    RECORD_TYPES,
    RecordError,
    canonical_bytes,
    encode_records,
    loads_strict,
    parse_utc,
    record_hash,
    sha256_hex,
    validate_record,
    validate_utc,
)

MAX_FILE_BYTES = 64 * 1024 * 1024
ROLES = ("MAX", "RESEARCH", "EXPERIENCE")
MANIFEST_FIELDS = {
    "protocol_version",
    "format_version",
    "bundle_id",
    "created_by_role",
    "created_utc",
    "producer",
    "records_sha256",
    "record_counts",
    "data_modes",
    "exclusions",
    "notes",
}


class BundleError(ValueError):
    pass


def build_manifest(
    records: list[dict[str, Any]],
    *,
    bundle_id: str,
    created_by_role: str,
    created_utc: str,
    producer: dict[str, str],
    exclusions: list[dict[str, str]] | None = None,
    notes: str = "",
) -> tuple[dict[str, Any], bytes]:
    """Return (manifest, records_bytes) for ``records``. Pure; writes nothing."""
    body = encode_records(records)
    counts = Counter(r["record_type"] for r in records)
    manifest = {
        "protocol_version": PROTOCOL_VERSION,
        "format_version": FORMAT_VERSION,
        "bundle_id": bundle_id,
        "created_by_role": created_by_role,
        "created_utc": created_utc,
        "producer": producer,
        "records_sha256": sha256_hex(body),
        "record_counts": {t: counts[t] for t in RECORD_TYPES if counts[t]},
        "data_modes": sorted({r["data_mode"] for r in records}),
        "exclusions": exclusions or [],
        "notes": notes,
    }
    return manifest, body


def write_bundle(
    directory: Path, manifest: dict[str, Any], records_bytes: bytes, raw: dict[str, bytes]
) -> None:
    """Write a bundle. ``raw`` maps bundle-relative path (raw/...) to payload bytes."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "records.jsonl").write_bytes(records_bytes)
    (directory / "manifest.json").write_bytes(canonical_bytes(manifest) + b"\n")
    for rel, data in raw.items():
        target = _safe_join(directory, rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


def _safe_join(directory: Path, rel: str) -> Path:
    p = PurePosixPath(rel)
    if p.is_absolute() or ".." in p.parts or not p.parts or p.parts[0] != "raw" or "\\" in rel:
        raise BundleError(f"unsafe bundle path {rel!r}; must be relative under raw/")
    return directory.joinpath(*p.parts)


def _read_capped(path: Path) -> bytes:
    if not path.is_file():
        raise BundleError(f"missing file {path.name}")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise BundleError(f"{path.name} exceeds {MAX_FILE_BYTES} bytes")
    return path.read_bytes()


def load_bundle(directory: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Load and fully validate a bundle. Raises BundleError/RecordError on any defect."""
    directory = Path(directory)
    manifest_bytes = _read_capped(directory / "manifest.json")
    manifest = loads_strict(manifest_bytes.decode("utf-8"))
    if not isinstance(manifest, dict) or set(manifest) != MANIFEST_FIELDS:
        raise BundleError(f"manifest fields must be exactly {sorted(MANIFEST_FIELDS)}")
    if manifest_bytes != canonical_bytes(manifest) + b"\n":
        raise BundleError("manifest.json is not canonical JSON")
    if manifest["protocol_version"] != PROTOCOL_VERSION:
        raise BundleError("manifest protocol_version mismatch")
    if manifest["format_version"] != FORMAT_VERSION:
        raise BundleError("manifest format_version mismatch")
    if manifest["created_by_role"] not in ROLES:
        raise BundleError(f"created_by_role must be one of {ROLES}")
    try:
        validate_utc(manifest["created_utc"], "manifest.created_utc")  # RV-U9
    except RecordError as exc:
        raise BundleError(str(exc)) from None

    body = _read_capped(directory / "records.jsonl")
    if sha256_hex(body) != manifest["records_sha256"]:
        raise BundleError("records.jsonl sha256 does not match manifest")
    records = []
    for lineno, line in enumerate(body.decode("utf-8").splitlines(), start=1):
        try:
            record = loads_strict(line)
            validate_record(record)
        except (RecordError, ValueError) as exc:
            raise BundleError(f"records.jsonl line {lineno}: {exc}") from None
        records.append(record)
    if encode_records(records) != body:
        raise BundleError("records.jsonl is not in canonical sorted form")

    counts = Counter(r["record_type"] for r in records)
    if manifest["record_counts"] != {t: counts[t] for t in RECORD_TYPES if counts[t]}:
        raise BundleError("manifest record_counts do not match records")
    if manifest["data_modes"] != sorted({r["data_mode"] for r in records}):
        raise BundleError("manifest data_modes do not match records")

    _check_references(directory, records)
    return manifest, records


def _check_references(directory: Path, records: list[dict[str, Any]]) -> None:
    by_type: dict[str, dict[str, dict[str, Any]]] = {t: {} for t in RECORD_TYPES}
    for r in records:
        key = (r["record_type"], r["record_id"])
        if r["record_id"] in by_type[r["record_type"]]:
            raise BundleError(f"duplicate record_id {key}")
        by_type[r["record_type"]][r["record_id"]] = r

    snapshots = {r["body"]["snapshot_sha256"]: r for r in by_type["RAW_SNAPSHOT"].values()}
    for r in by_type["RAW_SNAPSHOT"].values():
        b = r["body"]
        if r["record_id"] != b["snapshot_sha256"]:
            raise BundleError("RAW_SNAPSHOT record_id must equal snapshot_sha256")
        if b["bundle_path"] is not None:
            data = _read_capped(_safe_join(directory, b["bundle_path"]))
            if sha256_hex(data) != b["snapshot_sha256"]:
                raise BundleError(f"raw payload hash mismatch for {b['bundle_path']}")
            if len(data) != b["byte_count"]:
                raise BundleError(f"raw payload byte_count mismatch for {b['bundle_path']}")

    games = {r["body"]["game_id"]: r for r in by_type["GAME"].values()}
    for r in by_type["GAME"].values():
        if r["record_id"] != r["body"]["game_id"]:
            raise BundleError("GAME record_id must equal game_id")
    markets = by_type["VENUE_MARKET"]
    mappings = {r["body"]["mapping_id"]: r for r in by_type["VENUE_MAPPING"].values()}

    for r in records:
        b = r["body"]
        rid = f"{r['record_type']}:{r['record_id']}"
        for sid in b.get("source_snapshot_ids", []):
            if sid not in snapshots:
                raise BundleError(f"{rid} references unknown snapshot {sid}")
        if r["record_type"] in ("EVENT", "FEATURE_ROW", "RESTRICTED_LABEL", "VENUE_MAPPING"):
            if b["game_id"] not in games:
                raise BundleError(f"{rid} references game {b['game_id']} not in bundle")
            game_mode = games[b["game_id"]]["data_mode"]
            if (game_mode == "SYNTHETIC") != (r["data_mode"] == "SYNTHETIC"):
                raise BundleError(f"{rid} synthetic/real mismatch with its game")
            if r["record_type"] != "VENUE_MAPPING" and game_mode != r["data_mode"]:
                raise BundleError(f"{rid} NBA record must share its game's data_mode")
        if r["record_type"] == "VENUE_MAPPING":
            market = markets.get(b["venue_market_record_id"])
            if market is None:
                raise BundleError(f"{rid} references unknown VENUE_MARKET")
            contracts = {o["contract_id"] for o in market["body"]["outcomes"]}
            if b["contract_id"] not in contracts:
                raise BundleError(f"{rid} contract_id not an outcome of its market")
            game = games[b["game_id"]]["body"]
            if b["team_id"] not in (game["home_team_id"], game["away_team_id"]):
                raise BundleError(f"{rid} team_id is not a participant of the game")
        if r["record_type"] == "QUOTE":
            if b["raw_snapshot_id"] not in snapshots:
                raise BundleError(f"{rid} references unknown raw snapshot")
            mapping = mappings.get(b["mapping_id"])
            if mapping is None:
                raise BundleError(f"{rid} references unknown mapping {b['mapping_id']}")
            # RV-U8: the raw book must have been retrieved inside the quote's fetch window.
            retrieved = parse_utc(snapshots[b["raw_snapshot_id"]]["body"]["retrieved_utc"])
            if not parse_utc(b["fetch_start_utc"]) <= retrieved <= parse_utc(b["received_utc"]):
                raise BundleError(f"{rid} raw snapshot retrieved_utc is outside its fetch window")
            market = markets[mapping["body"]["venue_market_record_id"]]["body"]
            if (b["venue"], b["market_id"], b["contract_id"]) != (
                market["venue"],
                market["market_id"],
                mapping["body"]["contract_id"],
            ):
                raise BundleError(f"{rid} venue/market/contract disagree with its mapping")

    _check_nba_consistency(by_type, games)


def _check_nba_consistency(
    by_type: dict[str, dict[str, dict[str, Any]]], games: dict[str, dict[str, Any]]
) -> None:
    """Cross-record NBA checks: events, feature rows and labels must agree with each other."""
    # Latest revision of each shot EVENT, keyed by its target id <game_id>:shot:<event id>.
    shots: dict[str, dict[str, Any]] = {}
    for r in by_type["EVENT"].values():
        b = r["body"]
        if b["action"] == "SHOT":
            key = f"{b['game_id']}:shot:{b['provider_event_id']}"
            if key not in shots or b["revision"] > shots[key]["body"]["revision"]:
                shots[key] = r
    event_by_hash = {record_hash(r): r for r in by_type["EVENT"].values()}

    for r in by_type["EVENT"].values():
        b = r["body"]
        game = games[b["game_id"]]["body"]
        # RV-G1: an event's team must be a participant of its game.
        if b["team_id"] is not None and b["team_id"] not in (
            game["home_team_id"],
            game["away_team_id"],
        ):
            raise BundleError(f"EVENT:{r['record_id']} team_id is not home or away of its game")

    for r in by_type["FEATURE_ROW"].values():
        b = r["body"]
        rid = f"FEATURE_ROW:{r['record_id']}"
        if b["target_kind"] == "PRE_SHOT_MAKE":
            # RV-G2: a shot target belongs to the row's own game (<game_id>:shot:<event id>).
            if not b["target_id"].startswith(f"{b['game_id']}:shot:"):
                raise BundleError(f"{rid} target {b['target_id']} is not a shot of {b['game_id']}")
            target = shots.get(b["target_id"])
            cutoff = b["cutoff"]
            if target is not None and cutoff["kind"] == "GAME_SEQUENCE":
                # RV-L3: the cutoff may not fall after the target shot itself.
                if cutoff["before_sequence"] > target["body"]["sequence"]:
                    raise BundleError(
                        f"{rid} cutoff before_sequence {cutoff['before_sequence']} is after its "
                        f"target shot (sequence {target['body']['sequence']})"
                    )
            # RV-L4: no input may be the target shot's own EVENT, or a same-game EVENT at or
            # after the cutoff sequence.
            for h in b["source_record_hashes"]:
                ev = event_by_hash.get(h)
                if ev is None:
                    continue
                if target is not None and h == record_hash(target):
                    raise BundleError(f"{rid} lists its own target shot EVENT as an input")
                if (
                    cutoff["kind"] == "GAME_SEQUENCE"
                    and ev["body"]["game_id"] == b["game_id"]
                    and ev["body"]["sequence"] >= cutoff["before_sequence"]
                ):
                    raise BundleError(
                        f"{rid} input EVENT sequence {ev['body']['sequence']} is not before the "
                        f"cutoff {cutoff['before_sequence']}"
                    )

    # Made-shot points per (game, team), from the latest revision of each shot.
    points: dict[tuple[str, str], int] = {}
    for r in shots.values():
        b = r["body"]
        if b["shot"]["made"] and b["team_id"] is not None:
            key = (b["game_id"], b["team_id"])
            points[key] = points.get(key, 0) + b["shot"]["points_if_made"]
    games_with_shots = {r["body"]["game_id"] for r in shots.values()}

    for r in by_type["RESTRICTED_LABEL"].values():
        b = r["body"]
        rid = f"RESTRICTED_LABEL:{r['record_id']}"
        game = games[b["game_id"]]["body"]
        if b["label_kind"] == "GAME_FINAL_SCORE" and b["game_id"] in games_with_shots:
            # RV-O1: a final score in the same bundle as the play-by-play must equal the
            # made-shot totals with home/away identity preserved.
            home = points.get((b["game_id"], game["home_team_id"]), 0)
            away = points.get((b["game_id"], game["away_team_id"]), 0)
            if (b["value"]["home_points"], b["value"]["away_points"]) != (home, away):
                raise BundleError(
                    f"{rid} final score home {b['value']['home_points']}-away "
                    f"{b['value']['away_points']} contradicts EVENT made-shot totals "
                    f"home {home}-away {away}"
                )
        if b["label_kind"] == "SHOT_MADE":
            # RV-O2: a shot label must agree with the shot EVENT it names.
            target = shots.get(b["target_id"])
            if target is not None and target["body"]["shot"]["made"] != b["value"]["made"]:
                raise BundleError(
                    f"{rid} made={b['value']['made']} contradicts EVENT "
                    f"{target['record_id']} made={target['body']['shot']['made']}"
                )


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    status = 0
    for arg in argv:
        try:
            manifest, records = load_bundle(Path(arg))
        except (BundleError, RecordError, ValueError, UnicodeDecodeError) as exc:
            print(f"FAIL {arg}: {exc}")
            status = 1
            continue
        counts = ", ".join(f"{k}={v}" for k, v in manifest["record_counts"].items())
        print(
            f"PASS {arg}: bundle {manifest['bundle_id']} modes={manifest['data_modes']} "
            f"records_sha256={manifest['records_sha256']} [{counts}]"
        )
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
