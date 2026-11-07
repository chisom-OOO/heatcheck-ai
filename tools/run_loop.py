"""Run the deterministic Jone -> Challenger -> Referee loop on one bundle until Jone has no
registered claim left, appending evidence to an append-only ledger.

    uv run --frozen python tools/run_loop.py <bundle_dir> --ledger <ledger.jsonl>
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from heatcheck.agents.loop import run_once  # noqa: E402
from heatcheck.agents.views import shot_view_from_events  # noqa: E402
from heatcheck.contracts.bundle import load_bundle  # noqa: E402
from heatcheck.ledger.evidence import EvidenceLedger  # noqa: E402


def main(argv: list[str]) -> int:
    bundle, ledger_path = Path(argv[0]), Path(argv[argv.index("--ledger") + 1])
    manifest, recs = load_bundle(bundle)
    events = [r for r in recs if r["record_type"] == "EVENT"]
    modes = {r["data_mode"] for r in events}
    if len(modes) != 1:
        print(f"refusing: bundle EVENTs have data modes {sorted(modes)}")
        return 1
    view = shot_view_from_events(events, modes.pop(), manifest["records_sha256"])
    ledger = EvidenceLedger(ledger_path)
    print(f"view {view.identity()}")
    while (entry := run_once(view, ledger)) is not None:
        i = entry["identity"]
        print(f"{entry['evidence_id']} {i['claim']['claim_id']} {i['decision']} | {i['reason']}")
        for r in i["attack_results"]:
            print(f"    {r['test_id_version']:28s} {r['status']:11s} {r['reason']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
