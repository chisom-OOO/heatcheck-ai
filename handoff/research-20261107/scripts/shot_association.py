"""SHOT_ASSOCIATION lane (DECISIONS D11).

  harness : planted-truth leagues → false-positive rate, power, confounder susceptibility (G06).
            Test procedure sees only (made, group, strata); truth is scored afterwards by the scorer.
  nba     : pre-registered hot-hand permutation check on DEVELOPMENT games only (final shots not opened).

Usage: python -I scripts/shot_association.py {harness|nba} <data_dir> <out_dir>
"""
import json
import math
import sqlite3
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from heatcheck import features as F, kernels as K, simulate as SIM, splits as S, store  # noqa: E402
from heatcheck.util import PROTOCOL, utc_now_iso  # noqa: E402

KST = 3
ALPHA = 0.05


def hot_hand_test(made, group, strata, B, seed):
    """The ONLY procedure under evaluation. Receives no truth."""
    rng = np.random.default_rng(seed)
    t = K.streak_diff(made, group, KST)
    if t is None:
        return {"status": "UNDEFINED", "T": None, "p": None, "null_mean": None}
    null = []
    for _ in range(B):
        v = K.streak_diff(K.permute_within(made, strata, rng), group, KST)
        if v is not None:
            null.append(v)
    null = np.array(null)
    return {"status": "EXECUTED", "T": t, "p": K.mc_pvalue(t, null), "null_mean": float(null.mean()),
            "null_sd": float(null.std(ddof=1)), "B_effective": int(len(null))}


def _run_league(args):
    seed, family, gamma, form_sd = args
    lg, truth = SIM.generate(seed, family, gamma, form_sd=form_sd)
    res = hot_hand_test(lg.made, lg.group, lg.strata, B=99, seed=seed + 1)
    return res, truth.__dict__, int(len(lg.made))


def wilson(k, n, z=1.96):
    if n == 0:
        return (math.nan, math.nan)
    p = k / n; d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d; h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (c - h, c + h)


def harness(_data, out: Path):
    # conditions: (family, gamma_logodds, form_sd, n_leagues). Family B is held out: no parameter of the
    # test (k, B, alpha, strata) was chosen after looking at B results — they were fixed in D11.
    conds = [("A", 0.0, 0.0, 150), ("A", 0.30, 0.0, 150), ("A", 0.12, 0.0, 150),
             ("B", 0.0, 0.0, 150), ("B", 0.30, 0.0, 150),
             ("C", 0.0, 0.15, 150)]
    jobs, meta = [], []
    base_seed = 1_000_000
    for ci, (fam, g, fsd, n) in enumerate(conds):
        for j in range(n):
            jobs.append((base_seed + ci * 10_000 + j * 7, fam, g, fsd)); meta.append(ci)
    with ProcessPoolExecutor(2) as ex:
        results = list(ex.map(_run_league, jobs, chunksize=8))
    # ---- scorer: only now joins truth
    rows = []
    for (res, truth, nshots), ci in zip(results, meta):
        rows.append({"cond": ci, "family": truth["family"], "gamma": truth["gamma_logodds"],
                     "form_sd": truth["form_sd"], "label": truth["label"], "status": res["status"],
                     "p": res["p"], "T": res["T"], "null_mean": res["null_mean"], "n_shots": nshots})
    df = pd.DataFrame(rows)
    df["reject"] = (df.p <= ALPHA) & (df.status == "EXECUTED")
    summary = []
    for ci, (fam, g, fsd, n) in enumerate(conds):
        d = df[df.cond == ci]; k = int(d.reject.sum()); m = int((d.status == "EXECUTED").sum())
        kind = ("false_positive_rate" if g == 0 and fsd == 0 else
                "confounder_rejection_rate" if g == 0 else "power")
        summary.append({"family": fam, "held_out": fam == "B", "gamma_logodds": g, "form_sd": fsd,
                        "leagues": int(len(d)), "executed": m, "undefined": int(len(d) - m),
                        "metric": kind, "rate": k / m if m else None, "wilson95": wilson(k, m),
                        "mean_T": float(d["T"].mean()), "mean_null_T": float(d.null_mean.mean()),
                        "mean_shots_per_league": float(d.n_shots.mean())})
    # derived FDR at stated prevalence (labelled derived, not a replicated-family estimate)
    def fdr(fpr, pw, pi1):
        return (1 - pi1) * fpr / ((1 - pi1) * fpr + pi1 * pw) if pw + fpr > 0 else None
    sA = {(s["family"], s["gamma_logodds"]): s["rate"] for s in summary if s["form_sd"] == 0}
    derived = {f"family_{f}_gamma0.30_prevalence{p}": fdr(sA[(f, 0.0)], sA[(f, 0.30)], p)
               for f in ("A", "B") for p in (0.1, 0.5)}
    report = {"protocol_version": PROTOCOL, "lane": "SHOT_ASSOCIATION", "phase": "HARNESS",
              "data_mode": "SYNTHETIC", "test": {"k": KST, "B": 99, "alpha": ALPHA,
                                                 "null": "within player-game-shotvalue permutation"},
              "summary": summary, "derived_fdr_from_rates": derived,
              "notes": ["Scripted test policy, not autonomous LLM runs.",
                        "Each league tests one claim, so per-league FDP = V_j ∈ {0,1}; pure-null FDR = FPR.",
                        "Derived FDR assumes the stated prevalence and is computed from rates, not from replicated mixed families.",
                        "Family C has no causal streak term; its rejection rate measures susceptibility to within-game form drift, not FDR under the registered null.",
                        "TruthManifest kept in a separate file; separation is logical (same OS user)."],
              "created_utc": utc_now_iso()}
    out.mkdir(parents=True, exist_ok=True)
    (out / "harness_report.json").write_text(json.dumps(report, indent=2, default=str), newline="\n")
    df.to_csv(out / "harness_league_results.csv", index=False, lineterminator="\n")
    print(json.dumps(report, indent=2, default=str))


