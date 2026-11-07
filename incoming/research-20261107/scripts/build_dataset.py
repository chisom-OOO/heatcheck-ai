"""Build the frozen 2023-24 canonical dataset + manifest + reconciliation report.

Usage: python -I scripts/build_dataset.py <repo_dir> <out_dir>
Deterministic: rerunning on the same snapshot yields identical logical table hashes.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd  # noqa: E402

from heatcheck import canonical, store  # noqa: E402
from heatcheck.util import PROTOCOL, frame_hash, sha256_file, utc_now_iso  # noqa: E402

RIGHTS = ("nba_data repo is Apache-2.0; upstream NBA data/redistribution rights NOT established by that licence. "
          "Internal research use only; do not redistribute raw files (DECISIONS D9).")
UPSTREAM = "https://github.com/shufinskiy/nba_data"


def main(repo: Path, out: Path, extracted: Path):
    import subprocess
    try:
        rev = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True,
                                      stderr=subprocess.DEVNULL).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        rev = (repo / "COMMIT").read_text().strip()   # bundled copy without .git
    out.mkdir(parents=True, exist_ok=True)
    snaps = [canonical.register_raw(repo / "datasets" / f, out / "rawstore", provider=p, upstream=UPSTREAM,
                                    revision=rev, rights_note=RIGHTS)
             for f, p in [("cdnnba_2023.tar.xz", "cdnnba"), ("nbastats_2023.tar.xz", "nbastats"),
                          ("cdnnba_2022.tar.xz", "cdnnba")]]

    b23 = canonical.build_canonical(extracted / "cdnnba_2023.csv", "2023-24")
    b22 = canonical.build_canonical(extracted / "cdnnba_2022.csv", "2022-23")
    rec = canonical.reconcile_nbastats(b23.games, b23.game_labels, extracted / "nbastats_2023.csv")

    store.publish(out / "public.sqlite", {"games": b23.games, "events": b23.events,
                                          "exclusions": b23.exclusions,
                                          "games_2022": b22.games})
    store.publish(out / "restricted_labels.sqlite", {"game_labels": b23.game_labels,
                                                     "shot_labels": b23.shot_labels,
                                                     "game_labels_2022": b22.game_labels}, restricted=True)
    rec.to_csv(out / "reconciliation_2023.csv", index=False)

    hashes = {
        "games": frame_hash(b23.games, ["game_id"]),
        "events": frame_hash(b23.events, ["game_id", "sequence"]),
        "game_labels": frame_hash(b23.game_labels, ["game_id"]),
        "shot_labels": frame_hash(b23.shot_labels, ["target_id"]),
        "exclusions": frame_hash(b23.exclusions, ["game_id"]),
        "games_2022": frame_hash(b22.games, ["game_id"]),
        "game_labels_2022": frame_hash(b22.game_labels, ["game_id"]),
    }
    manifest = {
        "protocol_version": PROTOCOL,
        "manifest_type": "frozen_season_manifest",
        "season": "2023-24", "competition": "NBA_REGULAR_SEASON",
        "created_utc": utc_now_iso(),
        "transformation_revision": {"canonical.py": sha256_file(ROOT / "src/heatcheck/canonical.py"),
                                    "build_dataset.py": sha256_file(Path(__file__))},
        "raw_snapshots": snaps,
        "logical_table_hashes": hashes,
        "record_counts": {"2023-24": b23.diagnostics, "2022-23": b22.diagnostics},
        "reconciliation": rec.status.value_counts().to_dict(),
        "external_crosscheck": {"balldontlie": "NOT_RUN: no user key in this session; coverage UNVERIFIED_EXTERNAL"},
        "exclusions_2023": b23.exclusions.to_dict("records"),
        "rights_note": RIGHTS,
        "data_mode": "REAL_NBA_RETROSPECTIVE",
        "pseudo_out_of_sample": True,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str))
    print(json.dumps({"hashes": hashes, "counts": manifest["record_counts"],
                      "reconciliation": manifest["reconciliation"],
                      "exclusions": manifest["exclusions_2023"]}, indent=2, default=str))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
