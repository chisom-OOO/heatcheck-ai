"""Idea family (docs/IDEA_GRAMMAR.md): strict grammar, statistics, Holm, freeze-before-compute, synthetic truth
hiding, development-only data scope. Real-data tests are SKIPPED without HC_DATA: report them as NOT_RUN."""
import dataclasses
import importlib.util
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from heatcheck import ideas as I
from heatcheck import simulate as SIM

ROOT = Path(__file__).resolve().parents[1]


def _req(*ideas):
    return {"format": I.FORMAT, "ideas": list(ideas)}


G = {"template": "GAME_HOME_WIN_SPLIT", "params": {"feature": "away_back_to_back", "level": "yes", "alternative": "greater"}}
S1 = {"template": "SHOT_MAKE_AFTER_CONDITION", "params": {"condition": "after_makes", "level": "2", "alternative": "two_sided"}}


# --------------------------------------------------------------------------- grammar
def test_valid_request_and_canonical_hash_is_key_order_independent():
    a = I.validate_request(_req(G, S1), "development")
    b = I.validate_request(json.dumps({"ideas": [{"params": dict(reversed(list(G["params"].items()))),
                                                  "template": G["template"]}, S1], "format": I.FORMAT}), "development")
    assert [x.idea_hash for x in a] == [x.idea_hash for x in b] and len(a) == 2


def _with(idea, **params):
    return {"template": idea["template"], "params": {**idea["params"], **params}}


@pytest.mark.parametrize("bad", [
    {"format": I.FORMAT, "ideas": [G], "extra": 1},                                        # extra top-level key
    {"format": "heatcheck-idea-family/2", "ideas": [G]},                                     # wrong format
    _req(),                                                                                  # no ideas
    _req(*[_with(S1, level=str(k % 4 + 1), condition=c, alternative=a)
           for k, (c, a) in enumerate([(c, a) for c in ("after_makes", "after_misses") for a in I.ALTERNATIVES] * 4)]),
    _req({**G, "rationale": "because"}),                                                     # extra idea key
    _req(_with(G, level=1)),                                                                 # int not string
    _req(_with(G, level=" yes")),                                                            # whitespace
    _req(_with(G, level="Yes")),                                                             # case
    _req(_with(G, feature="home_rest_days", level="5")),                                     # level not enumerated
    _req(_with(G, feature="altitude")),                                                      # unknown feature
    _req(_with(G, alternative="greater_or_equal")),                                          # unknown alternative
    _req({"template": "GAME_HOME_WIN_SPLIT", "params": {**G["params"], "threshold": "0.01"}}),  # extra param
    _req({"template": "SHOT_MAKE_AFTER_CONDITION", "params": G["params"]}),                  # params of other template
    _req(G, dict(G)),                                                                        # duplicate idea
    _req({"template": "free_form", "params": {}}),                                           # unknown template
])
def test_refusals(bad):
    with pytest.raises(I.IdeaRefused):
        I.validate_request(bad, "development")


def test_more_than_twenty_ideas_refused_and_twenty_accepted():
    pool = [{"template": "SHOT_MAKE_AFTER_CONDITION", "params": {"condition": c, "level": lv, "alternative": a}}
            for c, lvls in I.SHOT_LEVELS.items() for lv in lvls for a in I.ALTERNATIVES]
    assert len(I.validate_request(_req(*pool[:20]), "development")) == 20
    with pytest.raises(I.IdeaRefused, match="1 to 20"):
        I.validate_request(_req(*pool[:21]), "development")


@pytest.mark.parametrize("text", [
    '{"format":"heatcheck-idea-family/1","format":"x","ideas":[]}',                          # duplicate key
    '{"format":"heatcheck-idea-family/1","ideas":[{"template":"GAME_HOME_WIN_SPLIT","params":{"feature":"away_back_to_back","level":"yes","alternative":NaN}}]}',
    'not json'])
def test_raw_json_refusals(text):
    with pytest.raises(I.IdeaRefused):
        I.validate_request(text, "development")


def test_synthetic_mode_refuses_game_ideas_and_overtime():
    with pytest.raises(I.IdeaRefused, match="synthetic"):
        I.validate_request(_req(G), "synthetic")
    with pytest.raises(I.IdeaRefused, match="overtime"):
        I.validate_request(_req(_with(S1, condition="period", level="OT")), "synthetic")


