"""GAME_PREDICTION lane.

  dev    : fit C1 on fit split, score B0/B1/C1 on tune split. Labels granted only for dates < final start.
  freeze : write the ClaimPlan (hashes of code, data, split, config) — no labels read.
  final  : verifies the plan hash and recomputes every input table hash from the data on disk (refuses on
           any difference, RV-R1); custodian reserves final game IDs, evaluates frozen plan once, marks
           spent, writes result. With changed code it runs only as an AMENDED_REPLAY of the spent receipt.
  amend  : write a CODE_IDENTITY_ONLY amendment (current code hash) for replaying a frozen plan.

Usage: python -I scripts/game_prediction.py {dev|freeze|final} <data_dir> <out_dir>
       python -I scripts/game_prediction.py amend <data_dir> <out_dir> <reason...>
Refusals print "REFUSED: ..." and exit 2.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.linear_model import LogisticRegression  # noqa: E402

from heatcheck import features as F, kernels as K, splits as S, store  # noqa: E402
from heatcheck.custodian import Custodian  # noqa: E402
from heatcheck.util import PROTOCOL, canonical_json, sha256_bytes, sha256_file, utc_now_iso  # noqa: E402

EPS = 1e-6
C1_COLS = ["elo_logit", "rest_diff", "home_b2b", "away_b2b"]
# RV-R4: util.py (canonical_json feeds plan/job hashes), store.py (reads + data hashes), canonical.py and
# build_dataset.py (produce the evaluated tables) added. Plans frozen before this list changed are
# replayed only through a CODE_IDENTITY_ONLY amendment (see amend/final).
CODE_FILES = ["src/heatcheck/features.py", "src/heatcheck/kernels.py", "src/heatcheck/splits.py",
              "src/heatcheck/custodian.py", "src/heatcheck/util.py", "src/heatcheck/store.py",
              "src/heatcheck/canonical.py", "scripts/build_dataset.py", "scripts/game_prediction.py"]
SENSITIVITY_BLOCK_DAYS = (14, 28)   # exploratory, non-decisive (DECISIONS D10)
MIN_BLOCKS = 5                      # pre-registered usable-block rule (DECISIONS D10), unchanged


class FinalRefused(RuntimeError):
    """The final step refuses to evaluate; nothing is reserved, scored or written."""


def load(data: Path):
    games = store.read(data / "public.sqlite", "games")
    games["tip_utc"] = pd.to_datetime(games.tip_utc, utc=True)
    games["neutral_site"] = games.neutral_site.astype(bool)
    g22 = store.read(data / "public.sqlite", "games_2022")
    l22 = store.read(data / "restricted_labels.sqlite", "game_labels_2022")
    sp, man = S.make_splits(games)
    return games, F.seed_elo(g22, l22), sp, man


def fit_c1(feat: pd.DataFrame, y: np.ndarray) -> LogisticRegression:
    m = LogisticRegression(C=1.0, max_iter=1000)
    m.fit(feat[C1_COLS].to_numpy(float), y)
    return m


def predict(feat, model, b0_rate):
    p_b0 = np.full(len(feat), b0_rate)
    p_b1 = feat.p_elo.to_numpy(float)
    X = feat[C1_COLS].to_numpy(float)
    ok = np.isfinite(X).all(1)
    p_c1 = np.where(ok, model.predict_proba(np.nan_to_num(X))[:, 1], p_b0)   # preregistered fallback
    return p_b0, p_b1, p_c1, int((~ok).sum())


def score_table(y, preds: dict):
    return {k: {"log_loss": float(K.log_loss_per(y, p, EPS).mean()), "brier": float(K.brier_per(y, p).mean())}
            for k, p in preds.items()}


def code_hash():
    return sha256_bytes(canonical_json({f: sha256_file(ROOT / f) for f in CODE_FILES}))


def dev(data: Path, out: Path):
    games, seed, sp, man = load(data)
    final_start = man["final"]["first_date"]
    labels_all = store.read(data / "restricted_labels.sqlite", "game_labels")
    allowed = set(games[games.game_date_et < final_start].game_id)
    labels = labels_all[labels_all.game_id.isin(allowed)]   # development grant: no final-period labels
    del labels_all
    ids = {s: set(sp[sp.split == s].game_id) for s in ("fit", "tune", "calibration")}
    feat = F.pregame_features(games, labels, seed, ids["fit"] | ids["tune"] | ids["calibration"])
    feat = feat.merge(labels[["game_id", "home_win"]], on="game_id")
    fit = feat[feat.game_id.isin(ids["fit"])]; tune = feat[feat.game_id.isin(ids["tune"])]
    cal = feat[feat.game_id.isin(ids["calibration"])]
    model = fit_c1(fit, fit.home_win.to_numpy())
    b0 = float(fit.home_win.mean())
    res = {}
    for name, part in (("tune", tune), ("calibration", cal)):
        p0, p1, pc, fb = predict(part, model, b0)
        y = part.home_win.to_numpy()
        d = K.log_loss_per(y, p1, EPS) - K.log_loss_per(y, pc, EPS)
        day = (pd.to_datetime(part.game_date_et) - pd.Timestamp("2023-10-01")).dt.days.to_numpy()
        bb = K.moving_block_bootstrap(d, day, 7, 2000, 7)
        # reliability bins (diagnostic only)
        bins = pd.cut(pc, [0, .2, .4, .5, .6, .8, 1.0], include_lowest=True)
        rel = (pd.DataFrame({"bin": bins, "p": pc, "y": y}).groupby("bin", observed=True)
               .agg(n=("y", "size"), mean_p=("p", "mean"), freq=("y", "mean")).reset_index())
        res[name] = {"n_games": int(len(part)), "c1_fallbacks": fb, "scores": score_table(y, {"B0": p0, "B1": p1, "C1": pc}),
                     "C1_vs_B1_logloss_diff": {"mean": bb.mean, "ci95": bb.ci, "p_one_sided": bb.p_one_sided,
                                               "days": bb.n_days, "nonoverlap_7d_blocks": bb.nonoverlap_blocks,
                                               "status": bb.status},
                     "C1_reliability": rel.astype({"bin": str}).to_dict("records")}
    report = {"protocol_version": PROTOCOL, "lane": "GAME_PREDICTION", "phase": "DEVELOPMENT",
              "data_mode": "REAL_NBA_RETROSPECTIVE", "pseudo_out_of_sample": True,
              "split_manifest": man, "fit": {"n_games": int(len(fit)), "home_win_rate_B0": b0,
                                              "c1_coef": dict(zip(C1_COLS, model.coef_[0].round(6).tolist())),
                                              "c1_intercept": float(model.intercept_[0])},
              "results": res, "labels_granted_through": f"< {final_start}", "created_utc": utc_now_iso()}
    out.mkdir(parents=True, exist_ok=True)
    (out / "game_prediction_dev.json").write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps(report, indent=2, default=str))


def freeze(data: Path, out: Path):
    games, seed, sp, man = load(data)
    mf = json.loads((data / "manifest.json").read_text())
    if store.logical_table_hashes(data) != mf["logical_table_hashes"]:
        raise FinalRefused("stored tables do not match manifest.json logical_table_hashes; refusing to freeze")
    plan = {
        "protocol_version": PROTOCOL, "claim_id": "GP-2023-24-C1-vs-B1", "revision": 1,
        "kind": "GAME_PREDICTION",
        "statement": "Adding prior-rest differential and back-to-back indicators to a frozen Elo baseline "
                     "improves mean log loss on unseen 2023-24 final-split games.",
        "estimand": "mean over final games of logloss(B1) - logloss(C1); H2: logloss(B0) - logloss(B1)",
        "population": "2023-24 NBA regular season games in final split (ET dates "
                      f"{man['final']['first_date']}..{man['final']['last_date']})",
        "target_horizon_cutoff": "00:00 US/Eastern on game date; inputs = outcomes on strictly earlier ET dates",
        "effect_units": "nats per game", "direction": "positive = improvement",
        "feature_catalogue_hash": sha256_bytes(canonical_json({"version": F.FEATURE_VERSION_PREGAME, "c1": C1_COLS,
                                                               "elo": [F.ELO_K, F.ELO_HFA, F.ELO_MEAN, F.ELO_CARRY]})),
        "baseline_hash": sha256_bytes(canonical_json({"B0": "fit-split home-win rate", "B1": "Elo p_elo"})),
        "data_hashes": mf["logical_table_hashes"],
        "split_manifest_hash": man["split_manifest_hash"],
        "primary_metric_test": "paired log-loss diff; moving-block bootstrap 7 calendar days, B=10000, seed 20261107; Holm over {H1,H2} at 0.05",
        "practical_effect_floor": 0.002,
        "mandatory_attacks": ["future_perturbation(G02)", "identical_eligible_games_and_fallback(G09)",
                              "block_count_sufficiency", "multiplicity_holm"],
        "final_family_id": "FAM-GP-2023-24-v1", "final_epoch_id": "EPOCH-GP-2023-24-001",
        "compute_budget": "single CPU run < 5 min",
        "creator_model_prompt": "none: plan authored by HeatCheck-Research coding session per DECISIONS D6/D10",
        "code_hash": code_hash(), "eps": EPS,
    }
    plan["canonical_plan_hash"] = sha256_bytes(canonical_json(plan))
    out.mkdir(parents=True, exist_ok=True)
    (out / "claim_plan_GP.json").write_text(json.dumps(plan, indent=2))
    print(json.dumps(plan, indent=2))


def _verified_plan(out: Path) -> dict:
    plan = json.loads((out / "claim_plan_GP.json").read_text())
    body = {k: v for k, v in plan.items() if k != "canonical_plan_hash"}
    if sha256_bytes(canonical_json(body)) != plan.get("canonical_plan_hash"):
        raise FinalRefused("claim_plan_GP.json does not match its canonical_plan_hash (plan edited after freeze)")
    return plan


def _amendment_path(out: Path, n: int) -> Path:
    return out / f"claim_plan_GP.amendment-{n}.json"


def amend(data: Path, out: Path, reason: str = ""):
    """Write a CODE_IDENTITY_ONLY amendment: records the current code hash for replaying a frozen plan.
    It carries no claim, hypothesis, threshold, floor, split, data hash, family, epoch or seed:
    final() reads all decision content from the original plan only."""
    plan = _verified_plan(out)
    n = 1
    while _amendment_path(out, n).exists():
        n += 1
    am = {"protocol_version": PROTOCOL, "amendment_type": "CODE_IDENTITY_ONLY",
          "amendment_id": f"{plan['claim_id']}-AMEND-{n}", "amends_plan_hash": plan["canonical_plan_hash"],
          "reason": reason or "code changed after freeze; decision content unchanged",
          "code_files": CODE_FILES, "code_hash": code_hash(),
          "decision_content": "unchanged; read from the original plan only", "created_utc": utc_now_iso()}
    am["canonical_amendment_hash"] = sha256_bytes(canonical_json(am))
    _amendment_path(out, n).write_text(json.dumps(am, indent=2) + "\n", newline="\n")
    print(json.dumps(am, indent=2))


def _matching_amendment(out: Path, plan: dict, current_code_hash: str) -> dict | None:
    n = 1
    while _amendment_path(out, n).exists():
        am = json.loads(_amendment_path(out, n).read_text())
        body = {k: v for k, v in am.items() if k != "canonical_amendment_hash"}
        if sha256_bytes(canonical_json(body)) != am.get("canonical_amendment_hash"):
            raise FinalRefused(f"{_amendment_path(out, n).name} does not match its canonical hash")
        if (am.get("amendment_type") == "CODE_IDENTITY_ONLY"
                and am["amends_plan_hash"] == plan["canonical_plan_hash"]
                and am["code_hash"] == current_code_hash and am["code_files"] == CODE_FILES):
            return am
        n += 1
    return None


def final(data: Path, out: Path):
    plan = _verified_plan(out)
    games, seed, sp, man = load(data)
    if man["split_manifest_hash"] != plan["split_manifest_hash"]:
        raise FinalRefused("split changed since freeze")
    # RV-R1: bind the run to the data actually on disk, not to the build manifest or the plan's copy
    actual = store.logical_table_hashes(data)
    frozen = plan["data_hashes"]
    differ = sorted(k for k in set(actual) | set(frozen) if actual.get(k) != frozen.get(k))
    if differ:
        raise FinalRefused(f"input data differ from the frozen plan's data_hashes: {differ}")
    input_hash = sha256_bytes(canonical_json(actual))
    current_code = code_hash()
    final_ids = sorted(sp[sp.split == "final"].game_id)
    cust = Custodian(out / "custodian_ledger.jsonl")
    if current_code == plan["code_hash"]:
        mode, amendment = "ORIGINAL", None
        receipt = cust.reserve(family_id=plan["final_family_id"], epoch_id=plan["final_epoch_id"],
                               plan_hash=plan["canonical_plan_hash"], code_hash=plan["code_hash"],
                               record_ids=final_ids, input_hash=input_hash)
        receipt_id, replay = receipt["receipt_id"], None
    else:
        amendment = _matching_amendment(out, plan, current_code)
        if amendment is None:
            raise FinalRefused("code changed since freeze and no CODE_IDENTITY_ONLY amendment matches the "
                               "current code: this would be a new experiment")
        originals = [e for e in cust.history_by_job(plan["final_family_id"], plan["final_epoch_id"])
                     if e["plan_hash"] == plan["canonical_plan_hash"]]
        if len(originals) != 1:
            raise FinalRefused("amended replay needs exactly one original reservation of this plan")
        mode, receipt_id = "AMENDED_REPLAY", originals[0]["receipt_id"]
        replay = cust.replay(receipt_id=receipt_id, family_id=plan["final_family_id"],
                             epoch_id=plan["final_epoch_id"], record_ids=final_ids,
                             amendment_hash=amendment["canonical_amendment_hash"], code_hash=current_code,
                             input_hash=input_hash)
        receipt = {"receipt_id": receipt_id, "retry": True}
    # ---- inside custodian scope: full labels
    labels = store.read(data / "restricted_labels.sqlite", "game_labels")
    feat = F.pregame_features(games, labels, seed, set(games.game_id)).merge(labels[["game_id", "home_win"]], on="game_id")
    fit = feat[feat.game_id.isin(sp[sp.split == "fit"].game_id)]
    model = fit_c1(fit, fit.home_win.to_numpy()); b0 = float(fit.home_win.mean())
    fin = feat[feat.game_id.isin(final_ids)].sort_values(["game_date_et", "game_id"])
    if len(fin) != len(final_ids):
        raise FinalRefused("final games missing from the feature table")
    p0, p1, pc, fb = predict(fin, model, b0)
    y = fin.home_win.to_numpy()
    day = (pd.to_datetime(fin.game_date_et) - pd.Timestamp("2023-10-01")).dt.days.to_numpy()
    d1 = K.log_loss_per(y, p1, EPS) - K.log_loss_per(y, pc, EPS)      # H1
    d2 = K.log_loss_per(y, p0, EPS) - K.log_loss_per(y, p1, EPS)      # H2
    r = {h: K.moving_block_bootstrap(d, day, 7, 10000, 20261107) for h, d in (("H1", d1), ("H2", d2))}
    # RV-R5: run a sensitivity block length only when the window supports it; otherwise say so explicitly
    span = int(day.max() - day.min()) + 1
    sens = {}
    for h, d in (("H1", d1), ("H2", d2)):
        sens[h] = {}
        for bl in SENSITIVITY_BLOCK_DAYS:
            nb = span // bl
            if nb < MIN_BLOCKS:
                sens[h][bl] = {"status": "NOT_COMPUTED", "days": span, "nonoverlap_blocks": nb,
                               "reason": f"{span}-day final window gives {nb} non-overlapping {bl}-day blocks, "
                                         f"below the pre-registered minimum of {MIN_BLOCKS}"}
            else:
                sens[h][bl] = K.moving_block_bootstrap(d, day, bl, 10000, 20261107).__dict__
    ps = [r["H1"].p_one_sided, r["H2"].p_one_sided]
    adj = K.holm(ps) if all(np.isfinite(ps)) else [float("nan")] * 2
    floor = plan["practical_effect_floor"]
    decisions = {}
    for (h, rr), pa in zip(r.items(), adj):
        if rr.status != "OK":
            dec, why = "INSUFFICIENT_EVIDENCE", "fewer than 5 non-overlapping 7-day blocks"
        elif pa < 0.05 and rr.ci[0] > 0 and rr.mean >= floor:
            dec, why = "SURVIVED_PROTOCOL", "Holm p<0.05, CI>0, mean>=floor"
        elif rr.ci[1] < floor:
            dec, why = "NOT_SUPPORTED", "CI upper bound below practical floor"
        else:
            dec, why = "INSUFFICIENT_EVIDENCE", "CI includes values on both sides of the decision thresholds"
        decisions[h] = {"decision": dec, "reason": why, "mean_improvement_nats": rr.mean, "ci95": rr.ci,
                        "p_one_sided": rr.p_one_sided, "p_holm": pa, "n_games": rr.n_obs, "days": rr.n_days,
                        "nonoverlap_7d_blocks": rr.nonoverlap_blocks}
    if mode == "ORIGINAL":
        cust.spend(receipt_id)   # mark spent BEFORE results leave the evaluator (a replay needs it spent already)
    result = {"protocol_version": PROTOCOL, "run_type": "EvaluationRun", "phase": "FINAL", "mode": mode,
              "claim_plan_hash": plan["canonical_plan_hash"], "final_epoch_id": plan["final_epoch_id"],
              "exposure_receipt_id": receipt_id, "receipt_was_retry": receipt["retry"],
              "amendment": None if amendment is None else {k: amendment[k] for k in (
                  "amendment_id", "canonical_amendment_hash", "reason", "code_files")},
              "replay": replay,
              "code_config_environment_hash": current_code, "plan_code_hash": plan["code_hash"],
              "data_hashes": actual, "data_binding": "RECOMPUTED_FROM_INPUTS_EQUAL_TO_PLAN",
              "input_hash": input_hash,
              "data_mode": "REAL_NBA_RETROSPECTIVE", "pseudo_out_of_sample": True,
              "counts_coverage": {"final_games": len(final_ids), "c1_fallbacks_to_B0": fb,
                                  "dropped_games": 0},
              "scores": score_table(y, {"B0": p0, "B1": p1, "C1": pc}),
              "decisions": decisions, "sensitivity_exploratory": sens,
              "seed_manifest": {"bootstrap": 20261107},
              "ledger_history_of_receipt": cust.history(receipt_id),
              "caveats": ["Outcomes are public; LLM roles may have memorised them (pseudo-out-of-sample).",
                          "Single season; final = last ~25% of season incl. late-season rest/tanking effects.",
                          "Block bootstrap p-value is approximate under weak-dependence assumptions."],
              "created_at_utc": utc_now_iso()}
    name = ("game_prediction_final.json" if mode == "ORIGINAL"
            else f"game_prediction_final.replay-{amendment['amendment_id']}.json")
    (out / name).write_text(json.dumps(result, indent=2, default=str) + "\n", newline="\n")
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    cmd = sys.argv[1]
    try:
        if cmd == "amend":
            amend(Path(sys.argv[2]), Path(sys.argv[3]), " ".join(sys.argv[4:]))
        else:
            {"dev": dev, "freeze": freeze, "final": final}[cmd](Path(sys.argv[2]), Path(sys.argv[3]))
    except FinalRefused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        sys.exit(2)
