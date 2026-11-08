"""Descriptive calibration check of the live B1 Elo (G07/G09 context): 2025-26 and 2026-27 to date.

Usage: python -I scripts/calibration_check.py <data_2023-24> <data_2024-25> <cdnnba_2025.csv> <balldontlie_raw_dir> <out.json>

Constants are frozen (features.py: K 20, home court 100, carry 0.75*r+0.25*1505). Ratings update only from
results on earlier dates, so every probability is pre-game. Neither season was used to set any constant.
Base-rate forecast B0 = 0.582, the registered 2023-24 fit-split home-win rate (frozen). No model change.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from heatcheck import canonical, store  # noqa: E402
from heatcheck import features as F  # noqa: E402
from heatcheck import kernels as K  # noqa: E402
from heatcheck.util import sha256_file, utc_now_iso  # noqa: E402

EPS = 1e-6
B0 = 0.582            # registered B0 (2023-24 fit split), frozen
B_BOOT, SEED = 4000, 20261108


def carry(r):
    return {t: F.ELO_CARRY * v + (1 - F.ELO_CARRY) * F.ELO_MEAN for t, v in r.items()}


def _season(data, gt="games", lt="game_labels"):
    g = store.read(data / "public.sqlite", gt); g["neutral_site"] = g.neutral_site.astype(bool)
    return g, store.read(data / "restricted_labels.sqlite", lt)


def _p_from_diff(d):
    return 1.0 / (1.0 + 10 ** (-np.asarray(d, float) / 400.0))


def metrics(y, p):
    y, p = np.asarray(y, float), np.asarray(p, float)
    return {"n": int(len(y)), "brier": float(K.brier_per(y, p).mean()), "log_loss": float(K.log_loss_per(y, p, EPS).mean())}


def reliability(y, p):
    rows = []
    for lo in np.arange(0.0, 1.0, 0.1):
        hi = lo + 0.1
        m = (p >= lo) & ((p < hi) if hi < 1.0 - 1e-9 else (p <= 1.0))
        n = int(m.sum())
        if n == 0:
            rows.append({"bin": f"{lo:.1f}-{hi:.1f}", "n": 0}); continue
        k = int(y[m].sum()); z = 1.96; ph = k / n; d = 1 + z * z / n
        c = (ph + z * z / (2 * n)) / d; h = z * math.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n)) / d
        rows.append({"bin": f"{lo:.1f}-{hi:.1f}", "n": n, "mean_predicted": float(p[m].mean()),
                     "actual_home_win_rate": ph, "actual_wilson95": [c - h, c + h],
                     "predicted_minus_actual": float(p[m].mean() - ph)})
    return rows


def home_bias(y, p, dates, rng):
    """Mean predicted minus actual home-win rate; 95% interval by resampling whole calendar dates."""
    y, p = np.asarray(y, float), np.asarray(p, float)
    est = float(p.mean() - y.mean())
    di, uniq = pd.factorize(pd.Series(dates))
    w = rng.multinomial(len(uniq), np.full(len(uniq), 1 / len(uniq)), size=B_BOOT)[:, di].astype(float)
    draws = (w * (p - y)).sum(1) / w.sum(1)
    lo, hi = np.percentile(draws, [2.5, 97.5])
    return {"mean_predicted_home_win": float(p.mean()), "actual_home_win_rate": float(y.mean()),
            "predicted_minus_actual": est, "ci95_date_bootstrap": [float(lo), float(hi)], "n_dates": int(len(uniq))}


def implied_home_court(diff_no_hfa, y):
    """Descriptive only: the home-court Elo points that would make the mean predicted rate equal the actual rate."""
    target = float(np.mean(y)); lo, hi = -200.0, 300.0
    for _ in range(80):
        mid = (lo + hi) / 2
        if _p_from_diff(diff_no_hfa + mid).mean() > target:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def bdl_games(raw_dir: Path, tri_to_id: dict) -> pd.DataFrame:
    rows = {}
    for f in sorted(raw_dir.glob("[0-9][0-9]-*.json")):
        for g in json.loads(f.read_bytes())["data"]:
            rows[g["id"]] = g
    out = []
    for g in rows.values():
        if g["season"] != 2026 or g.get("postseason") or g["status"] != "Final":
            continue
        h, a = tri_to_id[g["home_team"]["abbreviation"]], tri_to_id[g["visitor_team"]["abbreviation"]]
        out.append({"game_id": f"bdl:{g['id']}", "game_date_et": str(g["date"])[:10], "home_team_id": h,
                    "away_team_id": a, "neutral_site": False,
                    "home_win": int(g["home_team_score"] > g["visitor_team_score"])})
    return pd.DataFrame(out).sort_values(["game_date_et", "game_id"]).reset_index(drop=True)


def main(d23: Path, d24: Path, csv25: Path, bdl: Path, out: Path):
    rng = np.random.default_rng(SEED)
    g22, l22 = _season(d23, "games_2022", "game_labels_2022")
    g23, l23 = _season(d23); g24, l24 = _season(d24)
    b25 = canonical.build_canonical(csv25, "2025-26", neutral_sites=set())
    g25 = b25.games.copy(); g25["neutral_site"] = g25.neutral_site.astype(bool); l25 = b25.game_labels
    r = F.seed_elo(g22, l22)
    r, _ = F._run_elo(g23, dict(zip(l23.game_id, l23.home_win.astype(int))), r, emit=False)
    r, _ = F._run_elo(g24, dict(zip(l24.game_id, l24.home_win.astype(int))), carry(r), emit=False)
    s25 = carry(r)
    # 2025-26 pre-game probabilities (frozen feature builder)
    f25 = F.pregame_features(g25, l25, dict(s25), set(g25.game_id)).merge(l25[["game_id", "home_win"]], on="game_id")
    seasons = {"2025-26": {"y": f25.home_win.to_numpy(int), "p": f25.p_elo.to_numpy(float),
                           "diff_no_hfa": (f25.home_elo - f25.away_elo).to_numpy(float),
                           "dates": f25.game_date_et.astype(str).to_numpy()}}
    r, _ = F._run_elo(g25, dict(zip(l25.game_id, l25.home_win.astype(int))), dict(s25), emit=False)
    s27 = carry(r)
    tri = {}
    for g in (g25,):
        tri.update(dict(zip(g.home_tricode, g.home_team_id))); tri.update(dict(zip(g.away_tricode, g.away_team_id)))
    g27 = bdl_games(bdl, tri)
    _, pre = F._run_elo(g27, dict(zip(g27.game_id, g27.home_win)), dict(s27), emit=True)
    pre = pd.DataFrame(pre).merge(g27, on="game_id")
    seasons["2026-27 to date"] = {"y": pre.home_win.to_numpy(int), "p": _p_from_diff(pre.elo_diff),
                                  "diff_no_hfa": (pre.home_elo - pre.away_elo).to_numpy(float),
                                  "dates": pre.game_date_et.astype(str).to_numpy()}
    res = {}
    for name, s in list(seasons.items()) + [("combined", {k: np.concatenate([seasons[x][k] for x in seasons])
                                                          for k in ("y", "p", "diff_no_hfa", "dates")})]:
        y, p = s["y"], s["p"]
        res[name] = {"elo": metrics(y, p), "base_rate_B0_0.582": metrics(y, np.full(len(y), B0)),
                     "coin_0.5": metrics(y, np.full(len(y), 0.5)),
                     "home_bias": home_bias(y, p, s["dates"], rng),
                     "implied_home_court_elo_points": implied_home_court(s["diff_no_hfa"], y),
                     "reliability_10pct_bins": reliability(y, p),
                     "date_range": [str(min(s["dates"])), str(max(s["dates"]))]}
    doc = {"format": "heatcheck-calibration-check/1", "label": "DESCRIPTIVE (not a registered test; no model change)",
           "model": "B1 Elo, frozen constants: K 20, home court 100, carry 0.75*r+0.25*1505; pre-game ratings only",
           "base_rate": "B0 = 0.582, the registered 2023-24 fit-split home-win rate (frozen); coin 0.5 for reference",
           "data": {"2025-26": "shufinskiy/nba_data@46488f0f cdnnba_2025 (sha256 " + sha256_file(csv25)[:16] + ")",
                    "2026-27": "Max's raw balldontlie pages, max/nba-schedule@eec051d (completed regular-season games)"},
           "assumptions": ["neutral-site games are not flagged in 2025-26 or 2026-27 (home court applied to all)",
                           "implied_home_court_elo_points is descriptive only: the home-court value that would make "
                           "the mean predicted rate match the actual rate; it is not a fitted or adopted change"],
           "results": res, "created_utc": utc_now_iso()}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=1) + "\n", newline="\n")
    for name, v in res.items():
        hb = v["home_bias"]
        print(f"{name}: n={v['elo']['n']} Elo brier {v['elo']['brier']:.4f} ll {v['elo']['log_loss']:.4f} | "
              f"B0 brier {v['base_rate_B0_0.582']['brier']:.4f} ll {v['base_rate_B0_0.582']['log_loss']:.4f} | "
              f"pred {hb['mean_predicted_home_win']:.4f} actual {hb['actual_home_win_rate']:.4f} "
              f"diff {hb['predicted_minus_actual']:+.4f} {[round(x, 4) for x in hb['ci95_date_bootstrap']]} | "
              f"implied HCA {v['implied_home_court_elo_points']:.1f}")


if __name__ == "__main__":
    a = sys.argv
    main(Path(a[1]), Path(a[2]), Path(a[3]), Path(a[4]), Path(a[5]))