# --------------------------------------------------------------------------- statistics
def test_streak_condition_uses_only_strictly_earlier_shots_in_same_group():
    made = np.array([1, 1, 0, 1, 1, 1, 0], dtype=np.int8); group = np.array([0, 0, 0, 0, 1, 1, 1])
    cond, elig = I.streak_condition(made, group, 2, "makes")
    assert elig.tolist() == [False, False, True, True, False, False, True]
    assert cond.tolist() == [False, False, True, False, False, False, True]
    cond2, _ = I.streak_condition(1 - made, group, 2, "misses")      # mirror image
    assert cond2.tolist() == cond.tolist()
    flipped = made.copy(); flipped[2] = 1 - flipped[2]                # a shot's own outcome never changes its condition
    assert I.streak_condition(flipped, group, 2, "makes")[0][2] == cond[2]


def test_p_value_formulas():
    null = np.array([0.0, 0.1, 0.2, 0.3])
    assert I.p_value(0.25, null, "greater") == pytest.approx(2 / 5)
    assert I.p_value(0.05, null, "less") == pytest.approx(2 / 5)
    assert I.p_value(0.45, null, "two_sided") == pytest.approx(1 / 5)   # centred at mean 0.15


def test_holm_counts_insufficient_as_p_one_and_never_survived():
    rows = [{"status": "EXECUTED", "p_raw": 0.01}, {"status": "EXECUTED", "p_raw": 0.04},
            {"status": "INSUFFICIENT", "p_raw": None}]
    v = I.holm_verdicts(rows)
    assert [r["verdict"] for r in v] == ["CANDIDATE", "NOT_A_CANDIDATE", "INSUFFICIENT_EVIDENCE"]
    assert v[0]["p_holm"] == pytest.approx(0.03) and v[1]["p_holm"] == pytest.approx(0.08)


def _game_view(n=200, seed=0, effect=0.0):
    rng = np.random.default_rng(seed)
    b2b = (np.arange(n) % 4 == 0).astype(int)
    p = 0.55 + effect * b2b
    return I.GameView(pd.DataFrame({"game_id": [f"00223{i:05d}" for i in range(n)],
                                    "home_win": (rng.random(n) < p).astype(int), "home_rest": rng.integers(0, 4, n),
                                    "away_rest": rng.integers(0, 4, n), "home_b2b": 0, "away_b2b": b2b,
                                    "elo_diff": rng.normal(0, 120, n), "game_date_et": "2023-11-01"}))


def test_game_idea_detects_strong_effect_and_respects_minimum():
    idea = I.validate_request(_req(G), "development")[0]
    r = I.run_idea(idea, _game_view(effect=0.4), n_perm=199)
    assert r["status"] == "EXECUTED" and r["T"] > 0.25 and r["p_raw"] <= 0.01
    small = I.run_idea(idea, _game_view(n=100), n_perm=19)                         # 25 in the group < 30
    assert small["status"] == "INSUFFICIENT" and small["p_raw"] is None


# --------------------------------------------------------------------------- family: freeze before compute
def _shot_view(seed=1, gamma=0.0):
    lg, _ = SIM.generate(seed, "A", gamma)
    per = np.random.default_rng(seed + 1).integers(1, 5, len(lg.made))
    return I.ShotView(lg.made, lg.group, lg.value, per)


def test_family_registers_before_computing_and_is_write_once(tmp_path, monkeypatch):
    ideas = I.validate_request(_req(S1, _with(S1, condition="period", level="2")), "synthetic")
    seen = {}
    real_run = I.run_idea

    def spy(idea, view, n_perm=I.B):
        seen.setdefault("registered_first", (tmp_path / "registration.json").exists())
        return real_run(idea, view, n_perm)
    monkeypatch.setattr(I, "run_idea", spy)
    res = I.run_family(ideas, {"SHOT_MAKE_AFTER_CONDITION": _shot_view()}, tmp_path, mode="synthetic",
                       data_identity={"x": 1}, code_hash="c", n_perm=29)
    assert seen["registered_first"] is True
    reg = (tmp_path / "registration.json").read_bytes()
    assert res["registration_hash"] == I.sha256_bytes(reg)
    assert [r["idea_hash"] for r in res["results"]] == [i.idea_hash for i in ideas]
    assert all(r["verdict"] in ("CANDIDATE", "NOT_A_CANDIDATE", "INSUFFICIENT_EVIDENCE") for r in res["results"])
    with pytest.raises(FileExistsError):                                            # write-once
        I.run_family(ideas, {"SHOT_MAKE_AFTER_CONDITION": _shot_view()}, tmp_path, mode="synthetic",
                     data_identity={"x": 1}, code_hash="c", n_perm=29)


