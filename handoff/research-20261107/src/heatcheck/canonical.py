"""Raw snapshot registration and canonical game/event/label tables from cdnnba play-by-play.

Separation of concerns:
  * games      — identity, schedule, teams, status. NO outcome fields.
  * events     — play-by-play actions in documented order (contains shot results: these are
                 inputs to *later* events' features; feature builders must use strictly earlier rows).
  * labels     — RESTRICTED: game outcomes (home win, final score, finalisation time) and shot outcomes.
"""
from __future__ import annotations

import json
import shutil
import tarfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from .util import PROTOCOL, et_date, sha256_file, utc_now_iso

NEUTRAL_SITE_2023 = {
    # (ET date, frozenset of team tricodes) — DECISIONS.md D10
    ("2023-11-09", frozenset({"ATL", "ORL"})),
    ("2024-01-11", frozenset({"BKN", "CLE"})),
    ("2023-12-07", frozenset({"IND", "MIL"})),
    ("2023-12-07", frozenset({"LAL", "NOP"})),
}

NEUTRAL_SITE_2024 = {
    # 2024-25 regular season, checked 2026-11-07 (DECISIONS D16): Mexico City (WAS designated home),
    # Paris x2 (IND home 01-23, SAS home 01-25), NBA Cup semifinals in Las Vegas (12-14). The Cup final
    # (12-17, MIL-OKC) does not count as a regular-season game; listed so it is flagged if present.
    ("2024-11-02", frozenset({"MIA", "WAS"})),
    ("2025-01-23", frozenset({"IND", "SAS"})),
    ("2025-01-25", frozenset({"IND", "SAS"})),
    ("2024-12-14", frozenset({"MIL", "ATL"})),
    ("2024-12-14", frozenset({"OKC", "HOU"})),
    ("2024-12-17", frozenset({"MIL", "OKC"})),
}

SCHEMA_VERSION = "canonical/1"


# --------------------------------------------------------------------------- raw store
def register_raw(archive: Path, store: Path, *, provider: str, upstream: str, revision: str,
                 rights_note: str) -> dict:
    """Copy an archive into a content-addressed store and return its snapshot record."""
    digest = sha256_file(archive)
    dest = store / "objects" / digest[:2] / digest
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        shutil.copyfile(archive, dest)
    with tarfile.open(archive, "r:xz") as t:
        members = [m.name for m in t.getmembers()]
    return {
        "provider": provider,
        "upstream": upstream,
        "upstream_revision": revision,
        "path_in_upstream": f"datasets/{archive.name}",
        "retrieval_utc": utc_now_iso(),
        "payload_sha256": digest,
        "byte_count": archive.stat().st_size,
        "members": members,
        "schema_version": SCHEMA_VERSION,
        "rights_note": rights_note,
    }


# --------------------------------------------------------------------------- parsing
def _clock_seconds(clock: pd.Series) -> pd.Series:
    m = clock.str.extract(r"^PT(\d+)M([\d.]+)S$")
    return m[0].astype(float) * 60 + m[1].astype(float)


def _elapsed(period: pd.Series, sec_left: pd.Series) -> pd.Series:
    reg = (period - 1) * 720 + (720 - sec_left)
    ot = 2880 + (period - 5) * 300 + (300 - sec_left)
    return np.where(period <= 4, reg, ot)


@dataclass
class CanonicalBuild:
    games: pd.DataFrame
    events: pd.DataFrame
    game_labels: pd.DataFrame
    shot_labels: pd.DataFrame
    exclusions: pd.DataFrame
    diagnostics: dict = field(default_factory=dict)


