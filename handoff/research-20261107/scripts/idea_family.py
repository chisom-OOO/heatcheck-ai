"""Run a family of templated ideas (docs/IDEA_GRAMMAR.md).

Usage: python -I scripts/idea_family.py dev       <data_2023-24> <request.json> <out_dir>
       python -I scripts/idea_family.py synthetic <request.json> <out_dir> --family A --gamma 0.30 --seed <n>

dev       : 2023-24 DEVELOPMENT games only (fit+tune+calibration). Refuses any other season. The 300 spent
            final games and the sealed 2024-25 season are never read.
synthetic : a planted-truth league from simulate.generate. The runner keeps the truth; the family sees only
            the league view. truth.json and scoreboard.json are written AFTER results.json.
Refusals print "REFUSED: ..." and exit 2. Outputs are write-once.
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

from heatcheck import features as F, ideas as I, simulate as SIM, splits as S, store  # noqa: E402
from heatcheck.util import canonical_json, sha256_bytes, sha256_file, utc_now_iso  # noqa: E402

CODE_FILES = ["src/heatcheck/ideas.py", "src/heatcheck/kernels.py", "src/heatcheck/features.py",
              "src/heatcheck/splits.py", "src/heatcheck/store.py", "src/heatcheck/util.py",
              "src/heatcheck/simulate.py", "scripts/idea_family.py"]
SYNTH_PERIOD_STREAM = 7_777_777   # separate random stream for synthetic period labels (planted NULL)


def code_hash() -> str:
    return sha256_bytes(canonical_json({f: sha256_file(ROOT / f) for f in CODE_FILES}))


# --------------------------------------------------------------------------- development data (2023-24 only)
def load_development(data: Path):
    mf = json.loads((data / "manifest.json").read_text())
    if mf.get("season") != "2023-24":
        raise I.IdeaRefused(f"development mode accepts only the 2023-24 build; this data dir is {mf.get('season')!r}")
    games = store.read(data / "public.sqlite", "games")
    if not games.game_id.str.startswith("00223").all():
        raise I.IdeaRefused("development data contains non-2023-24 game ids")
    games["tip_utc"] = pd.to_datetime(games.tip_utc, utc=True)
    games["neutral_site"] = games.neutral_site.astype(bool)
    sp, man = S.make_splits(games)
    dev_ids = sorted(sp[sp.split != "final"].game_id)
    final_ids = set(sp[sp.split == "final"].game_id)
    # labels: development games only (the spent final games' labels are never read into this process's views)
    con = sqlite3.connect(f"file:{data / 'restricted_labels.sqlite'}?mode=ro", uri=True)
    q = ",".join("?" * len(dev_ids))
    gl = pd.read_sql(f"SELECT game_id, home_win FROM game_labels WHERE game_id IN ({q})", con, params=dev_ids)
    sl = pd.read_sql(f"SELECT target_id, game_id, made FROM shot_labels WHERE game_id IN ({q})", con, params=dev_ids)
    con.close()
    seed = F.seed_elo(store.read(data / "public.sqlite", "games_2022"),
                      store.read(data / "restricted_labels.sqlite", "game_labels_2022"))
    g = games[games.game_id.isin(dev_ids)]
    feat = F.pregame_features(g, gl, seed, set(dev_ids)).merge(gl, on="game_id")
    feat = feat[~feat.neutral_site]
    game_view = I.GameView(feat[["game_id", "home_win", "home_rest", "away_rest", "home_b2b", "away_b2b",
                                 "elo_diff", "game_date_et"]].reset_index(drop=True))
    con = sqlite3.connect(f"file:{data / 'public.sqlite'}?mode=ro", uri=True)
    ev = pd.read_sql(f"SELECT * FROM events WHERE game_id IN ({q})", con, params=dev_ids)
    con.close()
    pf = F.preshot_features(ev).merge(sl[["target_id", "made"]], on="target_id", how="inner", validate="1:1")
    pf = pf[~pf.ordering_unresolved & pf.person_id.notna()].sort_values(["game_id", "person_id", "sequence"])
    pg = (pf.game_id + ":" + pf.person_id.astype("int64").astype(str)).to_numpy()
    shot_view = I.ShotView(made=pf.made.to_numpy(np.int8), group=pd.factorize(pg)[0],
                           value=pf.shot_value.to_numpy(int), period=np.minimum(pf.period.to_numpy(int), 5))
    for ids in (set(game_view.frame.game_id), set(pf.game_id)):
        if ids & final_ids or not ids <= set(dev_ids):
            raise I.IdeaRefused("a development view contains a non-development game")
    identity = {"season": "2023-24", "split": "development (fit+tune+calibration)",
                "split_manifest_hash": man["split_manifest_hash"],
                "logical_table_hashes": store.logical_table_hashes(data),
                "game_view_sha256": game_view.identity(), "shot_view_sha256": shot_view.identity(),
                "n_games": int(len(game_view.frame)), "n_fga": int(len(shot_view.made))}
    return game_view, shot_view, identity


def dev(data: Path, request: Path, out: Path):
    ideas = I.validate_request(request.read_text(), "development")
    game_view, shot_view, identity = load_development(data)

    views = {"GAME_HOME_WIN_SPLIT": game_view, "SHOT_MAKE_AFTER_CONDITION": shot_view}
    res = I.run_family(ideas, views, out, mode="development", data_identity=identity, code_hash=code_hash())
    print(json.dumps(res, indent=2, default=float))


# --------------------------------------------------------------------------- synthetic
def synthetic(request: Path, out: Path, family: str, gamma: float, seed: int):
    ideas = I.validate_request(request.read_text(), "synthetic")
    league, truth = SIM.generate(seed, family, gamma)            # the runner holds `truth`
    period = np.random.default_rng(seed + SYNTH_PERIOD_STREAM).integers(1, 5, size=len(league.made))
    view = I.ShotView(made=league.made, group=league.group, value=league.value, period=period)
    identity = {"league_view_sha256": view.identity(), "n_fga": int(len(view.made)),
                "note": "simulator family, planted effect and seed are withheld until results are written"}
    res = I.run_family(ideas, {"SHOT_MAKE_AFTER_CONDITION": view}, out, mode="synthetic", data_identity=identity,
                       code_hash=code_hash())
    # truth revealed only now, after results.json exists
    if not (out / "results.json").exists():
        raise I.IdeaRefused("results.json missing; truth is not revealed")
    t = {"revealed_after": "results.json", "results_sha256": sha256_file(out / "results.json"),
         "simulator_family": truth.family, "gamma_logodds": truth.gamma_logodds, "seed": truth.seed,
         "form_sd": truth.form_sd, "planted_label": truth.label,
         "synthetic_period_labels": f"uniform 1-4 from default_rng(seed + {SYNTH_PERIOD_STREAM}); planted NULL",
         "created_utc": utc_now_iso()}
    with open(out / "truth.json", "x", newline="\n") as f:
        f.write(json.dumps(t, indent=2) + "\n")
    sb = {"results_sha256": t["results_sha256"], **I.scoreboard(res, ideas, truth.gamma_logodds),
          "created_utc": utc_now_iso()}
    with open(out / "scoreboard.json", "x", newline="\n") as f:
        f.write(json.dumps(sb, indent=2, default=float) + "\n")
    print(json.dumps(sb, indent=2, default=float))


if __name__ == "__main__":
    try:
        cmd = sys.argv[1]
        if cmd == "dev":
            dev(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]))
        elif cmd == "synthetic":
            a = sys.argv
            synthetic(Path(a[2]), Path(a[3]), a[a.index("--family") + 1], float(a[a.index("--gamma") + 1]),
                      int(a[a.index("--seed") + 1]))
        else:
            raise I.IdeaRefused(f"unknown command {cmd!r}")
    except (I.IdeaRefused, FileExistsError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        sys.exit(2)
