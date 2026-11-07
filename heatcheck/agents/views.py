"""Development data views the loop may read. Pure; no files, no truth, no labels table.

A ShotView holds only what the registered shot tests need: outcome per field-goal attempt,
ordered within player-game, plus group/stratum labels and attempted shot value. It is built
either from heatcheck-records/1 EVENTs or from a simulator's public arrays. Hidden simulator
truth is never part of a view.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from heatcheck.contracts.research_bridge import latest_revisions


@dataclass(frozen=True)
class ShotView:
    made: np.ndarray  # int8, ordered within group
    group: np.ndarray  # player-game id (contiguous blocks)
    strata: np.ndarray  # player-game-shot_value id
    value: np.ndarray  # attempted value 2 or 3
    data_mode: str
    source: str  # records_sha256 of the bundle, or simulator generator identity (not truth)
    n_games: int

    def identity(self) -> dict:
        import hashlib

        h = hashlib.sha256()
        for a in (self.made, self.group, self.strata, self.value):
            h.update(np.ascontiguousarray(a, dtype=np.int64).tobytes())
        return {"source": self.source, "data_mode": self.data_mode, "n_attempts": int(len(self.made)),
                "n_groups": int(len(np.unique(self.group))), "n_games": self.n_games,
                "arrays_sha256": h.hexdigest()}


def shot_view_from_events(events: list[dict], data_mode: str, source: str) -> ShotView:
    """Field-goal attempts from EVENT records, ordered by provider sequence within game."""
    rows = []
    for e in latest_revisions(events):
        b = e["body"]
        s = b["shot"]
        if b["action"] == "SHOT" and s["kind"] == "FIELD_GOAL" and b["player_id"]:
            rows.append((b["game_id"], b["player_id"], b["sequence"], int(s["made"]),
                         int(s["points_if_made"])))
    rows.sort(key=lambda r: (r[0], r[1], r[2]))
    keys = [f"{g}|{p}" for g, p, *_ in rows]
    _, group = np.unique(np.array(keys), return_inverse=True) if keys else (None, np.array([]))
    made = np.array([r[3] for r in rows], dtype=np.int8)
    value = np.array([r[4] for r in rows], dtype=np.int64)
    strata = group.astype(np.int64) * 2 + (value == 3)
    return ShotView(made, group.astype(np.int64), strata, value, data_mode, source,
                    len({r[0] for r in rows}))


def shot_view_from_league(league, generator_identity: str) -> ShotView:
    """From Research's simulator League arrays. The Truth object is NOT accepted here."""
    if type(league).__name__ != "League" or not all(
        hasattr(league, a) for a in ("made", "group", "strata", "value")
    ):
        raise TypeError("pass only the simulator's League (public arrays), never (League, Truth)")
    return ShotView(np.asarray(league.made, dtype=np.int8), np.asarray(league.group),
                    np.asarray(league.strata), np.asarray(league.value), "SYNTHETIC",
                    generator_identity, 0)
