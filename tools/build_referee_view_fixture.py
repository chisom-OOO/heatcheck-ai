"""Write the heatcheck-referee-view/1 projection of one ledger entry as a JSON fixture.

    uv run --frozen python tools/build_referee_view_fixture.py <ledger.jsonl> <evidence_id> <out.json>

The ledger is read (and verified) through EvidenceLedger; nothing in it is modified.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from heatcheck.ledger.evidence import EvidenceLedger  # noqa: E402
from heatcheck.ledger.referee_view import referee_view  # noqa: E402


def main(argv: list[str]) -> int:
    ledger, eid, out = Path(argv[0]), argv[1], Path(argv[2])
    view = referee_view(EvidenceLedger(ledger).get(eid))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(view, indent=1, ensure_ascii=False, allow_nan=False) + "\n",
                   encoding="utf-8", newline="\n")
    print(f"wrote {out} ({view['verdict']['decision']}, {len(view['attacks_run'])} attacks)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
