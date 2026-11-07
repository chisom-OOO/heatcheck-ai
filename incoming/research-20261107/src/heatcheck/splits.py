"""Chronological whole-game splits cut on ET calendar-date boundaries (DECISIONS D4)."""
from __future__ import annotations

import pandas as pd

from .util import canonical_json, sha256_bytes

FRACTIONS = (("fit", 0.50), ("tune", 0.15), ("calibration", 0.10), ("final", 0.25))


def make_splits(games: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    g = games.sort_values(["tip_utc", "game_id"]).reset_index(drop=True)
    per_date = g.groupby("game_date_et").size().sort_index()
    cum = per_date.cumsum() / len(g)
    bounds, acc = [], 0.0
    for name, frac in FRACTIONS[:-1]:
        acc += frac
        bounds.append((name, acc))
    assign = {}
    for d, c in cum.items():
        # a date goes to the first split whose cumulative boundary it does not exceed (date never straddles)
        prev_c = c - per_date[d] / len(g)
        name = "final"
        for n, b in bounds:
            if prev_c < b - 1e-12:
                name = n
                break
        assign[d] = name
    g["split"] = g.game_date_et.map(assign)
    lists = {s: sorted(g.loc[g.split == s, "game_id"]) for s, _ in FRACTIONS}
    manifest = {s: {"n_games": len(ids), "first_date": g.loc[g.split == s, "game_date_et"].min(),
                    "last_date": g.loc[g.split == s, "game_date_et"].max(),
                    "game_ids_sha256": sha256_bytes(canonical_json(ids))} for s, ids in lists.items()}
    manifest["split_manifest_hash"] = sha256_bytes(canonical_json({s: lists[s] for s in lists}))
    # disjointness
    allids = [i for ids in lists.values() for i in ids]
    assert len(allids) == len(set(allids)) == len(g)
    return g[["game_id", "game_date_et", "split"]], manifest
