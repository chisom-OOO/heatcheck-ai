"""Live end-to-end dialogue test: one turn per verdict type present in the committed ledger,
with real Meta model calls. Costs money: run only with the user's approval.

    uv run --frozen python tools/live_dialogue_e2e.py <out_dir> [--cap-usd 1.00] [--only CASE]

* Works on a COPY of the committed ledger reports/max/logs/2026-11-07-al-fixes/
  evidence_real_game_v2.jsonl; the committed file is never written.
* For each turn, records the response, wall time, per-call latency, tokens and cost from the
  usage log, and whether the Heater or Ref text fell back to a template (and why).
* Checks the turn's verdict against the committed entry for the same claim (the Referee is
  deterministic, so they must agree).
* Stops before a turn if the spend logged in <out_dir>/llm_usage.jsonl has reached the cap.
"""

from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from heatcheck.agents.dialogue import Dialogue  # noqa: E402
from heatcheck.agents.llm import MetaChat, usage_summary  # noqa: E402
from heatcheck.agents.views import shot_view_from_events  # noqa: E402
from heatcheck.contracts.bundle import load_bundle  # noqa: E402
from heatcheck.ledger.evidence import EvidenceLedger  # noqa: E402

BUNDLE = ROOT / "data" / "bundles" / "r001-nba-0022300061"
COMMITTED = ROOT / "reports" / "max" / "logs" / "2026-11-07-al-fixes" / "evidence_real_game_v2.jsonl"

# (label, question, expected claim). Questions are written by Max; the mapping is the model's.
CASES = [
    ("INSUFFICIENT_EVIDENCE", "Is the hot hand real? Do guys hit more after three straight makes "
     "than after three straight misses?", "HH-K3"),
    ("NOT_SUPPORTED", "After a player makes two in a row, is the next shot more likely to go in "
     "than after two misses in a row?", "HH-K2"),
    ("BLOCKED", "Do back-to-backs and rest days change who wins?", "GP-REST"),
    ("NONE (no registered test)", "Who is the best free throw shooter in the league?", "NONE"),
    ("CONFIRMATORY (dry run, no verdict)", "Do home teams really win more than half their games?",
     "CONF-HA"),
]


def build(ledger: Path, usage: Path) -> Dialogue:
    manifest, recs = load_bundle(BUNDLE)
    events = [r for r in recs if r["record_type"] == "EVENT"]
    (mode,) = {r["data_mode"] for r in events}
    view = shot_view_from_events(events, mode, manifest["records_sha256"])
    return Dialogue(view, EvidenceLedger(ledger), MetaChat(usage_log=usage))


def _calls(usage: Path, start: int) -> list[dict]:
    if not usage.exists():
        return []
    return [json.loads(x) for x in usage.read_text(encoding="utf-8").splitlines()[start:] if x.strip()]


def main(argv: list[str]) -> int:
    out = Path(argv[0])
    cap = float(argv[argv.index("--cap-usd") + 1]) if "--cap-usd" in argv else 1.00
    out.mkdir(parents=True, exist_ok=True)
    ledger, usage = out / "evidence_copy.jsonl", out / "llm_usage.jsonl"
    shutil.copyfile(COMMITTED, ledger)
    committed = {e["identity"]["claim"]["claim_id"]: e for e in EvidenceLedger.open_readonly(COMMITTED).all()}
    d = build(ledger, usage)
    only = argv[argv.index("--only") + 1] if "--only" in argv else None
    rows = []
    for label, question, expect in CASES:
        if only and not label.startswith(only):
            continue
        spent = usage_summary(usage)["est_cost_usd"] if usage.exists() else 0.0
        if spent >= cap:
            print(f"STOP: logged spend ${spent:.4f} reached cap ${cap:.2f}")
            break
        n0 = len(_calls(usage, 0))
        t0 = time.perf_counter()
        resp = d.turn(question)
        wall = round((time.perf_counter() - t0) * 1000, 1)
        calls = _calls(usage, n0)
        ref_entry = committed.get(resp["claim_id"])
        row = {
            "case": label, "question": question, "expected_claim": expect,
            "mapped_claim": resp["claim_id"], "mapping_ok": resp["claim_id"] == expect,
            "verdict": resp["verdict"], "lane": resp.get("lane"),
            "committed_verdict": ref_entry["identity"]["decision"] if ref_entry else None,
            "verdict_matches_committed": (resp["verdict"] == ref_entry["identity"]["decision"])
            if ref_entry else None,
            "evidence_record_id": resp["evidence_record_id"],
            "sources": resp["sources"], "heater_text": resp["heater_text"], "ref_text": resp["ref_text"],
            "heater_fell_back": not resp["sources"].get("heater", "").startswith("LLM"),
            "ref_fell_back": not resp["sources"].get("ref", "").startswith("LLM"),
            "guard_fallback": any("guard rejected" in str(v) for v in resp["sources"].values()),
            "wall_ms": wall,
            "calls": [{k: c[k] for k in ("role", "status", "latency_ms", "first_text_ms",
                                         "prompt_tokens", "completion_tokens", "reasoning_tokens",
                                         "est_cost_usd")} for c in calls],
            "turn_cost_usd": round(sum(c["est_cost_usd"] or 0 for c in calls), 6),
        }
        rows.append(row)
        print(json.dumps({k: row[k] for k in ("case", "mapped_claim", "verdict", "wall_ms",
                                              "turn_cost_usd", "guard_fallback")}))
    summary = {"turns": rows, "usage_total": usage_summary(usage) if usage.exists() else None,
               "cap_usd": cap, "committed_ledger": str(COMMITTED.relative_to(ROOT))}
    (out / "e2e_results.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
                                          encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
