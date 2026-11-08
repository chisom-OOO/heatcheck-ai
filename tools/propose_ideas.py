"""Propose an idea family (heatcheck-idea-family/1) from a fan's message.

    uv run --frozen python tools/propose_ideas.py "Do tired teams lose more?" [--mode development|synthetic]
        [--out request.json] [--llm] [--min N] [--max N] [--raw-out model_output.json]

Prints the proposal (source, ideas and their idea_hash). With --out, writes only the request
object, ready for Research's runner:
    python -I scripts/idea_family.py dev <data_2023-24> request.json <out_dir>
--llm uses the Meta model (META_API_KEY in the environment); without it, or on any refusal,
the deterministic proposer is used. --raw-out writes the model's exact text plus call metadata
(model, request id, tokens, estimated cost; no prompt secrets, no key). This tool never runs the family.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from heatcheck.agents.idea_proposer import propose_family  # noqa: E402


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    mode = argv[argv.index("--mode") + 1] if "--mode" in argv else "development"
    opt = lambda name, default: int(argv[argv.index(name) + 1]) if name in argv else default  # noqa: E731
    llm, calls = None, []
    if "--llm" in argv:
        import time

        from heatcheck.agents.llm import MetaChat, _cost
        chat = MetaChat()

        def llm(messages, fmt):
            t = time.time()
            try:
                r = chat.complete("idea_proposer", messages, response_format=fmt)
            except Exception as e:
                calls.append({"status": f"ERROR {type(e).__name__}", "latency_s": round(time.time() - t, 2)})
                raise
            calls.append({"status": "OK", "model": r.model, "effort": r.effort, "request_id": r.request_id,
                          "usage": r.usage, "estimated_cost_usd": _cost(r.model, r.usage),
                          "latency_s": round(time.time() - t, 2)})
            return r.text
    out = propose_family(argv[0], mode, llm, min_ideas=opt("--min", 1), max_ideas=opt("--max", 20))
    print(json.dumps({k: v for k, v in out.items() if k != "request"}, indent=1))
    print(json.dumps({"llm_calls": calls}, indent=1))
    if "--raw-out" in argv:
        from datetime import UTC, datetime
        raw = {"format": "heatcheck-idea-proposal-raw/1", "message": argv[0], "mode": mode,
               "created_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
               "source": out["source"], "proposer": out["proposer"], "llm_calls": calls,
               "model_output_text": out.get("llm_raw"),
               "parsed_ideas": out.get("ideas")}
        Path(argv[argv.index("--raw-out") + 1]).write_text(json.dumps(raw, indent=1, ensure_ascii=False) + "\n",
                                                          encoding="utf-8", newline="\n")
    if "--out" in argv and out["request"] is not None:
        Path(argv[argv.index("--out") + 1]).write_text(json.dumps(out["request"], indent=1) + "\n",
                                                       encoding="utf-8", newline="\n")
    return 0 if out["request"] is not None else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
