"""Start the HeatCheck demo from a clean checkout: dialogue API (Heater + Ref) and Experience's UI.

Windows:   demo.cmd [options]                 (in the repository root)
Any OS:    uv run --frozen --group research python tools/demo.py [options]

Options:
  --no-llm        deterministic stand-ins and templates only (also used when META_API_KEY is unset)
  --no-browser    do not open the browser
  --setup-only    build the data and the demo ledger, then exit
  --fresh-ledger  start the demo ledger again from the committed one
  --recorded-market  market card compares each recorded quote as of its capture time and says
                  "RECORDED game" on screen (the cut-off fallback); default compares live
  --live-forecast PATH  forecast file for the market card instead of data/live/forecasts.json
                  (e.g. a SAMPLE file: every card then says SAMPLE and Can't compare)

First run (a few minutes, about 46 MB downloaded):
  1. Download the three pinned public archives (shufinskiy/nba_data at the commit in Research's
     raw/repo/COMMIT) and verify them against Research's SHA256SUMS. Any mismatch stops.
  2. Build Research's 2023-24 tables with Research's unchanged build_dataset.py.
  3. Bridge game nba:0022300061 into data/bundles/ (tools/bridge_r001_game.py) and check that
     the bundle's records_sha256 equals the data identity in the committed evidence ledger.
All of this goes to git-ignored data/ (raw redistribution rights are unverified).

Then:
  * logs/demo/evidence.jsonl starts as a copy of the committed ledger (the committed file is
    never written). The dialogue API appends to it; the UI shows it read-only.
  * http://127.0.0.1:8770/  dialogue console (ask Heater; Max's API test page)
  * http://127.0.0.1:8765/  Experience's UI (Referee evidence ledger view)
  * Market card: GET /api/live-forecast and POST /api/investigate on the dialogue API, using
    Research's data/live/forecasts.json (if present; otherwise the card says Can't compare),
    Experience's quote bundles under data/experience/quotes and Max's verified mappings in
    data/max/mapping_verifications. Investigations go to logs/demo/market_investigations.jsonl.
Ctrl+C stops both servers.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tarfile
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INCOMING = ROOT / "incoming" / "research-20261107"
RAW = ROOT / "data" / "raw" / "research-20261107"
PROCESSED = ROOT / "data" / "processed" / "research-20261107"
BUNDLE = ROOT / "data" / "bundles" / "r001-nba-0022300061"
COMMITTED_LEDGER = ROOT / "evidence" / "evidence.jsonl"
DEMO_LEDGER = ROOT / "logs" / "demo" / "evidence.jsonl"
LIVE_FORECAST = ROOT / "data" / "live" / "forecasts.json"
QUOTES = ROOT / "data" / "experience" / "quotes"
VERIFICATIONS = ROOT / "data" / "max" / "mapping_verifications"
INVESTIGATIONS = ROOT / "logs" / "demo" / "market_investigations.jsonl"
SCENARIOS = ROOT / "logs" / "demo" / "scenarios.jsonl"
UPSTREAM = "https://raw.githubusercontent.com/shufinskiy/nba_data/{commit}/datasets/{name}"
API_PORT, UI_PORT = 8770, 8765


def say(msg: str) -> None:
    print(f"[demo] {msg}", flush=True)


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while b := f.read(1 << 20):
            h.update(b)
    return h.hexdigest()


def run(argv: list, cwd: Path = ROOT) -> None:
    p = subprocess.run([str(a) for a in argv], cwd=cwd)
    if p.returncode != 0:
        raise SystemExit(f"[demo] step failed (exit {p.returncode}): {' '.join(map(str, argv))}")


def fetch_raw() -> None:
    repo, datasets, extracted = RAW / "repo", RAW / "repo" / "datasets", RAW / "extracted"
    datasets.mkdir(parents=True, exist_ok=True)
    extracted.mkdir(parents=True, exist_ok=True)
    for name in ("COMMIT", "SHA256SUMS"):
        shutil.copyfile(INCOMING / "raw" / "repo" / name, repo / name)
    commit = (repo / "COMMIT").read_text().strip()
    sums = dict(reversed(line.split()) for line in (repo / "SHA256SUMS").read_text().splitlines()
                if line.strip())
    for name, want in sums.items():
        dest = datasets / name
        if not dest.exists() or sha256_file(dest) != want:
            url = UPSTREAM.format(commit=commit, name=name)
            say(f"downloading {name} ({url})")
            tmp = dest.with_suffix(".part")
            with urllib.request.urlopen(url, timeout=120) as r, open(tmp, "wb") as f:
                shutil.copyfileobj(r, f)
            got = sha256_file(tmp)
            if got != want:
                tmp.unlink()
                raise SystemExit(f"[demo] REFUSED: {name} sha256 {got} != pinned {want}")
            tmp.replace(dest)
        say(f"verified {name} sha256 {want[:12]}")
        csv = extracted / name.replace(".tar.xz", ".csv")
        if not csv.exists():
            say(f"extracting {name}")
            with tarfile.open(dest, "r:xz") as t:
                t.extractall(extracted, filter="data")


def ensure_bundle() -> None:
    if not (PROCESSED / "public.sqlite").exists():
        fetch_raw()
        say("building Research's 2023-24 tables (Research's build_dataset.py, unchanged)")
        run([sys.executable, "-I", INCOMING / "scripts" / "build_dataset.py",
             RAW / "repo", PROCESSED, RAW / "extracted"])
    if not (BUNDLE / "manifest.json").exists():
        say("bridging game nba:0022300061 into a heatcheck-records/1 bundle")
        run([sys.executable, ROOT / "tools" / "bridge_r001_game.py", PROCESSED])
    sys.path.insert(0, str(ROOT))
    from heatcheck.ledger.evidence import EvidenceLedger
    want = EvidenceLedger.open_readonly(COMMITTED_LEDGER).all()[0]["identity"]["data"]["source"]
    got = json.loads((BUNDLE / "manifest.json").read_text())["records_sha256"]
    if got != want:
        raise SystemExit(f"[demo] REFUSED: bundle records_sha256 {got} differs from the committed "
                         f"ledger's data identity {want}")
    say(f"bundle records_sha256 {got[:12]} matches the committed evidence ledger")


def ensure_ledger(fresh: bool) -> None:
    DEMO_LEDGER.parent.mkdir(parents=True, exist_ok=True)
    if fresh or not DEMO_LEDGER.exists():
        shutil.copyfile(COMMITTED_LEDGER, DEMO_LEDGER)
        say(f"demo ledger {DEMO_LEDGER.relative_to(ROOT)} copied from the committed ledger")
        return
    from heatcheck.ledger.evidence import EvidenceLedger
    have = {e["evidence_id"] for e in EvidenceLedger.open_readonly(DEMO_LEDGER).all()}
    missing = [e for e in EvidenceLedger.open_readonly(COMMITTED_LEDGER).all()
               if e["evidence_id"] not in have]
    if missing:
        say(f"WARNING: the demo ledger lacks {len(missing)} committed entries (e.g. "
            f"{missing[0]['identity']['claim']['claim_id']}); run once with --fresh-ledger")


def port_free(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def wait_port(port: int, proc: subprocess.Popen, name: str, timeout: float = 60) -> None:
    t0 = time.time()
    while time.time() - t0 < timeout:
        if proc.poll() is not None:
            raise SystemExit(f"[demo] {name} exited with code {proc.returncode}")
        if not port_free(port):
            return
        time.sleep(0.3)
    raise SystemExit(f"[demo] {name} did not open port {port} within {timeout:.0f} s")


def main(argv: list[str]) -> int:
    global LIVE_FORECAST
    if "--live-forecast" in argv:
        LIVE_FORECAST = (ROOT / argv[argv.index("--live-forecast") + 1]).resolve()
    try:
        import numpy  # noqa: F401
    except ImportError:
        raise SystemExit("[demo] numpy missing: run through demo.cmd or "
                         "'uv run --frozen --group research python tools/demo.py'") from None
    ensure_bundle()
    ensure_ledger("--fresh-ledger" in argv)
    if "--setup-only" in argv:
        say("setup done")
        return 0
    for port in (API_PORT, UI_PORT):
        if not port_free(port):
            raise SystemExit(f"[demo] port {port} is already in use; stop the other server first")
    use_llm = "--no-llm" not in argv and bool(os.environ.get("META_API_KEY"))
    say("Heater and Ref: " + ("live Meta model calls (spend is logged to logs/llm_usage.jsonl)"
                              if use_llm else "deterministic templates (no model calls)"))
    api = subprocess.Popen([sys.executable, str(ROOT / "tools" / "serve_dialogue.py"), str(BUNDLE),
                            "--ledger", str(DEMO_LEDGER), "--port", str(API_PORT),
                            "--live-forecast", str(LIVE_FORECAST), "--quote-bundle", str(QUOTES),
                            "--verifications", str(VERIFICATIONS),
                            "--investigation-ledger", str(INVESTIGATIONS),
                            "--scenario-ledger", str(SCENARIOS)]
                           + (["--recorded"] if "--recorded-market" in argv else [])
                           + ([] if use_llm else ["--no-llm"]), cwd=ROOT)
    say("market card: forecast " + (str(LIVE_FORECAST.relative_to(ROOT)) if LIVE_FORECAST.exists()
                                     else "MISSING (Research's data/live/forecasts.json not present)")
        + "; quotes " + ("RECORDED as of capture" if "--recorded-market" in argv else "LIVE (60 s limit)"))
    try:   # the board shows only games still to tip (user, 8 Nov); say how many, from the same rule
        from heatcheck.api.dialogue_server import board_forecast_payload
        bf = board_forecast_payload(LIVE_FORECAST)
        if bf.get("status") == "OK":
            say(f"board: {len(bf['forecast']['games'])} games still to tip; "
                f"{bf['earlier']['count']} earlier (tipped off) hidden as one row")
    except Exception as e:  # the count is a convenience; never stops the demo
        say(f"board: game count unavailable ({type(e).__name__})")
    ui = subprocess.Popen([sys.executable, "-m", "server.app", "--port", str(UI_PORT),
                           "--ledger", str(DEMO_LEDGER)], cwd=ROOT / "apps" / "web")
    try:
        wait_port(API_PORT, api, "dialogue API")
        wait_port(UI_PORT, ui, "UI server")
        say(f"demo page (main)  http://127.0.0.1:{UI_PORT}/demo.html")
        say(f"dialogue console  http://127.0.0.1:{API_PORT}/  (fallback)")
        say(f"evidence ledger   http://127.0.0.1:{UI_PORT}/")
        say("Ctrl+C to stop")
        if "--no-browser" not in argv:
            webbrowser.open(f"http://127.0.0.1:{UI_PORT}/demo.html")
        while api.poll() is None and ui.poll() is None:
            time.sleep(0.5)
        say("a server stopped; shutting down")
    except KeyboardInterrupt:
        say("stopping")
    finally:
        for p in (api, ui):
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    p.kill()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
