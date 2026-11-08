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


def test_model_family_bounded_3_to_6_with_keyword_fallback():
    import json as _json

    from heatcheck.agents.idea_proposer import propose_family as _pf
    g = lambda f, lv, a="two_sided": {"template": "GAME_HOME_WIN_SPLIT",  # noqa: E731
                                     "params": {"feature": f, "level": lv, "alternative": a}}
    four = _json.dumps({"format": "heatcheck-idea-family/1", "ideas": [
        g("rest_advantage", "home_more"), g("rest_advantage", "away_more"),
        g("home_back_to_back", "yes", "less"), g("away_back_to_back", "yes", "greater")]})
    seen = {}

    def llm(messages, fmt):
        seen["fmt"] = fmt
        return four
    out = _pf("does rest matter?", "development", llm, min_ideas=3, max_ideas=6)
    assert out["source"] == "LLM" and len(out["ideas"]) == 4 and out["llm_raw"] == four
    arr = seen["fmt"]["json_schema"]["schema"]["properties"]["ideas"]
    assert (arr["minItems"], arr["maxItems"]) == (3, 6)
    two = _json.dumps({"format": "heatcheck-idea-family/1", "ideas": [g("rest_advantage", "home_more")] * 1})
    out = _pf("does rest matter?", "development", lambda m, f: two, min_ideas=3, max_ideas=6)
    assert out["source"].startswith("KEYWORD_STANDIN (LLM proposal refused: 1 ideas, outside 3 to 6")
    assert out["llm_raw"] == two  # the refused model text is kept for the record
    out = _pf("does rest matter?", "development", lambda m, f: "not json", min_ideas=3, max_ideas=6)
    assert out["source"].startswith("KEYWORD_STANDIN (LLM proposal refused: not strict JSON")


def test_idea_board_shows_only_model_proposals_matching_their_request(tmp_path, monkeypatch):
    import json as _json
    import shutil
    import sys as _sys
    from pathlib import Path as _P
    root = _P(__file__).resolve().parents[2]
    _sys.path.insert(0, str(root / "apps" / "web"))
    from server import ideas
    src = root / "data" / "max" / "idea_requests"
    for f in ("does_rest_matter_heater_dev.json", "does_rest_matter_heater_dev.model_output.json"):
        shutil.copy(src / f, tmp_path / f)
    monkeypatch.setenv("HEATCHECK_PROPOSALS", str(tmp_path))
    ok, bad = ideas.read_proposals()
    assert [p["name"] for p in ok] == ["does_rest_matter_heater_dev"] and not bad
    assert ok[0]["status"] == "NOT_RUN" and 3 <= len(ok[0]["ideas"]) <= 6
    req = _json.loads((tmp_path / "does_rest_matter_heater_dev.json").read_text(encoding="utf-8"))
    req["ideas"] = req["ideas"][:-1]
    (tmp_path / "does_rest_matter_heater_dev.json").write_text(_json.dumps(req), encoding="utf-8")
    ok, bad = ideas.read_proposals()
    assert not ok and "does not match" in bad[0]["reason"]
    raw = _json.loads((tmp_path / "does_rest_matter_heater_dev.model_output.json").read_text(encoding="utf-8"))
    raw["source"] = "KEYWORD_STANDIN (fallback: LLMUnavailable)"
    (tmp_path / "does_rest_matter_heater_dev.model_output.json").write_text(_json.dumps(raw), encoding="utf-8")
    ok, bad = ideas.read_proposals()
    assert not ok and "keyword fallback" in bad[0]["reason"]


def test_idea_board_links_research_run_to_the_proposal_only_by_exact_request(tmp_path, monkeypatch):
    import json as _json
    import shutil
    import sys as _sys
    from pathlib import Path as _P
    root = _P(__file__).resolve().parents[2]
    _sys.path.insert(0, str(root / "apps" / "web"))
    from server import ideas
    fam_dir = tmp_path / "idea-family"
    shutil.copytree(root / "handoff" / "research-20261107" / "evidence" / "idea-family", fam_dir)
    monkeypatch.setenv("HEATCHECK_PROPOSALS", str(root / "data" / "max" / "idea_requests"))

    def proposal():
        d = ideas.read_all(str(fam_dir))
        return next(p for p in d["proposals"] if p["name"] == "does_rest_matter_heater_dev")

    p = proposal()  # Research's committed run of c15abf7's request
    assert p["status"] == "RAN" and p["family"] == "does_rest_matter_model"
    assert [r["verdict"] for r in p["results"]] == ["NOT_A_CANDIDATE"] * 5 and p["n_candidates"] == 0
    prov = fam_dir / "PROVENANCE_does_rest_matter_model.json"
    doc = _json.loads(prov.read_text(encoding="utf-8"))
    prov.write_text(_json.dumps({**doc, "request_sha256": "0" * 64}), encoding="utf-8")
    assert proposal()["status"] == "NOT_RUN"  # another request's hash: not linked
    prov.write_text(_json.dumps(doc), encoding="utf-8")
    res = fam_dir / "does_rest_matter_model" / "results.json"
    res.write_text(res.read_text(encoding="utf-8").replace('"label": "EXPLORATORY"', '"label": "CONFIRMED"'),
                   encoding="utf-8")
    assert proposal()["status"] == "NOT_RUN"  # the family fails its own checks: not linked
