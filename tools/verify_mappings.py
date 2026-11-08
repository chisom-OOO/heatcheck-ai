"""Max verifies Polymarket VENUE_MAPPINGs in quote bundles against their stored rules text (M-002).

    uv run --frozen python tools/verify_mappings.py OUT_DIR BUNDLE_DIR [BUNDLE_DIR ...]

For every POLYMARKET mapping in each bundle: reads the market's raw payload from the bundle
(its sha256 must equal a source snapshot id), runs heatcheck/contracts/mapping_verification.py
and writes OUT_DIR/<bundle_id>.json (heatcheck-mapping-verification/1). VERIFIED only when every
check passes; otherwise the document records LEFT_PROPOSED with the failing checks. Kalshi
mappings are skipped and stay PROPOSED. Experience's bundle bytes are never modified.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from heatcheck.contracts.bundle import load_bundle  # noqa: E402
from heatcheck.contracts.mapping_verification import verification_doc  # noqa: E402


def verify_bundle(bundle: Path, verified_utc: str) -> list[dict]:
    manifest, recs = load_bundle(bundle)
    by_id = {r["record_id"]: r for r in recs}
    docs = []
    for m in (r for r in recs if r["record_type"] == "VENUE_MAPPING"):
        market = by_id.get(m["body"]["venue_market_record_id"])
        if market is None or market["body"]["venue"] != "POLYMARKET":
            continue
        game = by_id[m["body"]["game_id"]]
        snap = by_id[market["body"]["source_snapshot_ids"][0]]
        raw = (bundle / snap["body"]["bundle_path"]).read_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        docs.append(verification_doc(m, market, game, json.loads(raw), sha,
                                     manifest["records_sha256"], verified_utc))
    return docs


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    out = Path(argv[0])
    out.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    status = 0
    for arg in argv[1:]:
        bundle = Path(arg)
        docs = verify_bundle(bundle, now)
        if not docs:
            print(f"SKIP {bundle}: no Polymarket mapping")
            continue
        manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
        target = out / f"{manifest['bundle_id']}.json"
        loc = bundle.resolve()  # stored repo-relative so the record works on any machine (CI is Linux)
        loc = loc.relative_to(ROOT).as_posix() if loc.is_relative_to(ROOT) else bundle.as_posix()
        target.write_text(json.dumps({"bundle_dir": loc, "verifications": docs},
                                     indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        for d in docs:
            failed = [c["check"] for c in d["checks"] if c["status"] != "PASS"]
            print(f"{d['outcome']} {bundle.name} {d['record']['record_id'] if d['record'] else ''} "
                  f"{len(d['checks']) - len(failed)}/{len(d['checks'])} PASS {failed or ''}")
            status |= bool(failed)
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
