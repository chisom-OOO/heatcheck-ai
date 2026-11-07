"""Propose an idea family (heatcheck-idea-family/1) from a fan's message.

    uv run --frozen python tools/propose_ideas.py "Do tired teams lose more?" [--mode development|synthetic]
        [--out request.json] [--llm]

Prints the proposal (source, ideas and their idea_hash). With --out, writes only the request
object, ready for Research's runner:
    python -I scripts/idea_family.py dev <data_2023-24> request.json <out_dir>
--llm uses the Meta model (META_API_KEY in the environment); without it, or on any refusal,
the deterministic proposer is used. This tool never runs the family.
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
    llm = None
    if "--llm" in argv:
        from heatcheck.agents.llm import MetaChat
        chat = MetaChat()

        def llm(messages, fmt):
            return chat.complete("idea_proposer", messages, response_format=fmt).text
    out = propose_family(argv[0], mode, llm)
    print(json.dumps({k: v for k, v in out.items() if k != "request"}, indent=1))
    if "--out" in argv and out["request"] is not None:
        Path(argv[argv.index("--out") + 1]).write_text(json.dumps(out["request"], indent=1) + "\n",
                                                       encoding="utf-8", newline="\n")
    return 0 if out["request"] is not None else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
