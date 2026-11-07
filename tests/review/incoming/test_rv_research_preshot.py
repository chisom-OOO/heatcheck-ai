"""Reviewer pre-shot invariance harness run on Research's real builder and real 2023-24 games.

Stricter than Research's own test (one shot in one game): here EVERY field goal in each sampled
game is flipped, with score_*_after propagated consistently from that event onward, and every
row at or before the flipped shot (all games) must be byte-identical.

Env: HEATCHECK_REVIEW_RESEARCH_SRC=<handoff>/src, HEATCHECK_REVIEW_RESEARCH_DATA=<data/run1>.
"""

from __future__ import annotations

import importlib
import os
import random
import socket
import sqlite3
import sys
from pathlib import Path

import pytest

SRC = os.environ.get("HEATCHECK_REVIEW_RESEARCH_SRC")
DATA = os.environ.get("HEATCHECK_REVIEW_RESEARCH_DATA")
if not (SRC and DATA and (Path(DATA) / "public.sqlite").exists()):
    pytest.skip("NOT_RUN: set HEATCHECK_REVIEW_RESEARCH_SRC and _DATA (built dataset)",
                allow_module_level=True)
pd = pytest.importorskip("pandas")
sys.path.insert(0, SRC)
for name in [m for m in sys.modules if m == "heatcheck" or m.startswith("heatcheck.")]:
    del sys.modules[name]
F = importlib.import_module("heatcheck.features")

# Regulation game, an overtime game, and a game with a clock-regression step (D3).
GAMES = ["0022300001", "0022300007"]


def _load():
    con = sqlite3.connect(f"file:{Path(DATA) / 'public.sqlite'}?mode=ro", uri=True)
    cr = con.execute("SELECT game_id FROM events GROUP BY game_id HAVING sum(clock_regress)>0 "
                     "ORDER BY game_id LIMIT 1").fetchone()
    gids = GAMES + ([cr[0]] if cr else [])
    q = f"SELECT * FROM events WHERE game_id IN ({','.join('?' * len(gids))})"
    ev = pd.read_sql(q, con, params=gids)
    games = pd.read_sql(f"SELECT * FROM games WHERE game_id IN ({','.join('?' * len(gids))})",
                        con, params=gids)
    con.close()
    return gids, ev, games


GIDS, EVENTS, GAMES_DF = _load()


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    def refuse(*a, **k):
        raise RuntimeError("network disabled by reviewer test")
    monkeypatch.setattr(socket, "socket", refuse)


def build(ev):
    return F.add_shooter_margin(F.preshot_features(ev), GAMES_DF)


def leaky(ev):
    out = build(ev)
    made = ev.set_index(["game_id", "sequence"]).shot_result.eq("Made").astype(int)
    out["prior_makes"] = out.prior_makes + made.reindex(
        list(zip(out.game_id, out.sequence))).to_numpy()
    return out


def flip(ev, gid, seq):
    """Flip one FG and keep the scoreboard consistent from that event onward."""
    e = ev.copy()
    row = e[(e.game_id == gid) & (e.sequence == seq)].iloc[0]
    home = int(GAMES_DF.set_index("game_id").home_team_id[gid])
    pts = 3 if row.action_type == "3pt" else 2
    made_now = row.shot_result == "Made"
    delta = -pts if made_now else pts
    col = "score_home_after" if int(row.team_id) == home else "score_away_after"
    e.loc[(e.game_id == gid) & (e.sequence == seq), "shot_result"] = "Missed" if made_now else "Made"
    e.loc[(e.game_id == gid) & (e.sequence >= seq), col] += delta
    return e


def rows(df):
    return {t: F.feature_bytes(df[df.target_id == t].reset_index(drop=True))
            for t in df.target_id}


def violations(builder, gid, limit=None):
    base = builder(EVENTS)
    b_rows = rows(base)
    seqs = sorted(EVENTS[(EVENTS.game_id == gid) & (EVENTS.is_field_goal == 1)].sequence)
    if limit:
        seqs = seqs[:limit]
    bad, downstream = [], 0
    pos = dict(zip(base.target_id, zip(base.game_id, base.sequence)))
    for s in seqs:
        after = rows(builder(flip(EVENTS, gid, s)))
        for t, b in b_rows.items():
            g, q = pos[t]
            if (g != gid or q <= s) and after.get(t) != b:
                bad.append(f"flip {gid}:{s} changed {t}")
            elif g == gid and q > s and after.get(t) != b:
                downstream += 1
    return bad, downstream, len(seqs)


