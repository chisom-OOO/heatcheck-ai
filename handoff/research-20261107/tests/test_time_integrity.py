"""G02 time integrity on REAL 2023-24 data (first ~6 weeks of games for speed).

Perturb the target outcome and later data; earlier feature vectors must be byte-identical.
A deliberately leaky feature must FAIL the same check (proves the test has teeth)."""
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from heatcheck import features as F
from heatcheck import store

DATA = Path(os.environ.get("HC_DATA", Path(__file__).resolve().parents[1] / "data/run1"))
pytestmark = pytest.mark.skipif(not (DATA / "public.sqlite").exists(), reason="dataset not built")


@pytest.fixture(scope="module")
def real():
    games = store.read(DATA / "public.sqlite", "games")
    games["tip_utc"] = pd.to_datetime(games.tip_utc, utc=True)
    labels = store.read(DATA / "restricted_labels.sqlite", "game_labels")
    g22 = store.read(DATA / "public.sqlite", "games_2022")
    l22 = store.read(DATA / "restricted_labels.sqlite", "game_labels_2022")
    seed = F.seed_elo(g22, l22)
    early = games[games.game_date_et <= "2023-12-05"].copy()
    return early, labels[labels.game_id.isin(early.game_id)].copy(), seed


def _target(games):
    dates = sorted(games.game_date_et.unique())
    d = dates[len(dates) // 2]
    return d, games[games.game_date_et == d].game_id.iloc[0]


def test_pregame_future_perturbation_invariance(real):
    games, labels, seed = real
    d, tgt = _target(games)
    upto = set(games[games.game_date_et <= d].game_id)
    base = F.pregame_features(games, labels, seed, upto)
    lab2 = labels.copy()
    later = lab2.game_id.isin(games[games.game_date_et >= d].game_id)  # target date AND later
    lab2.loc[later, "home_win"] = 1 - lab2.loc[later, "home_win"]
    lab2.loc[later, ["final_home", "final_away"]] = lab2.loc[later, ["final_away", "final_home"]].values
    pert = F.pregame_features(games, lab2, seed, upto)
    assert F.feature_bytes(base) == F.feature_bytes(pert)
    # sanity: perturbation is real — features for games AFTER d do change
    nxt = set(games[games.game_date_et > d].game_id)
    a = F.pregame_features(games, labels, seed, nxt); b = F.pregame_features(games, lab2, seed, nxt)
    assert F.feature_bytes(a) != F.feature_bytes(b)


def test_pregame_raises_if_needed_label_withheld(real):
    games, labels, seed = real
    d, _ = _target(games)
    upto = set(games[games.game_date_et <= d].game_id)
    earlier = games[games.game_date_et < d].game_id.iloc[-1]
    with pytest.raises(F.LabelUnavailable):
        F.pregame_features(games, labels[labels.game_id != earlier], seed, upto)


def _leaky_season_rate(games, labels):
    """DELIBERATELY LEAKY: team season home-win rate over ALL labelled games."""
    m = games.merge(labels[["game_id", "home_win"]], on="game_id")
    rate = m.groupby("home_team_id").home_win.mean()
    return games.assign(leak=games.home_team_id.map(rate))[["game_id", "leak"]]


def test_leakage_fixture_fails_perturbation(real):
    games, labels, _ = real
    d, _ = _target(games)
    early_ids = games[games.game_date_et <= d].game_id
    lab2 = labels.copy()
    later = lab2.game_id.isin(games[games.game_date_et > d].game_id)
    lab2.loc[later, "home_win"] = 1 - lab2.loc[later, "home_win"]
    a = _leaky_season_rate(games, labels); b = _leaky_season_rate(games, lab2)
    a = a[a.game_id.isin(early_ids)]; b = b[b.game_id.isin(early_ids)]
    assert F.feature_bytes(a) != F.feature_bytes(b), "leakage fixture should be detected"


@pytest.fixture(scope="module")
def real_events():
    import sqlite3
    con = sqlite3.connect(f"file:{DATA / 'public.sqlite'}?mode=ro", uri=True)
    gids = [r[0] for r in con.execute("SELECT game_id FROM games ORDER BY tip_utc LIMIT 20")]
    q = f"SELECT * FROM events WHERE game_id IN ({','.join('?' * len(gids))})"
    ev = pd.read_sql(q, con, params=gids); con.close()
    return ev


def test_preshot_future_perturbation_invariance(real_events):
    ev = real_events
    gid = ev.game_id.iloc[0]
    g = ev[ev.game_id == gid].sort_values("sequence")
    shots = g[g.is_field_goal == 1]
    s_seq = int(shots.sequence.iloc[len(shots) // 2])
    base = F.preshot_features(ev)
    base_e = base[(base.game_id != gid) | (base.sequence <= s_seq)]
    ev2 = ev.copy()
    cur_or_later = (ev2.game_id == gid) & (ev2.sequence >= s_seq)
    # flip current shot and every later shot result; corrupt later scores and add a later event
    fg = cur_or_later & (ev2.is_field_goal == 1)
    ev2.loc[fg, "shot_result"] = ev2.loc[fg, "shot_result"].map({"Made": "Missed", "Missed": "Made"})
    later = (ev2.game_id == gid) & (ev2.sequence > s_seq)
    ev2.loc[later, "score_home_after"] += 50
    cur = (ev2.game_id == gid) & (ev2.sequence == s_seq)
    ev2.loc[cur, ["assist_person_id", "block_person_id", "descriptor"]] = [123, 456, "alley-oop"]
    pert = F.preshot_features(ev2)
    pert_e = pert[(pert.game_id != gid) | (pert.sequence <= s_seq)]
    assert F.feature_bytes(base_e) == F.feature_bytes(pert_e)
    # the next shot by the same shooter MUST change (prior-outcome features are live)
    shooter = int(shots[shots.sequence == s_seq].person_id.iloc[0])
    nxt = base[(base.game_id == gid) & (base.person_id == shooter) & (base.sequence > s_seq)]
    if len(nxt):
        n0 = nxt.iloc[[0]]; n1 = pert[pert.target_id == n0.target_id.iloc[0]]
        assert F.feature_bytes(n0.reset_index(drop=True)) != F.feature_bytes(n1.reset_index(drop=True))


def test_preshot_banned_columns_absent(real_events):
    out = F.preshot_features(real_events)
    assert not set(out.columns) & F.BANNED_SHOT_INPUTS


def test_preshot_margin_is_pre_shot(real_events):
    out = F.preshot_features(real_events)
    ev = real_events.sort_values(["game_id", "sequence"])
    first = out.sort_values(["game_id", "sequence"]).groupby("game_id").head(1)
    assert (first.home_pre == 0).all() and (first.away_pre == 0).all()