def nba(data: Path, out: Path):
    games = store.read(data / "public.sqlite", "games"); games["tip_utc"] = pd.to_datetime(games.tip_utc, utc=True)
    sp, man = S.make_splits(games)
    dev_ids = sorted(sp[sp.split != "final"].game_id)
    con = sqlite3.connect(f"file:{data / 'public.sqlite'}?mode=ro", uri=True)
    ev = pd.read_sql(f"SELECT * FROM events WHERE game_id IN ({','.join('?' * len(dev_ids))})", con, params=dev_ids)
    con.close()
    assert not set(ev.game_id) & set(sp[sp.split == "final"].game_id)
    feat = F.preshot_features(ev)
    # outcome of each shot from the events table (development games only)
    out_made = ev[ev.is_field_goal == 1].assign(target_id=lambda d: "SHOT:" + d.game_id + ":" + d.sequence.astype(str))
    feat = feat.merge(out_made[["target_id", "shot_result"]], on="target_id")
    excluded = int(feat.ordering_unresolved.sum())
    f = feat[~feat.ordering_unresolved & feat.person_id.notna()].sort_values(["game_id", "person_id", "sequence"])
    made = (f.shot_result == "Made").to_numpy(np.int8)
    pg = (f.game_id + ":" + f.person_id.astype("int64").astype(str)).to_numpy()
    group = pd.factorize(pg)[0]
    strata = pd.factorize(pg + ":" + f.shot_value.astype(str))[0]
    hm, nm, hx, nx = K.streak_counts(made, group, KST)
    res = hot_hand_test(made, group, strata, B=999, seed=20261107)
    # attack: shot selection after streaks (difficulty confound) — distance & 3pt share after streaks
    a3 = f[f.prev3_all_made == 1]; x3 = f[f.prev3_all_missed == 1]
    attack_difficulty = {"after_3_makes": {"n": int(len(a3)), "mean_distance_ft": float(a3.shot_distance.mean()),
                                           "share_3pt": float((a3.shot_value == 3).mean())},
                         "after_3_misses": {"n": int(len(x3)), "mean_distance_ft": float(x3.shot_distance.mean()),
                                            "share_3pt": float((x3.shot_value == 3).mean())}}
    if res["status"] == "EXECUTED":
        dec = ("SURVIVED_PROTOCOL_DEVELOPMENT_ONLY" if res["p"] <= ALPHA else "NOT_REJECTED")
    else:
        dec = "INSUFFICIENT_EVIDENCE"
    report = {"protocol_version": PROTOCOL, "lane": "SHOT_ASSOCIATION", "phase": "DEVELOPMENT",
              "data_mode": "REAL_NBA_RETROSPECTIVE", "pseudo_out_of_sample": True,
              "games": len(dev_ids), "fga_eligible": int(len(f)), "fga_excluded_ordering_unresolved": excluded,
              "counts": {"hits_after_3_makes": hm, "n_after_3_makes": nm, "hits_after_3_misses": hx, "n_after_3_misses": nx,
                         "p_make_after_3_makes": hm / nm, "p_make_after_3_misses": hx / nx},
              "test": res, "development_outcome": dec, "attack_difficulty_selection": attack_difficulty,
              "interpretation_limits": [
                  "Association under within-player-game-shotvalue exchangeability only; not a causal hot hand.",
                  "Does not adjust for within-value shot difficulty, defence, fatigue, or shot selection after makes.",
                  "Development games only; this is not a confirmatory final result."],
              "created_utc": utc_now_iso()}
    out.mkdir(parents=True, exist_ok=True)
    (out / "hot_hand_dev.json").write_text(json.dumps(report, indent=2, default=str), newline="\n")
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    {"harness": harness, "nba": nba}[sys.argv[1]](Path(sys.argv[2]), Path(sys.argv[3]))