@pytest.mark.parametrize("gid", GIDS)
def test_rv_p1_every_shot_flip_leaves_earlier_rows_identical(gid):
    bad, downstream, n = violations(build, gid)
    assert n > 0
    assert not bad, f"EXPECTED 0 changed pre-shot rows over {n} flips; ACTUAL {len(bad)}: {bad[:5]}"
    assert downstream > 0, "flip never propagated to a later shot"


def test_rv_p2_negative_control_leaky_builder_caught():
    bad, _, _ = violations(leaky, GIDS[0], limit=15)
    assert bad, "harness failed to detect a builder that reads the current shot's outcome"


def test_rv_p3_input_row_order_does_not_matter():
    shuffled = EVENTS.sample(frac=1, random_state=20261107).reset_index(drop=True)
    assert rows(build(EVENTS)) == rows(build(shuffled))


def test_rv_p4_prior_counts_match_independent_recount():
    out = build(EVENTS).set_index("target_id")
    fg = EVENTS[EVENTS.is_field_goal == 1].sort_values(["game_id", "sequence"])
    seen: dict = {}
    problems = []
    for r in fg.itertuples():
        key = (r.game_id, r.person_id)
        att, mk = seen.get(key, (0, 0))
        tid = f"SHOT:{r.game_id}:{r.sequence}"
        row = out.loc[tid]
        if not row.ordering_unresolved and (row.prior_fga, row.prior_makes) != (att, mk):
            problems.append((tid, row.prior_fga, row.prior_makes, att, mk))
        seen[key] = (att + 1, mk + int(r.shot_result == "Made"))
    assert not problems, problems[:5]


def test_rv_p5_margin_matches_scoreboard_before_shot():
    out = build(EVENTS)
    home = GAMES_DF.set_index("game_id").home_team_id
    ev = EVENTS.sort_values(["game_id", "sequence"])
    problems = []
    for r in out[~out.ordering_unresolved].itertuples():
        prior = ev[(ev.game_id == r.game_id) & (ev.sequence < r.sequence)]
        h = int(prior.score_home_after.max()) if len(prior) else 0
        a = int(prior.score_away_after.max()) if len(prior) else 0
        want = h - a if int(r.team_id) == int(home[r.game_id]) else a - h
        if r.margin_pre != want:
            problems.append((r.target_id, r.margin_pre, want))
    assert not problems, problems[:5]


def test_rv_p6_future_assist_block_descriptor_ignored():
    e = EVENTS.copy()
    fg = e.is_field_goal == 1
    e.loc[fg, ["assist_person_id", "block_person_id", "descriptor"]] = [1, 2, "alley-oop"]
    assert rows(build(EVENTS)) == rows(build(e))


def test_rv_p7_random_sample_of_flips_on_unseen_games():
    """Extra: 3 random further games, 10 random flips each (seeded)."""
    con = sqlite3.connect(f"file:{Path(DATA) / 'public.sqlite'}?mode=ro", uri=True)
    all_ids = [r[0] for r in con.execute("SELECT game_id FROM games ORDER BY game_id")]
    con.close()
    picks = random.Random(7).sample([g for g in all_ids if g not in GIDS], 3)
    global EVENTS, GAMES_DF
    saved = EVENTS, GAMES_DF
    try:
        con = sqlite3.connect(f"file:{Path(DATA) / 'public.sqlite'}?mode=ro", uri=True)
        q = ",".join("?" * 3)
        EVENTS = pd.read_sql(f"SELECT * FROM events WHERE game_id IN ({q})", con, params=picks)
        GAMES_DF = pd.read_sql(f"SELECT * FROM games WHERE game_id IN ({q})", con, params=picks)
        con.close()
        for g in picks:
            bad, _, _ = violations(build, g, limit=10)
            assert not bad, bad[:5]
    finally:
        EVENTS, GAMES_DF = saved
