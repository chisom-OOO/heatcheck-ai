"""Capture real responses from Max's dialogue server for the page's mock tests.

    uv run --frozen --all-groups python apps/web/tools/capture_max_api.py

Starts Max's own ``heatcheck.api.dialogue_server.serve`` in this process on a free loopback port
(template mode: no model key, no LLM call), with temporary copies of the committed evidence
ledger and an empty investigation ledger, so no repository file is written except the output.
Sources: the SAMPLE live forecast tests/fixtures/live/forecasts.SAMPLE.json, the read-only quote
capture data/experience/quotes/20261107T222950Z (RECORDED mode: each quote as of its capture
time), and Max's mapping verifications data/max/mapping_verifications.

One extra exchange uses a TEST forecast (tests' own copy of the SAMPLE game list with source text
"TEST FIXTURE", not a forecast) so the "Worth investigating" path of the page has a real server
answer to render. It is marked ``test_forecast: true`` and only the tests read it.

Writes apps/web/tests/fixtures/max_api/captures.json.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from heatcheck.agents.dialogue import Dialogue  # noqa: E402
from heatcheck.agents.recorded import find_recorded  # noqa: E402
from heatcheck.api.dialogue_server import InvestigationConfig, serve  # noqa: E402
from heatcheck.ledger.evidence import EvidenceLedger  # noqa: E402

FORECAST = ROOT / "tests" / "fixtures" / "live" / "forecasts.SAMPLE.json"
RUN = ROOT / "data" / "experience" / "quotes" / "20261107T222950Z"
VERIFICATIONS = ROOT / "data" / "max" / "mapping_verifications"
LEDGER = ROOT / "evidence" / "evidence.jsonl"
OUT = ROOT / "apps" / "web" / "tests" / "fixtures" / "max_api" / "captures.json"


def call(base: str, method: str, path: str, body: object | None = None, raw: bytes | None = None):
    data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"} if data is not None else {})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            status, ctype, out = r.status, r.headers.get("Content-Type"), r.read()
    except urllib.error.HTTPError as e:
        status, ctype, out = e.code, e.headers.get("Content-Type"), e.read()
    return status, ctype, json.loads(out)


def test_forecast(tmp: Path) -> Path:
    doc = json.loads(FORECAST.read_text(encoding="utf-8"))
    doc["model"] = "TEST FIXTURE: no model was run; p_home_win 0.5 and Elo 1500 are placeholders"
    doc["source"] = {"results": "TEST FIXTURE for Experience's page tests, not a forecast: the hand-made "
                                "game list of tests/fixtures/live with test source fields",
                     "fetched_utc": "2026-11-07T22:00:00Z", "sha256": "0" * 64, "cross_check": "NOT_RUN"}
    p = tmp / "forecasts.TEST.json"
    p.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return p


def serve_once(ledger: Path, inv_ledger: Path, forecast: Path):
    dialogue = Dialogue(None, EvidenceLedger(ledger), None)
    inv = InvestigationConfig(market_bundle=RUN, ledger=EvidenceLedger(inv_ledger), mode="RECORDED",
                              thesis_lookup=lambda: find_recorded(dialogue.ledger, "GP-REST"),
                              heater_llm=None, verifications=VERIFICATIONS)
    srv = serve(dialogue, 0, forecast, inv)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def main() -> int:
    index = json.loads((RUN / "board.mappings.json").read_text(encoding="utf-8"))
    pm = [m for m in index["mappings"] if m["venue"] == "POLYMARKET"]
    kx = [m for m in index["mappings"] if m["venue"] == "KALSHI"]
    ex = []

    def rec(name, base, method, path, body=None, raw=None, **extra):
        status, ctype, out = call(base, method, path, body, raw)
        ex.append({"name": name, "method": method, "path": path, "request": body,
                   "request_raw": raw.decode() if raw is not None else None,
                   "status": status, "content_type": ctype, "body": out, **extra})
        print(f"{status} {method} {path} {name}")

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        shutil.copyfile(LEDGER, tmp / "evidence.jsonl")
        srv, base = serve_once(tmp / "evidence.jsonl", tmp / "inv.jsonl", FORECAST)
        rec("live_forecast_sample", base, "GET", "/api/live-forecast")
        rec("display_titles", base, "GET", "/api/display-titles")
        rec("dialogue_home_advantage", base, "POST", "/api/dialogue", {"question": "Do home teams win more?"})
        rec("dialogue_rest", base, "POST", "/api/dialogue",
            {"question": "Do back-to-backs and rest days change who wins?"})
        rec("dialogue_bad_body", base, "POST", "/api/dialogue", {"question": "x", "extra": 1})
        for m in pm:
            rec(f"investigate_{m['game_id']}_pm", base, "POST", "/api/investigate",
                {"game_id": m["game_id"], "mapping_id": m["mapping_id"], "message": ""})
        rec("investigate_kalshi", base, "POST", "/api/investigate",
            {"game_id": kx[0]["game_id"], "mapping_id": kx[0]["mapping_id"], "message": ""})
        rec("investigate_unknown_game", base, "POST", "/api/investigate",
            {"game_id": "nba:0000000000", "mapping_id": pm[0]["mapping_id"], "message": ""})
        rec("unknown_path", base, "GET", "/api/nope")
        srv.shutdown()
        srv.server_close()

        srv, base = serve_once(tmp / "evidence.jsonl", tmp / "inv2.jsonl", test_forecast(tmp))
        rec("investigate_test_forecast_pm", base, "POST", "/api/investigate",
            {"game_id": pm[0]["game_id"], "mapping_id": pm[0]["mapping_id"], "message": ""},
            test_forecast=True)
        srv.shutdown()
        srv.server_close()

    git = shutil.which("git")
    head = (subprocess.run([git, "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
            if git else "unknown (git not on PATH)")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc = {"format": "experience-max-api-captures/1",
           "captured_with": {"server": "heatcheck.api.dialogue_server.serve (Max), template mode, no LLM",
                             "repo_head": head, "mode": "RECORDED",
                             "forecast": str(FORECAST.relative_to(ROOT)).replace("\\", "/"),
                             "quotes": str(RUN.relative_to(ROOT)).replace("\\", "/"),
                             "verifications": str(VERIFICATIONS.relative_to(ROOT)).replace("\\", "/"),
                             "ledger": "temporary copy of evidence/evidence.jsonl"},
           "note": ("Real responses from Max's server code, captured by apps/web/tools/capture_max_api.py. "
                    "Volatile fields (recorded_at_utc, evidence ids of investigation entries) are as captured."),
           "exchanges": ex}
    OUT.write_bytes((json.dumps(doc, indent=1, ensure_ascii=False) + "\n").encode("utf-8"))
    print(f"wrote {OUT.relative_to(ROOT)} ({len(ex)} exchanges)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
