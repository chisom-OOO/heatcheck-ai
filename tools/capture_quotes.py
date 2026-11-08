"""Capture fresh read-only venue quotes for tonight's games, verify the mappings, report. One command.

    capture_quotes.cmd                      (Windows, from the repo root)
    uv run --frozen python tools/capture_quotes.py [--forecast data/live/forecasts.json] [--no-verify]

Steps (stops at the first failure and says which):
  1. python -m heatcheck.markets.live_quotes capture <forecast> data/experience/quotes/<UTC start>/
     Read-only GETs only (Polymarket Gamma + CLOB book, Kalshi event/market/orderbook); no keys, no
     accounts, no orders. Every raw body is kept with its fetch and received times. The page's market
     board reads the newest run directory automatically.
  2. python tools/verify_mappings.py data/max/mapping_verifications <each MATCHED Polymarket bundle>
     (Max's 16-check mapping verification; /api/investigate only uses VERIFIED mappings).
  3. Scans the new files for the balldontlie key (~/balldontlie_key.txt) and META_API_KEY; refuses
     if either appears (the values are never printed).
  4. Prints a summary and writes it to <run dir>/CAPTURE_SUMMARY.json.

Quotes age from the moment they are captured. Use them in the demo with
    demo.cmd --recorded-market
which compares each quote as of its capture time and labels it RECORDED (not live).
Nothing is committed or pushed by this tool.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUOTES = ROOT / "data" / "experience" / "quotes"
VERIFICATIONS = ROOT / "data" / "max" / "mapping_verifications"


def say(msg: str) -> None:
    print(f"[capture] {msg}", flush=True)


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")


def secrets() -> list[bytes]:
    out = []
    key_file = Path.home() / "balldontlie_key.txt"
    if key_file.is_file():
        v = key_file.read_text(encoding="utf-8").strip()
        if v:
            out.append(v.encode())
    if os.environ.get("META_API_KEY"):
        out.append(os.environ["META_API_KEY"].encode())
    return out


def main(argv: list[str]) -> int:
    forecast = ROOT / (argv[argv.index("--forecast") + 1] if "--forecast" in argv else "data/live/forecasts.json")
    started = datetime.now(UTC)
    run_dir = QUOTES / started.strftime("%Y%m%dT%H%M%SZ")
    say(f"forecast {forecast.relative_to(ROOT)}; capture into {run_dir.relative_to(ROOT)}")
    t0 = time.time()
    r = run([sys.executable, "-m", "heatcheck.markets.live_quotes", "capture", str(forecast), str(run_dir)])
    tail = [x for x in r.stdout.strip().splitlines() if x.strip()][-6:]
    for line in tail:
        say(f"  {line}")
    if r.returncode != 0 or not run_dir.is_dir():
        say(f"FAIL capture exited {r.returncode}: {r.stderr.strip()[-600:]}")
        return 1
    say(f"capture done in {time.time() - t0:.1f} s")

    pm = sorted(p for p in run_dir.iterdir() if p.is_dir() and "-pm-" in p.name)
    other = sorted(p.name for p in run_dir.iterdir() if p.is_dir() and "-pm-" not in p.name and p.name != "raw")
    index = run_dir / "board.mappings.json"
    n_index = len(json.loads(index.read_text(encoding="utf-8"))["mappings"]) if index.is_file() else 0
    verified, v_lines = None, []
    if "--no-verify" not in argv and pm:
        rel = [str(p.relative_to(ROOT)).replace(os.sep, "/") for p in pm]  # repo-relative paths in the record
        v = run([sys.executable, "tools/verify_mappings.py", str(VERIFICATIONS.relative_to(ROOT)), *rel])
        v_lines = [x for x in v.stdout.splitlines() if x.strip()]
        verified = sum("16/16 PASS" in x for x in v_lines)
        say(f"mapping verification: {verified}/{len(pm)} Polymarket bundles VERIFIED (exit {v.returncode})")
        if v.returncode != 0:
            for line in v_lines[-8:]:
                say(f"  {line}")

    leaked = []
    keys = secrets()
    for f in run_dir.rglob("*"):
        if f.is_file() and keys:
            data = f.read_bytes()
            if any(k in data for k in keys):
                leaked.append(str(f.relative_to(ROOT)))
    if leaked:
        say(f"REFUSED: a key value appears in {len(leaked)} captured file(s): {leaked[:5]}. Do not commit them.")
        return 3
    say(f"key check: no key value in {sum(1 for f in run_dir.rglob('*') if f.is_file())} captured files")

    summary = {"format": "heatcheck-capture-summary/1", "started_utc": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
               "finished_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
               "forecast": str(forecast.relative_to(ROOT)).replace(os.sep, "/"),
               "run_dir": str(run_dir.relative_to(ROOT)).replace(os.sep, "/"),
               "command": f"{Path(sys.executable).name} -m heatcheck.markets.live_quotes capture",
               "polymarket_bundles": [p.name for p in pm], "other_bundles": other,
               "board_mappings": n_index, "verified_polymarket": verified,
               "capture_stdout_tail": tail, "verify_stdout_tail": v_lines[-20:]}
    (run_dir / "CAPTURE_SUMMARY.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8",
                                                  newline="\n")
    say(f"board mappings: {n_index}; Polymarket bundles: {len(pm)}; other venues: {len(other)}")
    if n_index == 0:
        say("WARNING: no MATCHED contract, so the board will show no market prices from this run")
        return 2
    if verified is not None and verified < len(pm):
        say("WARNING: some mappings did not verify; /api/investigate refuses those games")
    say("next: demo.cmd --recorded-market   (quotes shown as RECORDED with their capture time)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