def build_canonical(csv_path: Path, season: str, competition: str = "NBA_REGULAR_SEASON",
                    neutral_sites: set = NEUTRAL_SITE_2023) -> CanonicalBuild:
    raw = pd.read_csv(csv_path, low_memory=False, dtype={"qualifiers": str, "personIdsFilter": str})
    diag: dict = {"raw_rows": int(len(raw)), "raw_games": int(raw.gameId.nunique())}

    e = pd.DataFrame({
        "game_id": raw.gameId.astype("int64").map(lambda g: f"00{g}"),
        "provider": "cdnnba",
        "provider_event_id": raw.actionNumber.astype("int64"),
        "revision_utc": pd.to_datetime(raw.edited, utc=True, format="ISO8601", errors="coerce"),
        "sequence": raw.orderNumber.astype("int64"),
        "period": raw.period.astype("int64"),
        "period_type": raw.periodType,
        "clock_sec_left": _clock_seconds(raw.clock),
        "event_time_utc": pd.to_datetime(raw.timeActual, utc=True, format="ISO8601", errors="coerce"),
        "team_id": raw.teamId.astype("Int64"),
        "team_tricode": raw.teamTricode,
        "person_id": raw.personId.astype("Int64"),
        "action_type": raw.actionType,
        "sub_type": raw.subType,
        "qualifiers": raw.qualifiers.fillna(""),
        "is_field_goal": raw.isFieldGoal.astype("int64"),
        "shot_result": raw.shotResult,       # outcome of THIS action; never a feature for this action
        "shot_distance": raw.shotDistance,
        "area": raw.area,
        "x": raw.x, "y": raw.y,
        "score_home_after": raw.scoreHome.astype("int64"),
        "score_away_after": raw.scoreAway.astype("int64"),
        # post-outcome annotations kept in events for audit, banned from pre-shot features
        "descriptor": raw.descriptor,
        "assist_person_id": raw.assistPersonId.astype("Int64"),
        "block_person_id": raw.blockPersonId.astype("Int64"),
    })
    e["elapsed_sec"] = _elapsed(e.period, e.clock_sec_left)
    e = e.sort_values(["game_id", "sequence"], kind="mergesort").reset_index(drop=True)
    g = e.groupby("game_id", sort=False)
    e["clock_regress"] = (g.elapsed_sec.diff() < 0).fillna(False)

    # ---------------- duplicates
    dup_seq = int(e.duplicated(["game_id", "sequence"]).sum())
    dup_evt = int(e.duplicated(["game_id", "provider_event_id"]).sum())
    diag.update(duplicate_sequence=dup_seq, duplicate_event_id=dup_evt,
                clock_regress_steps=int(e.clock_regress.sum()))

    # ---------------- per-game derivations
    e["d_home"] = g.score_home_after.diff().fillna(e.score_home_after)
    e["d_away"] = g.score_away_after.diff().fillna(e.score_away_after)
    scoring = e[(e.d_home > 0) | (e.d_away > 0)]
    home_team = (scoring[scoring.d_home > 0].groupby("game_id").team_id
                 .agg(lambda s: s.dropna().unique().tolist()))
    away_team = (scoring[scoring.d_away > 0].groupby("game_id").team_id
                 .agg(lambda s: s.dropna().unique().tolist()))
    tri = e.dropna(subset=["team_id"]).groupby("team_id").team_tricode.agg(lambda s: s.mode().iat[0])

    pstart = e[(e.action_type == "period") & (e.sub_type == "start")]
    tip = pstart[pstart.period == 1].groupby("game_id").event_time_utc.min()
    gend = e[(e.action_type == "game") & (e.sub_type == "end")].groupby("game_id").agg(
        final_home=("score_home_after", "last"), final_away=("score_away_after", "last"),
        final_time_utc=("event_time_utc", "last"), final_revision_utc=("revision_utc", "max"))
    maxp = g.period.max()

    # points recomputed from made shots, independent of running score columns
    made = e[e.shot_result == "Made"].copy()
    made["pts"] = np.select([made.action_type == "3pt", made.action_type == "2pt",
                             made.action_type == "freethrow"], [3, 2, 1], 0)

    rows, excl = [], []
    for gid in e.game_id.unique():
        reasons = []
        h, a = home_team.get(gid, []), away_team.get(gid, [])
        if len(h) != 1 or len(a) != 1 or h == a:
            reasons.append(f"home/away not uniquely derivable (home={h}, away={a})")
        if gid not in gend.index:
            reasons.append("no game-end action")
        if gid not in tip.index or pd.isna(tip.get(gid)):
            reasons.append("no period-1 start time")
        if reasons:
            excl.append({"game_id": gid, "reason": "; ".join(reasons)})
            continue
        hid, aid = int(h[0]), int(a[0])
        fh, fa = int(gend.at[gid, "final_home"]), int(gend.at[gid, "final_away"])
        mg = made[made.game_id == gid]
        pts_h = int(mg[mg.team_id == hid].pts.sum()); pts_a = int(mg[mg.team_id == aid].pts.sum())
        if (pts_h, pts_a) != (fh, fa):
            # team-credited points can differ legitimately (e.g. own-basket); record, don't silently fix
            excl_reason = f"made-shot points {pts_h}-{pts_a} != final {fh}-{fa}"
        else:
            excl_reason = None
        if fh == fa:
            excl.append({"game_id": gid, "reason": f"tied final score {fh}-{fa}"}); continue
        t = tip.at[gid]
        rows.append({
            "game_id": gid, "season": season, "competition": competition,
            "provider_game_id_cdnnba": gid,
            "home_team_id": hid, "away_team_id": aid,
            "home_tricode": tri.get(hid), "away_tricode": tri.get(aid),
            "tip_utc": t, "game_date_et": str(t.tz_convert("America/New_York").date()),
            "status": "FINAL", "periods": int(maxp.at[gid]),
            "neutral_site": False, "points_check": "OK" if excl_reason is None else excl_reason,
            "_fh": fh, "_fa": fa, "_ft": gend.at[gid, "final_time_utc"], "_fr": gend.at[gid, "final_revision_utc"],
        })
    games = pd.DataFrame(rows)
    games["neutral_site"] = [
        (d, frozenset({ht, at})) in neutral_sites
        for d, ht, at in zip(games.game_date_et, games.home_tricode, games.away_tricode)]
    diag["neutral_site_games_flagged"] = int(games.neutral_site.sum())

    game_labels = pd.DataFrame({
        "target_id": "GAME:" + games.game_id, "game_id": games.game_id,
        "home_win": (games._fh > games._fa).astype(int),
        "final_home": games._fh, "final_away": games._fa,
        "finalization_utc": games._ft, "revision_utc": games._fr,
    })
    games = games.drop(columns=["_fh", "_fa", "_ft", "_fr"])

    keep = set(games.game_id)
    events = e[e.game_id.isin(keep)].drop(columns=["d_home", "d_away"]).reset_index(drop=True)
    shots = events[events.is_field_goal == 1]
    shot_labels = pd.DataFrame({
        "target_id": "SHOT:" + shots.game_id + ":" + shots.sequence.astype(str),
        "game_id": shots.game_id, "sequence": shots.sequence,
        "made": (shots.shot_result == "Made").astype(int),
        "first_observation_utc": shots.event_time_utc, "revision_utc": shots.revision_utc,
    })
    diag.update(games_included=int(len(games)), games_excluded=int(len(excl)),
                events_included=int(len(events)), field_goal_attempts=int(len(shots)),
                points_check_mismatch=int((games.points_check != "OK").sum()))
    return CanonicalBuild(games, events, game_labels, shot_labels,
                          pd.DataFrame(excl, columns=["game_id", "reason"]), diag)


