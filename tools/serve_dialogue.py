"""Serve POST /api/dialogue on 127.0.0.1 for Experience's UI.

    uv run --frozen python tools/serve_dialogue.py data/bundles/r001-nba-0022300061 \
        --ledger logs/dialogue_evidence.jsonl [--port 8770] [--no-llm]         [--live-forecast data/live/forecasts.json]         [--quote-bundle DIR [--recorded] [--investigation-ledger logs/market_investigations.jsonl]
         [--verifications data/max/mapping_verifications]] [--scenario-ledger logs/scenarios.jsonl]

--live-forecast is served read-only at GET /api/live-forecast, re-validated per request.
--quote-bundle enables POST /api/investigate (read-only MARKET_COMPARISON investigation) on that
heatcheck-records/1 quote bundle, or every bundle under that directory (the bundle holding the
newest quote for the requested mapping is used). Max's verified mappings are applied from
--verifications (default data/max/mapping_verifications). --recorded evaluates each quote as of its capture time and
labels every response "RECORDED game" (the 03:00 fallback); otherwise quotes are compared live.
With --live-forecast, POST /api/route and POST /api/scenario[/estimate] are served too; confirmed
scenarios are recorded in --scenario-ledger (default logs/scenarios.jsonl). Research's scenario
effects are a stub until research/scenario-effects is merged.

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
from heatcheck.agents.recorded import find_recorded  # noqa: E402
from heatcheck.agents.views import shot_view_from_events  # noqa: E402
from heatcheck.api.dialogue_server import InvestigationConfig, ScenarioConfig, serve  # noqa: E402
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
    lf = Path(argv[argv.index("--live-forecast") + 1]) if "--live-forecast" in argv else None
    use_llm = "--no-llm" not in argv
    dialogue = build(bundle, ledger, use_llm)
    inv = None
    if "--quote-bundle" in argv:
        inv_ledger = (Path(argv[argv.index("--investigation-ledger") + 1])
                      if "--investigation-ledger" in argv else ROOT / "logs" / "market_investigations.jsonl")
        heater = None
        if use_llm and dialogue.llm is not None:
            llm = dialogue.llm

            def heater(system: str, user: str) -> str:
                msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
                return llm.complete("heater", msgs, stream=True).text

        inv = InvestigationConfig(
            market_bundle=Path(argv[argv.index("--quote-bundle") + 1]),
            ledger=EvidenceLedger(inv_ledger), mode="RECORDED" if "--recorded" in argv else "LIVE",
            thesis_lookup=lambda: find_recorded(dialogue.ledger, "GP-REST"), heater_llm=heater,
            verifications=(Path(argv[argv.index("--verifications") + 1]) if "--verifications" in argv
                           else ROOT / "data" / "max" / "mapping_verifications"))
    scn = None
    if lf is not None:
        scn = ScenarioConfig(ledger=EvidenceLedger(Path(argv[argv.index("--scenario-ledger") + 1])
                                                   if "--scenario-ledger" in argv
                                                   else ROOT / "logs" / "scenarios.jsonl"))
    srv = serve(dialogue, port, lf, inv, scn)
    print(f"dialogue API on http://127.0.0.1:{srv.server_address[1]}/api/dialogue")
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
