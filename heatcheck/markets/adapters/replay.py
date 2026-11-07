"""Offline replay: re-derive market records from a bundle's raw payloads only.

The bundle's ``raw/`` holds each venue payload exactly as received plus one capture log
(``heatcheck-capture/1``) that records, for each payload, its endpoint, fetch-start and
received times, and the game/team/contract it was captured for. Replay reads only those
files, checks every hash, and runs the pure parsers. It never touches the network.

Usage: ``python -m heatcheck.markets.adapters.replay <bundle_dir>`` prints the
re-derived records as canonical JSON lines.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from heatcheck.contracts.records import canonical_bytes, sha256_hex
from heatcheck.markets.adapters import kalshi, polymarket
from heatcheck.markets.adapters.common import AdapterError, Capture, load_payload, propose_mapping

CAPTURE_LOG_VERSION = "heatcheck-capture/1"
PARSERS = {"POLYMARKET": polymarket, "KALSHI": kalshi}


def read_raw(bundle: Path, sha: str) -> bytes:
    path = bundle / "raw" / f"{sha}.json"
    if not path.is_file():
        raise AdapterError(f"raw payload {sha} is missing from the bundle")
    data = path.read_bytes()
    if sha256_hex(data) != sha:
        raise AdapterError(f"raw payload {path.name} does not match its sha256")
    return data


def find_capture_log(bundle: Path) -> tuple[str, dict[str, Any]]:
    found = []
    for path in sorted((bundle / "raw").glob("*.json")):
        obj = load_payload(path.read_bytes())
        if isinstance(obj, dict) and obj.get("capture_log_version") == CAPTURE_LOG_VERSION:
            found.append((path.stem, obj))
    if len(found) != 1:
        raise AdapterError(f"expected exactly one capture log in raw/, found {len(found)}")
    sha, _ = found[0]
    return sha, load_payload(read_raw(bundle, sha))


def derive(
    log: dict[str, Any], payloads: dict[str, bytes]
) -> list[dict[str, Any]]:
    """Pure: capture log + raw payload bytes -> VENUE_MARKET, VENUE_MAPPING, QUOTE records."""
    mode = log.get("data_mode")
    out: list[dict[str, Any]] = []
    markets: dict[str, dict[str, Any]] = {}
    for entry in log.get("captures", []):
        venue = entry.get("venue")
        if venue not in PARSERS:
            raise AdapterError(f"no adapter for venue {venue!r}")
        parser = PARSERS[venue]
        cap = Capture(
            source=entry.get("source"),
            fetch_start_utc=entry.get("fetch_start_utc"),
            received_utc=entry.get("received_utc"),
            data_mode=mode,
        )
        raw = payloads[entry["payload_sha256"]]
        if entry.get("kind") == "MARKET":
            market = parser.parse_market(raw, cap)
            markets[entry["payload_sha256"]] = market
            out.append(market)
        elif entry.get("kind") == "BOOK":
            market_sha = entry["market_payload_sha256"]
            market = markets.get(market_sha)
            if market is None:
                raise AdapterError("a BOOK capture must follow its MARKET capture in the log")
            market_raw = payloads[market_sha]
            target = entry["target"]
            out.append(
                propose_mapping(
                    game_id=target["game_id"],
                    team_id=target["team_id"],
                    market=market,
                    contract_id=target["contract_id"],
                    expected_label=target["expected_label"],
                    rules_text=parser.rules_text(market_raw),
                )
            )
            out.append(
                parser.parse_book(
                    raw,
                    cap,
                    market=market,
                    contract_id=target["contract_id"],
                    game_id=target["game_id"],
                    paused=parser.paused_reason(market_raw),
                )
            )
        else:
            raise AdapterError(f"unknown capture kind {entry.get('kind')!r}")
    return out


def replay_bundle(bundle: Path) -> list[dict[str, Any]]:
    """Re-derive records from ``bundle/raw`` only (hash-checked)."""
    bundle = Path(bundle)
    _, log = find_capture_log(bundle)
    shas = {e["payload_sha256"] for e in log.get("captures", [])}
    payloads = {sha: read_raw(bundle, sha) for sha in shas}
    return derive(log, payloads)


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__)
        return 2
    try:
        records = replay_bundle(Path(argv[0]))
    except (AdapterError, KeyError, OSError) as exc:
        print(f"FAIL {argv[0]}: {exc}")
        return 1
    for r in records:
        sys.stdout.write(canonical_bytes(r).decode("utf-8") + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
