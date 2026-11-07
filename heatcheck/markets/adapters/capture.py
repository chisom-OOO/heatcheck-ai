"""Record a public, read-only venue capture into a heatcheck-records/1 bundle.

Two steps, so raw bytes are saved before any parsing can fail:

    fetch  GETs the market and book for one Polymarket slug and/or one Kalshi ticker with
           ``live.ReadOnlyClient`` and writes each response body exactly as received to
           ``<bundle>/raw/<sha256>.json``, plus a ``heatcheck-capture/1`` log holding the URL,
           fetch-start and received times, HTTP status and the game/team target.
    build  Re-derives every record from ``raw/`` offline (``replay.derive``) and writes
           ``records.jsonl`` and ``manifest.json``. ``--check`` compares with what is on disk.

Requests are GET only, to the allowlist in ``live.py``. No account, key, order or
authenticated route exists. Run a fetch only where the user has authorised it.

    python -m heatcheck.markets.adapters.capture fetch <bundle> <capture_spec.json>
    python -m heatcheck.markets.adapters.capture build <bundle> [--check]
"""

from __future__ import annotations

import json
import sys
import urllib.parse
from pathlib import Path
from typing import Any

from heatcheck.contracts.bundle import build_manifest, load_bundle, write_bundle
from heatcheck.contracts.records import sha256_hex
from heatcheck.markets.adapters import polymarket
from heatcheck.markets.adapters.common import (
    ADAPTER_VERSION,
    AdapterError,
    envelope,
    load_payload,
)
from heatcheck.markets.adapters.live import ReadOnlyClient
from heatcheck.markets.adapters.replay import (
    CAPTURE_LOG_VERSION,
    derive,
    find_capture_log,
    read_raw,
)

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
KALSHI = "https://api.elections.kalshi.com/trade-api/v2"


def _get(client: ReadOnlyClient, url: str, raw_dir: Path) -> tuple[bytes, dict[str, Any]]:
    status, body, start, received = client.get(url)
    sha = sha256_hex(body)
    (raw_dir / f"{sha}.json").write_bytes(body)  # saved even if the status is not 200
    entry = {"source": f"GET {url}", "http_status": status, "payload_sha256": sha,
             "fetch_start_utc": start, "received_utc": received}
    if status != 200:
        raise AdapterError(f"HTTP {status} from {url}; raw body kept as {sha}.json")
    return body, entry