def test_family_is_deterministic(tmp_path):
    ideas = I.validate_request(_req(S1), "synthetic")
    a = I.run_family(ideas, {"SHOT_MAKE_AFTER_CONDITION": _shot_view()}, tmp_path / "a", mode="synthetic",
                     data_identity={}, code_hash="c", n_perm=49)
    b = I.run_family(ideas, {"SHOT_MAKE_AFTER_CONDITION": _shot_view()}, tmp_path / "b", mode="synthetic",
                     data_identity={}, code_hash="c", n_perm=49)
    strip = lambda r: [{k: v for k, v in x.items()} for x in r["results"]]  # noqa: E731
    assert strip(a) == strip(b)


def test_missing_view_refused_before_registration(tmp_path):
    ideas = I.validate_request(_req(G), "development")
    with pytest.raises(I.IdeaRefused, match="no data view"):
        I.run_family(ideas, {}, tmp_path, mode="development", data_identity={}, code_hash="c")
    assert not (tmp_path / "registration.json").exists()


# --------------------------------------------------------------------------- synthetic: truth hidden, scoreboard
def test_views_carry_no_truth():
    fields = {f.name for f in dataclasses.fields(I.ShotView)}
    assert fields == {"made", "group", "value", "period"}


def test_truth_table_and_scoreboard_tally():
    mk = lambda c, lv, a: I.Idea("SHOT_MAKE_AFTER_CONDITION", tuple(sorted({"condition": c, "level": lv, "alternative": a}.items())))  # noqa: E731
    up, down, per = mk("after_makes", "3", "greater"), mk("after_misses", "1", "less"), mk("period", "2", "two_sided")
    assert I.truth_for(up, 0.3) == ("EFFECT", "greater") and I.truth_for(down, 0.3) == ("EFFECT", "less")
    assert I.truth_for(per, 0.3) == ("NULL", None) and I.truth_for(up, 0.0) == ("NULL", None)
    res = {"results": [
        {"idea_hash": up.idea_hash, "params": up.p, "verdict": "CANDIDATE", "p_holm": 0.01, "T": 0.1, "null_mean": 0.0},
        {"idea_hash": down.idea_hash, "params": down.p, "verdict": "NOT_A_CANDIDATE", "p_holm": 0.3, "T": 0.0, "null_mean": 0.0},
        {"idea_hash": per.idea_hash, "params": per.p, "verdict": "CANDIDATE", "p_holm": 0.02, "T": 0.05, "null_mean": 0.0}]}
    t = I.scoreboard(res, [up, down, per], 0.3)["tally"]
    assert t == {"planted_effects_found": 1, "planted_effects_missed": 1, "nulls_correctly_not_flagged": 0,
                 "false_candidates": 1}


def _script():
    spec = importlib.util.spec_from_file_location("idea_family_cli", ROOT / "scripts/idea_family.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


def test_synthetic_cli_writes_truth_only_after_results(tmp_path):
    cli = _script()
    req = tmp_path / "req.json"; req.write_text(json.dumps(_req(S1, _with(S1, condition="period", level="1"))))
    out = tmp_path / "out"
    cli.synthetic(req, out, "A", 0.3, 11)
    truth = json.loads((out / "truth.json").read_text())
    assert truth["results_sha256"] == I.sha256_bytes((out / "results.json").read_bytes())
    reg = (out / "registration.json").read_text()
    assert "0.3" not in reg and '"A"' not in reg and "gamma" not in reg      # truth absent from registration
    assert set(json.loads((out / "scoreboard.json").read_text())["tally"]) == {
        "planted_effects_found", "planted_effects_missed", "nulls_correctly_not_flagged", "false_candidates"}


# --------------------------------------------------------------------------- real development data
DATA = Path(os.environ.get("HC_DATA", ROOT / "data/run1"))
real = pytest.mark.skipif(not (DATA / "public.sqlite").exists(), reason="NOT_RUN: dataset not built")
DATA_2024 = os.environ.get("HC_DATA_2024")


@real
def test_development_views_contain_only_development_games():
    from heatcheck import splits as S
    from heatcheck import store
    cli = _script()
    gv, sv, ident = cli.load_development(DATA)
    games = store.read(DATA / "public.sqlite", "games"); games["tip_utc"] = pd.to_datetime(games.tip_utc, utc=True)
    sp, _ = S.make_splits(games)
    final = set(sp[sp.split == "final"].game_id)
    assert not set(gv.frame.game_id) & final and len(gv.frame) == 926 and ident["n_fga"] == len(sv.made) > 160000


@pytest.mark.skipif(not DATA_2024, reason="NOT_RUN: set HC_DATA_2024")
def test_development_loader_refuses_the_sealed_2024_25_build():
    with pytest.raises(I.IdeaRefused, match="2023-24"):
        _script().load_development(Path(DATA_2024))
