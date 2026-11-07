"""CONFIRMATORY lane: one pre-registered family evaluated once on the sealed 2024-25 season (D16-D18).

  dev    : run the exact registered procedures on 2023-24 DEVELOPMENT games (fit+tune+calibration) only.
           The 300 spent 2023-24 final games are never read. Output is exploratory, labelled DEVELOPMENT.
  seal   : seal a built season under the custodian before any claim runs on it. Reads only game ids and
           recomputes table hashes; computes no outcome statistic.
  freeze : write one plan per hypothesis (claim, estimand, test, null, threshold, sample) and a family
           manifest; register the family with the seal. Refuses to overwrite.
  final  : NOT TO BE RUN until the user authorises it (live demo). Verifies plans, code and sealed data,
           reserves the whole seal, runs the three tests, applies Holm, spends, writes the result.

Usage: python -I scripts/confirmatory.py dev    <data_2023-24> <evidence_dir>
       python -I scripts/confirmatory.py seal   <data_2024-25> <evidence_dir>
       python -I scripts/confirmatory.py freeze <data_2023-24> <evidence_dir>
       python -I scripts/confirmatory.py final  <data_2024-25> <evidence_dir> --authorised-by <name>
Refusals print "REFUSED: ..." and exit 2. The ledger is <evidence_dir>/custodian_ledger.jsonl; plans and
results go to <evidence_dir>/confirmatory-2024-25/.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from heatcheck import features as F, kernels as K, splits as S, store  # noqa: E402
from heatcheck.custodian import Custodian, ExposureRefused  # noqa: E402
from heatcheck.util import PROTOCOL, canonical_json, sha256_bytes, sha256_file, utc_now_iso  # noqa: E402

EPOCH_ID = "EPOCH-CONF-2024-25-001"
FAMILY_ID = "FAM-CONF-2024-25-v1"
SEASON = "2024-25"
SUBDIR = "confirmatory-2024-25"
CODE_FILES = ["src/heatcheck/features.py", "src/heatcheck/kernels.py", "src/heatcheck/custodian.py",
              "src/heatcheck/util.py", "src/heatcheck/store.py", "src/heatcheck/canonical.py",
              "src/heatcheck/splits.py", "scripts/build_confirmatory.py", "scripts/confirmatory.py"]
ALPHA = 0.05
DAY0 = "2023-10-01"

# Registered design, written before the development run and before any 2024-25 analysis (DECISIONS D17).
HYPOTHESES = {
    "CONF-HA": {
        "channel": "GAME_PREDICTION", "title": "Home advantage",
        "claim": "In 2024-25 NBA regular-season games not played at a neutral site, the designated home team "
                 "wins more than half of the games.",
        "estimand": "mean over eligible games of (home_win - 0.5); home_win includes overtime",
        "sample": "every sealed 2024-25 regular-season game with neutral_site == false (builder exclusions, "
                  "quarantined games (D19) and listed neutral sites removed); one row per game",
        "test": "moving-block bootstrap over calendar days (kernels.moving_block_bootstrap): block 7 days, "
                "B=10000, seed 20261108; one-sided p = (1 + #{centred boot >= mean}) / (B + 1)",
        "null": "mean(home_win) - 0.5 <= 0 (home teams win at most half of eligible games)",
        "params": {"kind": "home_advantage", "block_days": 7, "B": 10000, "seed": 20261108,
                   "practical_floor": 0.01, "min_games": 1000, "min_blocks": 5},
        "decision_rule": "SURVIVED_PROTOCOL iff Holm-adjusted p < 0.05 AND CI95 lower > 0 AND mean >= 0.01; "
                         "NOT_SUPPORTED iff CI95 upper < 0.01; INSUFFICIENT_EVIDENCE otherwise, or if fewer "
                         "than 1000 eligible games or fewer than 5 non-overlapping 7-day blocks",
    },
    "CONF-MOM": {
        "channel": "SHOT_ASSOCIATION", "title": "One-shot momentum",
        "claim": "In 2024-25, within a player's game, a field-goal attempt is more likely to be made after a "
                 "made field goal than after a missed one, beyond what within-player-game shuffling produces.",
        "estimand": "pooled P(make | previous FGA in same player-game made) - P(make | previous FGA missed)",
        "sample": "every 2024-25 field-goal attempt in sealed, non-quarantined games (D19; free throws out of "
                  "scope, D12) with a known shooter and resolved event order (shots in a period with a clock "
                  "regression excluded, D3)",
        "test": "permutation: outcomes shuffled within (player, game, shot value 2/3) strata, statistic "
                "recomputed, B=999, seed 20261109; one-sided p = (1 + #{T* >= T}) / (B + 1) (kernels.mc_pvalue)",
        "null": "outcomes are exchangeable within (player, game, shot value): no dependence on the previous shot",
        "params": {"kind": "streak", "k": 1, "B": 999, "seed": 20261109, "min_fga": 100000,
                   "min_opportunities": 1000},
        "decision_rule": "SURVIVED_PROTOCOL iff Holm-adjusted p < 0.05; otherwise INSUFFICIENT_EVIDENCE (no "
                         "equivalence test registered); INSUFFICIENT_EVIDENCE if the statistic is undefined, "
                         "eligible FGA < 100000 or either conditioning set < 1000",
        "interpretation_limit": "association under within-player-game exchangeability; not causal. Harness "
                                "family C (form drift, no streak) triggers the k=3 version 38% of the time.",
    },
    "CONF-HH": {
        "channel": "SHOT_ASSOCIATION", "title": "Hot hand (3 makes)",
        "claim": "In 2024-25, within a player's game, a field-goal attempt is more likely to be made after "
                 "three straight made field goals than after three straight misses, beyond what "
                 "within-player-game shuffling produces.",
        "estimand": "pooled P(make | previous 3 FGA in same player-game all made) - P(make | previous 3 all missed)",
        "sample": "as CONF-MOM",
        "test": "as DECISIONS D11 with B=999, seed 20261110 (permutation within player, game, shot value)",
        "null": "outcomes are exchangeable within (player, game, shot value): no streak dependence",
        "params": {"kind": "streak", "k": 3, "B": 999, "seed": 20261110, "min_fga": 100000,
                   "min_opportunities": 1000},
        "decision_rule": "as CONF-MOM",
        "interpretation_limit": "as CONF-MOM; 2023-24 development result was NOT_REJECTED (p=0.996, D11)",
    },
}


class Refused(RuntimeError):
    pass


def code_hash() -> str:
    return sha256_bytes(canonical_json({f: sha256_file(ROOT / f) for f in CODE_FILES}))


def _hashed(obj: dict, key: str) -> dict:
    body = {k: v for k, v in obj.items() if k != key}
    return {**body, key: sha256_bytes(canonical_json(body))}


def _check_hash(obj: dict, key: str, what: str) -> None:
    body = {k: v for k, v in obj.items() if k != key}
    if sha256_bytes(canonical_json(body)) != obj.get(key):
        raise Refused(f"{what} does not match its {key} (edited after freeze)")


# --------------------------------------------------------------------------- procedures (pure)
def home_advantage(games: pd.DataFrame, labels: pd.DataFrame, p: dict) -> dict:
    g = games[~games.neutral_site.astype(bool)].merge(labels[["game_id", "home_win"]], on="game_id")
    d = g.home_win.to_numpy(float) - 0.5
    day = (pd.to_datetime(g.game_date_et) - pd.Timestamp(DAY0)).dt.days.to_numpy()
    out = {"n_games": int(len(g)), "neutral_excluded": int(games.neutral_site.astype(bool).sum())}
    if len(g) == 0:
        return {**out, "status": "UNDEFINED"}
    r = K.moving_block_bootstrap(d, day, p["block_days"], p["B"], p["seed"], min_blocks=p["min_blocks"])
    return {**out, "status": "EXECUTED" if r.status == "OK" else r.status, "mean": r.mean,
            "home_win_rate": r.mean + 0.5, "ci95": list(r.ci), "p_one_sided": r.p_one_sided,
            "days": r.n_days, "nonoverlap_blocks": r.nonoverlap_blocks}


def shot_frame(events: pd.DataFrame, shot_labels: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    feat = F.preshot_features(events)
    feat = feat.merge(shot_labels[["target_id", "made"]], on="target_id", how="inner", validate="1:1")
    excluded = int(feat.ordering_unresolved.sum())
    f = feat[~feat.ordering_unresolved & feat.person_id.notna()].sort_values(["game_id", "person_id", "sequence"])
    return f, excluded


def streak_test(f: pd.DataFrame, p: dict) -> dict:
    made = f.made.to_numpy(np.int8)
    pg = (f.game_id + ":" + f.person_id.astype("int64").astype(str)).to_numpy()
    group = pd.factorize(pg)[0]
    strata = pd.factorize(pg + ":" + f.shot_value.astype(str))[0]
    hm, nm, hx, nx = K.streak_counts(made, group, p["k"])
    out = {"n_fga": int(len(f)), "hits_after_makes": hm, "n_after_makes": nm, "hits_after_misses": hx,
           "n_after_misses": nx}
    t = K.streak_diff(made, group, p["k"])
    if t is None:
        return {**out, "status": "UNDEFINED"}
    rng = np.random.default_rng(p["seed"])
    null = [v for v in (K.streak_diff(K.permute_within(made, strata, rng), group, p["k"]) for _ in range(p["B"]))
            if v is not None]
    null = np.array(null)
    return {**out, "status": "EXECUTED", "T": t, "p_make_after_makes": hm / nm, "p_make_after_misses": hx / nx,
            "null_mean": float(null.mean()), "null_sd": float(null.std(ddof=1)), "B_effective": int(len(null)),
            "p_one_sided": K.mc_pvalue(t, null)}


def run_family(games, game_labels, events, shot_labels, plans: dict, quarantined=frozenset()) -> dict:
    q = set(quarantined)   # D19: quarantined games are excluded from every sample
    games, game_labels = games[~games.game_id.isin(q)], game_labels[~game_labels.game_id.isin(q)]
    events, shot_labels = events[~events.game_id.isin(q)], shot_labels[~shot_labels.game_id.isin(q)]
    res = {"_quarantined_games_excluded": sorted(q)}
    for hid, plan in plans.items():
        if plan["params"]["kind"] == "home_advantage":
            res[hid] = home_advantage(games, game_labels, plan["params"])
    f, excluded = shot_frame(events, shot_labels)
    for hid, plan in plans.items():
        if plan["params"]["kind"] == "streak":
            res[hid] = {**streak_test(f, plan["params"]), "fga_excluded_ordering_unresolved": excluded}
    return res


def _quarantined(data: Path) -> list[str]:
    return sorted(store.read(data / "public.sqlite", "quarantine").game_id)


def decide(res: dict, plans: dict) -> dict:
    ids = sorted(plans)
    ps = [res[h].get("p_one_sided") if res[h]["status"] == "EXECUTED" else None for h in ids]
    finite = [i for i, v in enumerate(ps) if v is not None and np.isfinite(v)]
    adj = [None] * len(ids)
    for i, a in zip(finite, K.holm([ps[i] for i in finite])):   # Holm over the executed hypotheses
        adj[i] = a
    out = {}
    for i, h in enumerate(ids):
        r, pr, pa = res[h], plans[h]["params"], adj[i]
        if r["status"] != "EXECUTED":
            dec, why = "INSUFFICIENT_EVIDENCE", f"statistic status {r['status']}"
        elif pr["kind"] == "home_advantage":
            if r["n_games"] < pr["min_games"]:
                dec, why = "INSUFFICIENT_EVIDENCE", f"{r['n_games']} eligible games < {pr['min_games']}"
            elif pa < ALPHA and r["ci95"][0] > 0 and r["mean"] >= pr["practical_floor"]:
                dec, why = "SURVIVED_PROTOCOL", "Holm p<0.05, CI>0, mean>=floor"
            elif r["ci95"][1] < pr["practical_floor"]:
                dec, why = "NOT_SUPPORTED", "CI upper bound below practical floor"
            else:
                dec, why = "INSUFFICIENT_EVIDENCE", "CI or p-value does not meet the survival rule"
        else:
            if r["n_fga"] < pr["min_fga"] or min(r["n_after_makes"], r["n_after_misses"]) < pr["min_opportunities"]:
                dec, why = "INSUFFICIENT_EVIDENCE", "sample below the registered minimum"
            elif pa < ALPHA:
                dec, why = "SURVIVED_PROTOCOL", "Holm p<0.05 (association under the registered null, not causal)"
            else:
                dec, why = "INSUFFICIENT_EVIDENCE", "not rejected at Holm 0.05; no equivalence test registered"
        out[h] = {"decision": dec, "reason": why, "p_one_sided": r.get("p_one_sided"), "p_holm": pa}
    return out


# --------------------------------------------------------------------------- data access
def _read_events(data: Path, game_ids: list[str]) -> pd.DataFrame:
    con = sqlite3.connect(f"file:{data / 'public.sqlite'}?mode=ro", uri=True)
    try:
        ev = pd.read_sql(f"SELECT * FROM events WHERE game_id IN ({','.join('?' * len(game_ids))})",
                         con, params=game_ids)
    finally:
        con.close()
    return ev


def _games(data: Path) -> pd.DataFrame:
    g = store.read(data / "public.sqlite", "games")
    g["tip_utc"] = pd.to_datetime(g.tip_utc, utc=True)
    return g


# --------------------------------------------------------------------------- commands
def dev(data: Path, evidence: Path):
    """Registered procedures on 2023-24 development games only (exploratory)."""
    games = _games(data)
    sp, man = S.make_splits(games)
    dev_ids = sorted(sp[sp.split != "final"].game_id)
    final_ids = set(sp[sp.split == "final"].game_id)
    g = games[games.game_id.isin(dev_ids)]
    gl = store.read(data / "restricted_labels.sqlite", "game_labels")
    gl = gl[gl.game_id.isin(dev_ids)]
    sl = store.read(data / "restricted_labels.sqlite", "shot_labels")
    sl = sl[sl.game_id.isin(dev_ids)]
    ev = _read_events(data, dev_ids)
    if set(ev.game_id) & final_ids or set(gl.game_id) & final_ids or set(sl.game_id) & final_ids:
        raise Refused("development run touched spent 2023-24 final games")
    plans = {h: v for h, v in HYPOTHESES.items()}
    res = run_family(g, gl, ev, sl, plans)
    report = {"protocol_version": PROTOCOL, "lane": "CONFIRMATORY", "phase": "DEVELOPMENT",
              "data_mode": "REAL_NBA_RETROSPECTIVE", "season": "2023-24", "pseudo_out_of_sample": True,
              "games": len(dev_ids), "split_manifest_hash": man["split_manifest_hash"],
              "results": res, "development_decisions_if_rule_applied": decide(res, plans),
              "note": "Exploratory. Same code and parameters as the registered family; not a confirmatory result.",
              "code_hash": code_hash(), "created_utc": utc_now_iso()}
    out = evidence / SUBDIR
    out.mkdir(parents=True, exist_ok=True)
    (out / "dev_results_2023-24.json").write_text(json.dumps(report, indent=2, default=str) + "\n", newline="\n")
    print(json.dumps(report, indent=2, default=str))


def seal(data: Path, evidence: Path):
    mf = json.loads((data / "manifest.json").read_text())
    if mf.get("season") != SEASON:
        raise Refused(f"data dir is season {mf.get('season')}, expected {SEASON}")
    hashes = store.logical_table_hashes(data, store.SEASON_TABLES)
    if hashes != mf["logical_table_hashes"]:
        raise Refused("stored tables do not match manifest.json logical_table_hashes")
    ids = sorted(store.read(data / "public.sqlite", "games").game_id)
    cust = Custodian(evidence / "custodian_ledger.jsonl")
    entry = cust.seal(epoch_id=EPOCH_ID, record_ids=ids, input_hash=sha256_bytes(canonical_json(hashes)),
                      data_hashes=hashes, description=f"{SEASON} NBA regular season, sealed as confirmatory final "
                      "data before any claim runs on it (DECISIONS D16)")
    summary = {k: entry[k] for k in ("seal_id", "epoch_id", "input_hash", "data_hashes", "at_utc", "retry")}
    summary["n_games"] = len(entry["record_ids"])
    print(json.dumps(summary, indent=2))


def _seal_entry(cust: Custodian) -> dict:
    seals = [e for e in cust._entries() if e["type"] == "seal" and e["epoch_id"] == EPOCH_ID]
    if len(seals) != 1:
        raise Refused(f"expected exactly one seal for {EPOCH_ID}")
    return seals[0]


def freeze(data: Path, evidence: Path, overrides: dict | None = None):
    """Write the per-hypothesis plans and the family manifest, then register with the seal.
    `overrides` exists only for tests on temporary ledgers; the CLI never passes it."""
    out = evidence / SUBDIR
    out.mkdir(parents=True, exist_ok=True)
    cust = Custodian(evidence / "custodian_ledger.jsonl")
    sl = _seal_entry(cust)
    dev_file = out / "dev_results_2023-24.json"
    dev_ref = {"file": dev_file.name, "sha256": sha256_file(dev_file)} if dev_file.exists() else None
    plan_hashes = {}
    for hid, h in HYPOTHESES.items():
        h = json.loads(json.dumps(h))
        if overrides and hid in overrides:
            h["params"].update(overrides[hid])
        path = out / f"{hid}.plan.json"
        if path.exists():
            raise Refused(f"{path.name} already exists; plans are frozen and never overwritten")
        plan = _hashed({"protocol_version": PROTOCOL, "hypothesis_id": hid, **h, "season": SEASON,
                        "data_mode": "REAL_NBA_RETROSPECTIVE", "final_epoch_id": EPOCH_ID,
                        "development_reference": dev_ref,
                        "registered_before": "any 2024-25 claim evaluation; seal " + sl["seal_id"]},
                       "canonical_plan_hash")
        path.write_text(json.dumps(plan, indent=2) + "\n", newline="\n")
        plan_hashes[hid] = plan["canonical_plan_hash"]
    fam = _hashed({"protocol_version": PROTOCOL, "family_id": FAMILY_ID, "final_epoch_id": EPOCH_ID,
                   "seal_id": sl["seal_id"], "sealed_input_hash": sl["input_hash"],
                   "sealed_data_hashes": sl["data_hashes"], "n_sealed_games": len(sl["record_ids"]),
                   "hypotheses": plan_hashes,
                   "multiplicity": f"Holm over the {len(plan_hashes)} hypotheses at alpha={ALPHA}",
                   "code_files": CODE_FILES, "code_hash": code_hash(),
                   "authorisation": "final run requires explicit user authorisation (live demo)",
                   "created_utc": utc_now_iso()}, "canonical_family_hash")
    (out / "family.json").write_text(json.dumps(fam, indent=2) + "\n", newline="\n")
    reg = cust.register(epoch_id=EPOCH_ID, family_id=FAMILY_ID, plan_hash=fam["canonical_family_hash"],
                        code_hash=fam["code_hash"])
    print(json.dumps({"family": fam, "registration": reg}, indent=2))


def final(data: Path, evidence: Path, authorised_by: str):
    if not authorised_by:
        raise Refused("final needs --authorised-by <name>: no confirmatory test until the user says so")
    out = evidence / SUBDIR
    fam = json.loads((out / "family.json").read_text())
    _check_hash(fam, "canonical_family_hash", "family.json")
    plans = {}
    for hid, ph in fam["hypotheses"].items():
        plan = json.loads((out / f"{hid}.plan.json").read_text())
        _check_hash(plan, "canonical_plan_hash", f"{hid}.plan.json")
        if plan["canonical_plan_hash"] != ph:
            raise Refused(f"{hid} plan hash differs from the family manifest")
        plans[hid] = plan
    if code_hash() != fam["code_hash"]:
        raise Refused("code changed since the family was frozen; a confirmatory run cannot be amended")
    hashes = store.logical_table_hashes(data, store.SEASON_TABLES)
    if hashes != fam["sealed_data_hashes"]:
        raise Refused(f"input data differ from the sealed data: {sorted(k for k in hashes if hashes[k] != fam['sealed_data_hashes'].get(k))}")
    input_hash = sha256_bytes(canonical_json(hashes))
    games = _games(data)
    ids = sorted(games.game_id)
    cust = Custodian(evidence / "custodian_ledger.jsonl")
    receipt = cust.reserve(family_id=FAMILY_ID, epoch_id=EPOCH_ID, plan_hash=fam["canonical_family_hash"],
                           code_hash=fam["code_hash"], record_ids=ids, input_hash=input_hash)
    # ---- inside custodian scope
    gl = store.read(data / "restricted_labels.sqlite", "game_labels")
    sl = store.read(data / "restricted_labels.sqlite", "shot_labels")
    ev = _read_events(data, ids)
    res = run_family(games, gl, ev, sl, plans, _quarantined(data))
    decisions = decide(res, plans)
    cust.spend(receipt["receipt_id"])   # spent BEFORE results leave the evaluator
    result = {"protocol_version": PROTOCOL, "run_type": "EvaluationRun", "phase": "FINAL", "lane": "CONFIRMATORY",
              "season": SEASON, "family_id": FAMILY_ID, "family_hash": fam["canonical_family_hash"],
              "plan_hashes": fam["hypotheses"], "final_epoch_id": EPOCH_ID, "authorised_by": authorised_by,
              "exposure_receipt_id": receipt["receipt_id"], "receipt_was_retry": receipt["retry"],
              "code_hash": fam["code_hash"], "data_hashes": hashes, "input_hash": input_hash,
              "data_mode": "REAL_NBA_RETROSPECTIVE", "pseudo_out_of_sample": True,
              "results": res, "decisions": decisions, "multiplicity": fam["multiplicity"],
              "ledger_history_of_receipt": cust.history(receipt["receipt_id"]),
              "caveats": ["2024-25 outcomes are public; LLM roles may have memorised them (pseudo-out-of-sample).",
                          "Shot-test survival is association under within-player-game exchangeability, not causal.",
                          "Block bootstrap p-value is approximate under weak-dependence assumptions."],
              "created_at_utc": utc_now_iso()}
    (out / "final_result.json").write_text(json.dumps(result, indent=2, default=str) + "\n", newline="\n")
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    cmd = sys.argv[1]
    try:
        if cmd == "final":
            who = sys.argv[sys.argv.index("--authorised-by") + 1] if "--authorised-by" in sys.argv else ""
            final(Path(sys.argv[2]), Path(sys.argv[3]), who)
        else:
            {"dev": dev, "seal": seal, "freeze": freeze}[cmd](Path(sys.argv[2]), Path(sys.argv[3]))
    except (Refused, ExposureRefused) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        sys.exit(2)
