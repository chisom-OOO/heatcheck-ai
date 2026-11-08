"""Time Max's run_investigation per game, no LLM, on a throwaway ledger (read-only on repo files)."""
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(ROOT))
from heatcheck.api.dialogue_server import InvestigationConfig, live_forecast_payload, run_investigation, discover_bundles  # noqa: E402
from heatcheck.ledger.evidence import EvidenceLedger  # noqa: E402

LF = ROOT / "data" / "live" / "forecasts.json"
QUOTES = ROOT / "data" / "experience" / "quotes"
VER = ROOT / "data" / "max" / "mapping_verifications"
sys.path.insert(0, str(ROOT / "apps" / "web"))
from server import app as ui  # noqa: E402

tmp = Path(tempfile.mkdtemp())
cfg = InvestigationConfig(market_bundle=QUOTES, ledger=EvidenceLedger(tmp / "inv.jsonl"), mode="LIVE",
                          verifications=VER)
print("bundles under quotes:", len(discover_bundles(QUOTES)))
t = time.perf_counter(); fc = live_forecast_payload(LF); print(f"live-forecast: {fc['status']} {time.perf_counter() - t:.3f}s")
maps = ui.market_mappings_payload() if hasattr(ui, "market_mappings_payload") else None
games = fc["forecast"]["games"]
total = 0.0
for row in games:
    gid = row["game_id"]
    mid = gid.replace("nba:", "") + "-pm-0215"
    t = time.perf_counter()
    code, out = run_investigation({"game_id": gid, "mapping_id": mid, "message": ""}, LF, cfg)
    dt = time.perf_counter() - t
    total += dt
    print(f"{gid} {mid}: HTTP {code} {out.get('verdict') or out.get('error')} {dt:.3f}s")
print(f"total {total:.2f}s for {len(games)} games")
