"""Scenario ESTIMATES (heatcheck.scenario): planted-effect recovery on synthetic games, tenure windows,
game-clustered bootstrap, and the pure scenario combiner's arithmetic and refusals."""
import math

import numpy as np
import pandas as pd
import pytest

from heatcheck import scenario as SC


def _games(n=400, seed=0, absent_every=4, drop=0.25):
    """Team 1 at home every game vs team 2; player 77 (team 1) absent every `absent_every`-th game, and team 1's
    true win probability is `drop` lower then. Elo expectation fixed at 0.6."""
    rng = np.random.default_rng(seed)
    absent = np.arange(n) % absent_every == 0
    p_true = np.where(absent, 0.6 - drop, 0.6)
    g = pd.DataFrame({"game_id": [f"g{i:04d}" for i in range(n)], "season": "2023-24",
                      "game_date_et": pd.date_range("2023-10-24", periods=n, freq="D").strftime("%Y-%m-%d"),
                      "home_team_id": 1, "away_team_id": 2, "p_home": 0.6,
                      "home_win": (rng.random(n) < p_true).astype(int), "home_rest": 1, "away_rest": 1})
    app = pd.DataFrame({"game_id": g.game_id[~absent], "team_id": 1, "player_id": 77})
    app = pd.concat([app, pd.DataFrame({"game_id": g.game_id, "team_id": 1, "player_id": 88})])  # never absent
    return g, app, absent


def test_planted_absence_effect_is_recovered_with_interval():
    g, app, absent = _games()
    rows = SC.team_rows(g)
    eff = {e["player_id"]: e for e in SC.absence_effects(rows, app, {77: "P"}, {1: "AAA"}, B=500)}
    e = eff["nba-player:77"]
    # game 0 precedes the player's first appearance, so the tenure window excludes it: 99, not 100
    assert e["label"] == "ESTIMATE" and e["n_games_missed"] == int(absent.sum()) - 1 == 99
    lo, hi = e["effect_win_prob"]["ci95"]
    assert lo < -0.25 + 0.15 and hi > -0.25 - 0.15 and hi < 0                 # covers truth, excludes 0
    assert e["effect_win_prob"]["ci80"][0] >= lo and e["effect_win_prob"]["ci80"][1] <= hi
    assert e["effect_log_odds"]["estimate"] == pytest.approx(e["effect_win_prob"]["estimate"] / (0.6 * 0.4))
    assert "nba-player:88" not in eff                                          # never absent -> no estimate


def test_tenure_window_and_flags():
    g, app, _ = _games(n=40)
    # player 99 appears only in games 10..19, so only absences inside that window count
    app = pd.concat([app, pd.DataFrame({"game_id": [f"g{i:04d}" for i in (10, 12, 14, 19)], "team_id": 1,
                                        "player_id": 99})])
    e = {x["player_id"]: x for x in SC.absence_effects(SC.team_rows(g), app, {}, {}, B=50)}["nba-player:99"]
    assert e["n_games_missed"] == 6 and e["n_games_played"] == 4
    assert "small_n" not in e["flags"]
    app2 = pd.concat([app, pd.DataFrame({"game_id": ["g0003"], "team_id": 2, "player_id": 99})])  # also played for 2
    e2 = {x["key"]: x for x in SC.absence_effects(SC.team_rows(g), app2, {}, {}, B=50)}
    assert "team_change_in_window" in e2["nba-player:99|nba-team:1"]["flags"]


def test_schedule_effects_structure_and_registered_verdict():
    g, _, _ = _games(n=300)
    g["home_rest"] = np.where(np.arange(300) % 5 == 0, 0, 2)
    rows = SC.team_rows(g); rows["three_in_four"] = SC.three_in_four(rows)
    s = SC.schedule_effects(rows, B=200)
    assert s["back_to_back"]["registered_verdict"]["verdict"] == "INSUFFICIENT_EVIDENCE"
    assert s["three_in_four"]["registered_verdict"] is None
    assert s["back_to_back"]["n_condition"] == 60
    assert set(s["rest_diff"]["by_value"]) == {"-3", "-2", "-1", "1", "2", "3"}
    empty = s["rest_diff"]["by_value"]["3"]                      # no game with rest_diff +3 here
    assert empty["n_condition"] == 0 and empty["effect_win_prob"]["estimate"] is None
    with pytest.raises(SC.ScenarioRefused, match="no estimate"):
        SC.scenario_probability(0.6, "a", "b", [{"type": "schedule", "effect": "rest_diff", "value": 3}], {}, s)


