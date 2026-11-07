"""Planted-truth league generator for the hot-hand test (Research §06; HC11–HC24).

Shot model: logit p_i = talent[player, value] + gamma_logodds * 1{previous k shots in player-game all made}
            + form[player, game] (family C only).
gamma is in LOG-ODDS. The probability increment it implies depends on the base rate.

Families:
  A  — normal talents around league means (2pt≈0.52, 3pt≈0.36), Poisson shot counts. Used for tuning/dev.
  B  — HELD OUT: heavy-tailed (t3) talents, mixture of high/low-volume shooters, 3pt share varies by player.
  C  — confounded null: NO streak term but slow within-game form (random walk). Truth label for the
       registered estimand "causal streak term" is NULL, yet within-game exchangeability is violated.
The TruthManifest is returned separately and must never be passed to the test procedure.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

K_STREAK = 3


@dataclass
class League:
    made: np.ndarray       # int8, ordered within player-game
    group: np.ndarray      # player-game id
    strata: np.ndarray     # player-game-shotvalue id
    value: np.ndarray      # 2 or 3


@dataclass(frozen=True)
class Truth:
    seed: int
    family: str
    gamma_logodds: float
    form_sd: float
    label: str             # NULL | ALTERNATIVE (w.r.t. causal streak term)


def _logit(p):
    return np.log(p / (1 - p))


def generate(seed: int, family: str, gamma_logodds: float, *, n_players=40, n_games=25, mean_shots=12,
             form_sd: float = 0.0) -> tuple[League, Truth]:
    rng = np.random.default_rng(seed)
    if family in ("A", "C"):
        t2 = _logit(0.52) + rng.normal(0, 0.25, n_players)
        t3 = _logit(0.36) + rng.normal(0, 0.20, n_players)
        share3 = np.full(n_players, 0.4)
        vol = np.full(n_players, float(mean_shots))
    elif family == "B":
        t2 = _logit(0.52) + 0.18 * rng.standard_t(3, n_players)
        t3 = _logit(0.36) + 0.15 * rng.standard_t(3, n_players)
        share3 = rng.beta(2, 3, n_players)
        vol = np.where(rng.random(n_players) < 0.3, mean_shots * 1.8, mean_shots * 0.65)
    else:
        raise ValueError(family)
    made_l, grp_l, str_l, val_l = [], [], [], []
    gid = 0
    for p in range(n_players):
        for _ in range(n_games):
            n = rng.poisson(vol[p])
            if n == 0:
                continue
            val = np.where(rng.random(n) < share3[p], 3, 2)
            base = np.where(val == 3, t3[p], t2[p])
            form = np.cumsum(rng.normal(0, form_sd, n)) if form_sd > 0 else np.zeros(n)
            m = np.zeros(n, dtype=np.int8)
            for i in range(n):
                streak = i >= K_STREAK and m[i - K_STREAK:i].all()
                eta = base[i] + form[i] + (gamma_logodds if streak else 0.0)
                m[i] = rng.random() < 1 / (1 + np.exp(-eta))
            made_l.append(m); grp_l.append(np.full(n, gid)); val_l.append(val)
            str_l.append(gid * 2 + (val == 3)); gid += 1
    lg = League(np.concatenate(made_l), np.concatenate(grp_l), np.concatenate(str_l), np.concatenate(val_l))
    label = "ALTERNATIVE" if gamma_logodds != 0 else "NULL"
    return lg, Truth(seed, family, gamma_logodds, form_sd, label)