def fetch(bundle: Path, spec: dict[str, Any], client: ReadOnlyClient | None = None) -> Path:
    """GET each venue's market and book; write raw payloads and the capture log."""
    client = client or ReadOnlyClient()
    raw_dir = bundle / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    game = spec["game"]
    captures: list[dict[str, Any]] = []
    for target in spec["targets"]:
        venue = target["venue"]
        if venue == "POLYMARKET":
            slug = target["slug"]
            m_raw, m_entry = _get(client, f"{GAMMA}/markets/slug/{urllib.parse.quote(slug)}",
                                  raw_dir)
            # Minimal token lookup only; full parsing happens offline in ``build``.
            m = load_payload(m_raw)
            outcomes = polymarket._json_list(m.get("outcomes"), "outcomes")
            ids_field = "positionIds" if m.get("version") == "v2" else "clobTokenIds"
            tokens = polymarket._json_list(m.get(ids_field), ids_field)
            label = target["expected_label"]
            matches = [t for o, t in zip(outcomes, tokens, strict=True) if o == label]
            if len(matches) != 1:
                raise AdapterError(f"outcome label {label!r} found {len(matches)} times")
            contract = matches[0]
            book_url = f"{CLOB}/book?token_id={urllib.parse.quote(contract)}"
        elif venue == "KALSHI":
            ticker = target["ticker"]
            m_raw, m_entry = _get(client, f"{KALSHI}/markets/{ticker}", raw_dir)
            contract = f"{ticker}:yes"
            book_url = f"{KALSHI}/markets/{ticker}/orderbook"
        else:
            raise AdapterError(f"no capture route for venue {venue!r}")
        _, b_entry = _get(client, book_url, raw_dir)
        captures.append({"venue": venue, "kind": "MARKET", **m_entry})
        captures.append({
            "venue": venue, "kind": "BOOK", **b_entry,
            "market_payload_sha256": m_entry["payload_sha256"],
            "target": {"game_id": game["game_id"], "team_id": target["team_id"],
                       "contract_id": contract, "expected_label": target["expected_label"]},
        })
    log = {"capture_log_version": CAPTURE_LOG_VERSION, "data_mode": spec["data_mode"],
           "adapter_version": ADAPTER_VERSION, "game_reference": game,
           "captures": captures, "note": spec.get("note", "")}
    log_bytes = (json.dumps(log, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    (raw_dir / f"{sha256_hex(log_bytes)}.json").write_bytes(log_bytes)
    return bundle


_PROVIDER = {"POLYMARKET": ("polymarket", "polymarket-gamma", "polymarket-clob-book"),
             "KALSHI": ("kalshi", "kalshi-trade-api/v2", "kalshi-trade-api/v2")}


def build(bundle: Path, rights_note: str, notes: str, created_utc: str) -> tuple[dict, bytes, dict]:
    """Pure over ``bundle/raw``: return (manifest, records_bytes, raw_files)."""
    log_sha, log = find_capture_log(bundle)
    mode = log["data_mode"]
    payloads = {c["payload_sha256"]: read_raw(bundle, c["payload_sha256"])
                for c in log["captures"]}
    log_bytes = read_raw(bundle, log_sha)
    records = []
    for c in log["captures"]:
        provider, m_schema, b_schema = _PROVIDER[c["venue"]]
        data = payloads[c["payload_sha256"]]
        records.append(envelope("RAW_SNAPSHOT", c["payload_sha256"], mode, {
            "snapshot_sha256": c["payload_sha256"], "provider": provider, "source": c["source"],
            "redacted_params": {}, "retrieved_utc": c["received_utc"], "byte_count": len(data),
            "media_type": "application/json",
            "schema_version": m_schema if c["kind"] == "MARKET" else b_schema,
            "rights_note": rights_note, "bundle_path": f"raw/{c['payload_sha256']}.json",
        }))
    records.append(envelope("RAW_SNAPSHOT", log_sha, mode, {
        "snapshot_sha256": log_sha, "provider": "heatcheck",
        "source": "heatcheck.markets.adapters.capture fetch (capture log)",
        "redacted_params": {}, "retrieved_utc": max(c["received_utc"] for c in log["captures"]),
        "byte_count": len(log_bytes), "media_type": "application/json",
        "schema_version": CAPTURE_LOG_VERSION,
        "rights_note": "HeatCheck-authored capture metadata; redistributable within this repo.",
        "bundle_path": f"raw/{log_sha}.json",
    }))
    g = log["game_reference"]
    records.append(envelope("GAME", g["game_id"], mode, {
        "game_id": g["game_id"], "season": g["season"], "competition": g["competition"],
        "provider_ids": g["provider_ids"], "home_team_id": g["home_team_id"],
        "away_team_id": g["away_team_id"], "scheduled_tip_utc": g["scheduled_tip_utc"],
        "status": g["status"], "source_snapshot_ids": [log_sha],
    }))
    records.extend(derive(log, payloads))
    manifest, body = build_manifest(
        records, bundle_id=bundle.name, created_by_role="EXPERIENCE", created_utc=created_utc,
        producer={"tool": "heatcheck.markets.adapters.capture", "version": "1",
                  "adapter_version": ADAPTER_VERSION},
        notes=notes,
    )
    raw = {f"raw/{s}.json": b for s, b in {**payloads, log_sha: log_bytes}.items()}
    return manifest, body, raw


def main(argv: list[str]) -> int:
    if len(argv) >= 3 and argv[0] == "fetch":
        spec = load_payload(Path(argv[2]).read_bytes())
        fetch(Path(argv[1]), spec)
        print(f"fetched into {argv[1]}/raw")
        return 0
    if len(argv) >= 2 and argv[0] == "build":
        bundle = Path(argv[1])
        meta = load_payload((bundle.parent / f"{bundle.name}.build.json").read_bytes())
        manifest, body, raw = build(bundle, meta["rights_note"], meta["notes"],
                                    meta["created_utc"])
        if "--check" in argv:
            on_disk, _ = load_bundle(bundle)
            ok = on_disk == manifest and (bundle / "records.jsonl").read_bytes() == body
            print("PASS: reproducible" if ok else "FAIL: bundle differs from build output")
            return 0 if ok else 1
        write_bundle(bundle, manifest, body, raw)
        load_bundle(bundle)
        print(f"built {bundle} records_sha256={manifest['records_sha256']}")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