def test_three_in_four():
    rows = pd.DataFrame({"team_id": 1, "season": "s", "date": ["2024-01-01", "2024-01-02", "2024-01-04", "2024-01-08"]})
    assert SC.three_in_four(rows).tolist() == [False, False, True, False]


# --------------------------------------------------------------------------- combiner
ABS = {"nba-player:1|nba-team:10": {"player_id": "nba-player:1", "team_id": "nba-team:10", "n_games_missed": 12,
                                    "effect_log_odds": {"estimate": -0.4, "ci95": [-0.8, 0.0]}},
       "nba-player:2|nba-team:20": {"player_id": "nba-player:2", "team_id": "nba-team:20", "n_games_missed": 3,
                                    "effect_log_odds": {"estimate": -0.3, "ci95": [-1.0, 0.4]}},
       "nba-player:1|nba-team:20": {"player_id": "nba-player:1", "team_id": "nba-team:20", "n_games_missed": 9,
                                    "effect_log_odds": {"estimate": -0.1, "ci95": [-0.5, 0.3]}}}
SCH = {"back_to_back": {"effect_log_odds": {"estimate": -0.2, "ci95": [-0.3, -0.1]}},
       "three_in_four": {"effect_log_odds": {"estimate": -0.1, "ci95": [-0.3, 0.1]}},
       "rest_diff": {"by_value": {str(k): {"effect_log_odds": {"estimate": 0.05 * k, "ci95": [0.05 * k - 0.1, 0.05 * k + 0.1]}}
                                  for k in (-3, -2, -1, 1, 2, 3)}}}


def _run(changes, **kw):
    return SC.scenario_probability(0.6, "nba-team:10", "nba-team:20", changes, ABS, SCH, **kw)


def test_combination_on_log_odds_with_quadrature_interval():
    r = _run([{"type": "player_absence", "key": "nba-player:1|nba-team:10", "side": "home"},
              {"type": "schedule", "effect": "back_to_back", "side": "away"}])
    z = math.log(0.6 / 0.4) - 0.4 + 0.2
    assert r["scenario_p_home"] == pytest.approx(1 / (1 + math.exp(-z)))
    se = math.sqrt((0.8 / (2 * SC.Z95)) ** 2 + (0.2 / (2 * SC.Z95)) ** 2)
    assert r["ci95"][0] == pytest.approx(1 / (1 + math.exp(-(z - SC.Z95 * se))))
    assert r["ci80"][0] > r["ci95"][0] and r["ci80"][1] < r["ci95"][1] and r["label"] == "ESTIMATE"
    assert _run([])["scenario_p_home"] == pytest.approx(0.6)


@pytest.mark.parametrize("changes,kw,msg", [
    ([{"type": "player_absence", "key": "nba-player:1|nba-team:10", "side": "home"},
      {"type": "player_absence", "key": "nba-player:1|nba-team:20", "side": "away"}], {}, "twice"),
    ([{"type": "player_absence", "key": "nba-player:1|nba-team:10", "side": "away"}], {}, "not the away team"),
    ([{"type": "player_absence", "key": "nba-player:2|nba-team:20", "side": "away"}], {}, "games missed"),
    ([{"type": "schedule", "effect": "back_to_back", "side": "home"},
      {"type": "schedule", "effect": "three_in_four", "side": "home"}], {}, "double counting"),
    ([{"type": "schedule", "effect": "rest_diff", "value": 2},
      {"type": "schedule", "effect": "back_to_back", "side": "away"}], {}, "double counting"),
    ([{"type": "schedule", "effect": "back_to_back", "side": "home"}], {"baseline_includes": ("rest",)}, "already reflects rest"),
    ([{"type": "schedule", "effect": "rest_diff", "value": 4}], {}, "-3..3"),
    ([{"type": "schedule", "effect": "travel", "side": "home"}], {}, "unknown schedule effect"),
    ([{"type": "player_absence", "key": "nba-player:9|nba-team:10", "side": "home"}], {}, "no estimate"),
    ([{"type": "player_absence", "key": "nba-player:1|nba-team:10", "side": "home", "weight": 2}], {}, "exactly"),
    ([{"type": "injury"}], {}, "type must be"),
])
def test_refusals(changes, kw, msg):
    with pytest.raises(SC.ScenarioRefused, match=msg):
        _run(changes, **kw)


