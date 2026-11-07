"""Build the sealed confirmatory season (2024-25 regular season) in the canonical format (DECISIONS D16).

Usage: python -I scripts/build_confirmatory.py <repo_dir> <out_dir> <extracted_dir>

<repo_dir> holds datasets/cdnnba_2024.tar.xz, datasets/nbastats_2024.tar.xz and COMMIT. Archives must match
PINNED below (sha256, byte count and the git blob id listed in the upstream commit's tree), or the build stops.
Writes public.sqlite {games, events, exclusions}, restricted_labels.sqlite {game_labels, shot_labels},
reconciliation_2024.csv and manifest.json. Prints ONLY counts, hashes and reconciliation status counts:
no outcome statistic (win rate, make rate, score) is computed or printed. The builder reads outcome
fields mechanically to derive labels and to reconcile final scores.
"""
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd  # noqa: E402

from heatcheck import canonical, store  # noqa: E402
from heatcheck.util import PROTOCOL, frame_hash, sha256_file, upstream_revision, utc_now_iso  # noqa: E402

SEASON = "2024-25"
UPSTREAM = "https://github.com/shufinskiy/nba_data"
UPSTREAM_COMMIT = "46488f0f8e1cab58fc1256511ea808166a443a15"
PINNED = {  # verified 2026-11-07: raw download == upstream tree blob id and size at UPSTREAM_COMMIT
    "cdnnba_2024.tar.xz": {"sha256": "35a82e6b29821adb22b8474dea8c51e08847d8e00690d1d5ffde7d000e0087d1",
                           "bytes": 18886652, "git_blob": "4ff09ac1238a28a0e213c0f4e950b6848cf6f230"},
    "nbastats_2024.tar.xz": {"sha256": "8f370da00ad0a6d4157921bd161d56ea32647a165d906516f2b36384a6a4989a",
                             "bytes": 8583784, "git_blob": "acda11afb5fdb4cbee610e62b66e19915ef3de22"},
}
REGULAR_SEASON_ID = re.compile(r"00224[0-9]{5}")
RIGHTS = ("nba_data repo is Apache-2.0; upstream NBA data/redistribution rights NOT established by that licence. "
          "Internal research use only; do not redistribute raw files (DECISIONS D9).")


def git_blob_id(path: Path) -> str:
    data = path.read_bytes()
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def verify_archives(repo: Path) -> None:
    for name, pin in PINNED.items():
        f = repo / "datasets" / name
        got = {"sha256": sha256_file(f), "bytes": f.stat().st_size, "git_blob": git_blob_id(f)}
        if got != pin:
            raise SystemExit(f"REFUSED: {name} does not match its pin: {got} != {pin}")


def main(repo: Path, out: Path, extracted: Path):
    rev = upstream_revision(repo)
    if rev != UPSTREAM_COMMIT:
        raise SystemExit(f"REFUSED: upstream revision {rev} != pinned {UPSTREAM_COMMIT}")
    verify_archives(repo)
    out.mkdir(parents=True, exist_ok=True)
    snaps = [canonical.register_raw(repo / "datasets" / f, out / "rawstore", provider=p, upstream=UPSTREAM,
                                    revision=rev, rights_note=RIGHTS)
             for f, p in [("cdnnba_2024.tar.xz", "cdnnba"), ("nbastats_2024.tar.xz", "nbastats")]]
    b = canonical.build_canonical(extracted / "cdnnba_2024.csv", SEASON, neutral_sites=canonical.NEUTRAL_SITE_2024)

    # only 2024-25 regular-season game ids are sealed (e.g. the NBA Cup final does not count)
    bad = sorted(set(b.games.game_id[~b.games.game_id.str.fullmatch(REGULAR_SEASON_ID.pattern)]))
    games = b.games[~b.games.game_id.isin(bad)].reset_index(drop=True)
    events = b.events[b.events.game_id.isin(games.game_id)].reset_index(drop=True)
    game_labels = b.game_labels[b.game_labels.game_id.isin(games.game_id)].reset_index(drop=True)
    shot_labels = b.shot_labels[b.shot_labels.game_id.isin(games.game_id)].reset_index(drop=True)
    exclusions = pd.concat([b.exclusions, pd.DataFrame({"game_id": bad, "reason": "not a 2024-25 regular-season game id"})],
                           ignore_index=True)

    rec = canonical.reconcile_nbastats(games, game_labels, extracted / "nbastats_2024.csv")
    store.publish(out / "public.sqlite", {"games": games, "events": events, "exclusions": exclusions})
    store.publish(out / "restricted_labels.sqlite", {"game_labels": game_labels, "shot_labels": shot_labels},
                  restricted=True)
    rec.to_csv(out / "reconciliation_2024.csv", index=False, lineterminator="\n")

    hashes = {
        "games": frame_hash(games, ["game_id"]),
        "events": frame_hash(events, ["game_id", "sequence"]),
        "exclusions": frame_hash(exclusions, ["game_id"]),
        "game_labels": frame_hash(game_labels, ["game_id"]),
        "shot_labels": frame_hash(shot_labels, ["target_id"]),
    }
    stored = store.logical_table_hashes(out, store.SEASON_TABLES)
    if stored != hashes:
        raise SystemExit(f"REFUSED: stored tables do not round-trip to the built hashes: {stored} != {hashes}")
    diag = dict(b.diagnostics, non_regular_season_ids_excluded=bad, games_sealable=int(len(games)),
                events_sealable=int(len(events)), field_goal_attempts_sealable=int(len(shot_labels)))
    manifest = {
        "protocol_version": PROTOCOL, "manifest_type": "confirmatory_season_manifest",
        "season": SEASON, "competition": "NBA_REGULAR_SEASON", "created_utc": utc_now_iso(),
        "transformation_revision": {"canonical.py": sha256_file(ROOT / "src/heatcheck/canonical.py"),
                                    "build_confirmatory.py": sha256_file(Path(__file__))},
        "raw_snapshots": snaps, "pinned_archives": PINNED, "logical_table_hashes": hashes,
        "record_counts": diag, "reconciliation": rec.status.value_counts().to_dict(),
        "external_crosscheck": {"balldontlie": "NOT_RUN: no user key; coverage UNVERIFIED_EXTERNAL"},
        "exclusions": exclusions.to_dict("records"), "rights_note": RIGHTS,
        "data_mode": "REAL_NBA_RETROSPECTIVE", "pseudo_out_of_sample": True,
        "access_note": "Sealed final data. Only counts/hashes printed; no claim or outcome statistic computed.",
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str) + "\n", newline="\n")
    print(json.dumps({"hashes": hashes, "counts": diag, "reconciliation": manifest["reconciliation"],
                      "exclusions": manifest["exclusions"]}, indent=2, default=str))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