# --------------------------------------------------------------------------- reconciliation
def reconcile_nbastats(games: pd.DataFrame, game_labels: pd.DataFrame, nbastats_csv: Path) -> pd.DataFrame:
    """Compare home team and final score against stats.nba.com v2 PBP (same upstream org: consistency check)."""
    s = pd.read_csv(nbastats_csv, low_memory=False,
                    usecols=["GAME_ID", "EVENTNUM", "HOMEDESCRIPTION", "VISITORDESCRIPTION",
                             "PLAYER1_TEAM_ID", "SCORE", "PERIOD"])
    s["game_id"] = s.GAME_ID.map(lambda g: f"00{int(g)}")
    hd = s[s.HOMEDESCRIPTION.notna() & s.VISITORDESCRIPTION.isna() & s.PLAYER1_TEAM_ID.notna()]
    home = hd.groupby("game_id").PLAYER1_TEAM_ID.agg(lambda x: int(x.mode().iat[0]))
    sc = s[s.SCORE.notna()].copy()
    sc[["away", "home"]] = sc.SCORE.str.split(" - ", expand=True).astype(int)
    last = sc.sort_values(["game_id", "PERIOD", "EVENTNUM"]).groupby("game_id").agg(
        home=("home", "max"), away=("away", "max"))
    m = games[["game_id", "home_team_id"]].merge(game_labels[["game_id", "final_home", "final_away"]], on="game_id")
    m["nbastats_home_team_id"] = m.game_id.map(home)
    m["nbastats_final_home"] = m.game_id.map(last.home)
    m["nbastats_final_away"] = m.game_id.map(last.away)
    def status(r):
        if pd.isna(r.nbastats_home_team_id):
            return "MISSING_IN_NBASTATS"
        issues = []
        if int(r.nbastats_home_team_id) != r.home_team_id: issues.append("HOME_TEAM_MISMATCH")
        if (r.nbastats_final_home, r.nbastats_final_away) != (r.final_home, r.final_away): issues.append("SCORE_MISMATCH")
        return "|".join(issues) or "MATCH"
    m["status"] = m.apply(status, axis=1)
    return m
