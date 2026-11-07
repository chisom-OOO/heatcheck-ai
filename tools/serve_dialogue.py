"""Serve POST /api/dialogue on 127.0.0.1 for Experience's UI.

    uv run --frozen python tools/serve_dialogue.py data/bundles/r001-nba-0022300061 \
        --ledger logs/dialogue_evidence.jsonl [--port 8770] [--no-llm]

The Meta key is read from META_API_KEY in this process's environment. Without it, or with
--no-llm, every turn uses the deterministic stand-ins and templates. Token usage per call is
appended to logs/llm_usage.jsonl.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from heatcheck.agents.dialogue import Dialogue  # noqa: E402
from heatcheck.agents.llm import MetaChat  # noqa: E402
from heatcheck.agents.views import shot_view_from_events  # noqa: E402
from heatcheck.api.dialogue_server import serve  # noqa: E402
from heatcheck.contracts.bundle import load_bundle  # noqa: E402
from heatcheck.ledger.evidence import EvidenceLedger  # noqa: E402


def build(bundle: Path, ledger: Path, use_llm: bool) -> Dialogue:
    manifest, recs = load_bundle(bundle)
    events = [r for r in recs if r["record_type"] == "EVENT"]
    modes = {r["data_mode"] for r in events}
    if len(modes) != 1:
        raise SystemExit(f"refusing: bundle EVENTs have data modes {sorted(modes)}")
    view = shot_view_from_events(events, modes.pop(), manifest["records_sha256"])
    return Dialogue(view, EvidenceLedger(ledger), MetaChat() if use_llm else None)


def main(argv: list[str]) -> int:
    bundle = Path(argv[0])
    ledger = Path(argv[argv.index("--ledger") + 1])
    port = int(argv[argv.index("--port") + 1]) if "--port" in argv else 8770
    srv = serve(build(bundle, ledger, "--no-llm" not in argv), port)
    print(f"dialogue API on http://127.0.0.1:{srv.server_address[1]}/api/dialogue")
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