def test_small_n_can_be_allowed_explicitly_and_bad_baseline_refused():
    r = _run([{"type": "player_absence", "key": "nba-player:2|nba-team:20", "side": "away"}], min_n_missed=3)
    assert r["scenario_p_home"] > 0.6
    with pytest.raises(SC.ScenarioRefused, match="baseline"):
        SC.scenario_probability(1.0, "a", "b", [], ABS, SCH)


def test_low_involvement_flag():
    g, app, _ = _games(n=60)
    rows = SC.team_rows(g)
    e = {x["player_id"]: x for x in SC.absence_effects(rows, app, {}, {}, B=20, involvement={(77, 1): 3.0})}
    assert "low_involvement_outcome_dependent_appearance" in e["nba-player:77"]["flags"]
    assert e["nba-player:77"]["median_events_per_game"] == 3.0


# --------------------------------------------------------------------------- heatcheck-scenario/1 answer
import re  # noqa: E402

PROB = re.compile(r"^(0(\.\d+)?|1(\.0+)?)$")
GAME = {"game_id": "nba:0022600191", "home_team_id": "nba-team:10", "away_team_id": "nba-team:20",
        "home_team": "Home Team", "away_team": "Away Team"}
ABS2 = {k: dict(v, player_name=f"P{i}", n_games_played=50 - i, seasons=["2025-26"], flags=[], key=k)
        for i, (k, v) in enumerate(ABS.items()) if k != "nba-player:1|nba-team:20"}
ABS2["nba-player:3|nba-team:20"] = dict(ABS["nba-player:1|nba-team:20"], player_id="nba-player:3", player_name="P3",
                                        n_games_played=40, seasons=["2025-26"], flags=[], key="nba-player:3|nba-team:20")
SCH2 = {"back_to_back": {**SCH["back_to_back"], "n_condition": 1313},
        "three_in_four": {**SCH["three_in_four"], "n_condition": 1934}, "rest_diff": SCH["rest_diff"]}


@pytest.mark.parametrize("team,base", [("nba-team:10", "0.6"), ("nba-team:20", "0.4")])
def test_scenario_answer_meets_experience_rules(team, base):
    a = SC.scenario_api_answer(GAME, team, "Card Team", base, "fc-1", ABS2, SCH2, source="test")
    assert a["format"] == "heatcheck-scenario/1" and a["status"] == "OK" and a["is_sample"] is False
    assert a["baseline"]["p_team_win"] == base and a["team"] == "Card Team" and a["scenarios"]
    for s in a["scenarios"]:
        assert s["label"] == "ESTIMATE" and all(PROB.match(x) for x in (s["p_team_win"], s["range"]["low"], s["range"]["high"]))
        assert float(s["range"]["low"]) <= float(s["p_team_win"]) <= float(s["range"]["high"])
        assert s["range"]["level"] == "0.90" and isinstance(s["n"], int) and s["n"] >= 1 and s["caveats"]
    # an absence of the card team's own player lowers its chance; the away perspective is mirrored
    own = next(s for s in a["scenarios"] if s["scenario_id"].endswith("absent:nba-player:1:nba-team:10"))
    assert (float(own["p_team_win"]) < float(base)) == (team == "nba-team:10")
    small = [s for s in a["scenarios"] if "nba-player:2" in s["scenario_id"]]
    assert not small                                                       # 3 games missed: never offered


def test_scenario_answer_refuses_team_not_in_game():
    with pytest.raises(SC.ScenarioRefused):
        SC.scenario_api_answer(GAME, "nba-team:99", "X", "0.5", "fc", ABS2, SCH2, source="t")


def test_scenario_answer_skips_ambiguous_and_stale_players():
    both = dict(ABS2, **{"nba-player:1|nba-team:20": dict(ABS2["nba-player:1|nba-team:10"], team_id="nba-team:20",
                                                          key="nba-player:1|nba-team:20")})
    old = dict(ABS2, **{"nba-player:3|nba-team:20": dict(ABS2["nba-player:3|nba-team:20"], seasons=["2023-24"])})
    a = SC.scenario_api_answer(GAME, "nba-team:10", "H", "0.6", "fc", both, SCH2, source="t")
    assert not [s for s in a["scenarios"] if "nba-player:1" in s["scenario_id"]]       # on both teams: skipped
    b = SC.scenario_api_answer(GAME, "nba-team:10", "H", "0.6", "fc", old, SCH2, source="t")
    assert not [s for s in b["scenarios"] if "nba-player:3" in s["scenario_id"]]       # not seen in 2025-26
    ids = [s["scenario_id"] for s in a["scenarios"]]
    assert len(ids) == len(set(ids))
