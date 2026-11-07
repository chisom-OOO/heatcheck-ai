"""Idea-family proposer against Research's grammar heatcheck-idea-family/1 (research/idea-family@d43b29a7).

Cross-checks use Research's own ideas.py from that commit, extracted from git into a temporary
directory (not merged). Without git or that commit the cross-checks skip and say so.
"""

from __future__ import annotations

import ast
import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from heatcheck.agents import idea_proposer as P

ROOT = Path(__file__).resolve().parents[2]
COMMIT = "d43b29a7"
SRC = "handoff/research-20261107/src/heatcheck"


def _git_show(path: str) -> str | None:
    try:
        r = subprocess.run(["git", "show", f"{COMMIT}:{path}"], cwd=ROOT, capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.decode("utf-8") if r.returncode == 0 else None


@pytest.fixture(scope="module")
def research_ideas(tmp_path_factory):
    files = {f: _git_show(f"{SRC}/{f}") for f in ("__init__.py", "ideas.py", "kernels.py", "util.py")}
    if any(v is None for v in files.values()):
        pytest.skip(f"Research's ideas.py at {COMMIT} is not available from git here")
    pytest.importorskip("numpy")
    pytest.importorskip("pandas")
    d = tmp_path_factory.mktemp("research_src") / "rs_heatcheck"
    d.mkdir()
    for f, text in files.items():
        (d / f).write_text(text, encoding="utf-8")
    sys.path.insert(0, str(d.parent))
    try:
        return importlib.import_module("rs_heatcheck.ideas")
    finally:
        sys.path.remove(str(d.parent))


def _literals(src: str) -> dict:
    out = {}
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                out[node.targets[0].id] = ast.literal_eval(node.value)
            except ValueError:
                pass
    return out


def test_enumerations_equal_research_code():
    src = _git_show(f"{SRC}/ideas.py")
    if src is None:
        pytest.skip(f"Research's ideas.py at {COMMIT} is not available from git here")
    lit = _literals(src)
    assert lit["FORMAT"] == P.FORMAT and lit["MAX_IDEAS"] == P.MAX_IDEAS
    assert lit["ALTERNATIVES"] == P.ALTERNATIVES and lit["MODES"] == P.MODES
    assert lit["GAME_LEVELS"] == P.GAME_LEVELS and lit["SHOT_LEVELS"] == P.SHOT_LEVELS


MESSAGES = [
    "Do tired teams on a back-to-back lose more on the road?",
    "Is the hot hand real? Three in a row and you're on fire",
    "Do shooters go cold after two misses?",
    "Are three-pointers streakier in the fourth quarter?",
    "Do favourites cover at home on Sundays in December?",
    "Does rest matter?",
]


@pytest.mark.parametrize("msg", MESSAGES)
def test_keyword_proposals_validate_in_both_validators(msg, research_ideas):
    out = P.propose_family(msg)
    assert out["request"] is not None and out["source"] == "KEYWORD_STANDIN"
    ours = P.validate_request(out["request"], "development")
    theirs = research_ideas.validate_request(json.dumps(out["request"]), "development")
    assert [P.idea_hash(i) for i in ours] == [t.idea_hash for t in theirs]
    assert [x["idea_hash"] for x in out["ideas"]] == [t.idea_hash for t in theirs]


def test_expected_ideas_for_back_to_back():
    out = P.propose_family("Do tired teams on a back-to-back lose more?")
    got = [i["idea"] for i in out["ideas"]]
    assert {"template": "GAME_HOME_WIN_SPLIT",
            "params": {"feature": "away_back_to_back", "level": "yes", "alternative": "greater"}} in got


def test_streak_level_from_message():
    got = [i["idea"]["params"] for i in P.propose_family("two in a row, hot hand?")["ideas"]]
    assert {"condition": "after_makes", "level": "2", "alternative": "greater"} in got


def test_synthetic_mode_drops_game_ideas_and_ot():
    out = P.propose_family("back-to-back hot hand in overtime", mode="synthetic")
    assert all(i["idea"]["template"] == "SHOT_MAKE_AFTER_CONDITION" for i in out["ideas"])
    assert all(i["idea"]["params"]["level"] != "OT" for i in out["ideas"])


def test_nothing_fits_returns_no_request():
    out = P.propose_family("Who has the best jersey?")
    assert out["request"] is None and "no idea" in out["reason"]


def test_free_throws_never_proposed():
    out = P.propose_family("Do free throws go in more after a make?")
    assert all("free" not in json.dumps(i) for i in out.get("ideas", []))


def test_llm_valid_proposal_used():
    req = {"format": P.FORMAT, "ideas": [{"template": "SHOT_MAKE_AFTER_CONDITION",
                                          "params": {"condition": "period", "level": "4", "alternative": "less"}}]}
    seen = {}

    def llm(messages, fmt):
        seen["fmt"] = fmt
        return json.dumps(req)
    out = P.propose_family("clutch?", llm=llm)
    assert out["source"] == "LLM" and out["request"] == req and out["proposer"]["prompt_sha256"]
    assert seen["fmt"]["json_schema"]["strict"] is True


@pytest.mark.parametrize("bad,why", [
    ('{"format":"heatcheck-idea-family/1","ideas":[{"template":"SHOT_MAKE_AFTER_CONDITION",'
     '"params":{"condition":"after_makes","level":3,"alternative":"greater"}}]}', "level"),
    ('{"format":"heatcheck-idea-family/1","ideas":[{"template":"SHOT_MAKE_AFTER_CONDITION",'
     '"params":{"condition":"after_makes","level":"3","alternative":"greater","seed":"1"}}]}', "keys"),
    ('{"format":"heatcheck-idea-family/1","ideas":[{"template":"GAME_HOME_WIN_SPLIT",'
     '"params":{"feature":"travel_miles","level":"yes","alternative":"greater"}}]}', "feature"),
    ('{"format":"heatcheck-idea-family/1","ideas":[], "rationale":"x"}', "keys"),
    ('{"format":"heatcheck-idea-family/1","ideas":[{"template":"SHOT_MAKE_AFTER_CONDITION",'
     '"params":{"condition":"period","level":"OT","alternative":"less"}},{"template":"SHOT_MAKE_AFTER_CONDITION",'
     '"params":{"alternative":"less","condition":"period","level":"OT"}}]}', "duplicates"),
])
def test_llm_invalid_proposal_refused_not_repaired(bad, why, research_ideas):
    with pytest.raises(P.IdeaRefused):
        P.validate_request(bad, "development")
    with pytest.raises(research_ideas.IdeaRefused):
        research_ideas.validate_request(bad, "development")
    out = P.propose_family("hot hand three in a row", llm=lambda m, f: bad)
    assert out["source"].startswith("KEYWORD_STANDIN (LLM proposal refused")
    assert bad not in json.dumps(out["request"])


def test_llm_failure_falls_back():
    def down(m, f):
        raise TimeoutError
    out = P.propose_family("hot hand?", llm=down)
    assert out["source"] == "KEYWORD_STANDIN (fallback: TimeoutError)"


def test_proposer_never_sees_data():
    seen = []
    P.propose_family("hot hand?", llm=lambda m, f: seen.append(m) or "{}")
    text = json.dumps(seen)
    assert "2024-25" not in text and "truth" not in text and "gamma" not in text.lower()
