"""Semantic checks a reviewer runs on candidate bundles, beyond what the validator proves.

Each function returns a list of human-readable problems; an empty list means no problem
found by that check. The self-tests in test_rv_checks_selftest.py prove each check fires.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any

from heatcheck.contracts.records import parse_utc, record_hash
from tests.review.review_support import (
    MIN_FEATURES,
    latest_revisions,
    of_type,
    reference_features,
    resolve_shot,
    walk_values,
)

LEAKY_NAME = re.compile(r"(made|make_flag|result|outcome|points_scored|final|label|assist)")
REG_SEASON_2023_24 = re.compile(r"^nba:00223\d{5}$")
CLOCK_TOLERANCE_S = 2


# =========================================================================== Research (R-001)


def research_problems(manifest: dict, records: list[dict], *, real: bool) -> list[str]:
    p: list[str] = []
    games = {g["body"]["game_id"]: g["body"] for g in of_type(records, "GAME")}
    events = of_type(records, "EVENT")
    by_hash = {record_hash(r): r for r in records}

    if real:
        if manifest["data_modes"] != ["REAL_NBA_RETROSPECTIVE"]:
            p.append(f"data_modes {manifest['data_modes']} != ['REAL_NBA_RETROSPECTIVE']")
        for gid, g in games.items():
            if not REG_SEASON_2023_24.match(gid):
                p.append(f"{gid} is not a 2023-24 regular-season NBA game id (nba:00223xxxxx)")
            if g["season"] != "2023-24" or g["competition"] != "REGULAR_SEASON":
                p.append(f"{gid} season/competition {g['season']}/{g['competition']}")
    if len(games) != 1:
        p.append(f"expected exactly one GAME, found {len(games)}")

    # ---- games and teams
    for e in events:
        b = e["body"]
        g = games.get(b["game_id"])
        if g and b["team_id"] is not None and b["team_id"] not in (
                g["home_team_id"], g["away_team_id"]):
            p.append(f"EVENT {e['record_id']} team {b['team_id']} not in game {b['game_id']}")
    seqs = Counter((e["body"]["game_id"], e["body"]["sequence"]) for e in latest_revisions(events))
    p += [f"duplicate sequence {k}" for k, n in seqs.items() if n > 1]
    revs = Counter((e["body"]["game_id"], e["body"]["provider_event_id"], e["body"]["revision"])
                   for e in events)
    p += [f"duplicate event revision {k}" for k, n in revs.items() if n > 1]

    # ---- clocks / overtime
    for e in events:
        b = e["body"]
        c = b["clock_seconds_remaining"]
        if c is not None and b["period"] > 4 and Decimal(c) > 300:
            p.append(f"EVENT {e['record_id']} overtime period {b['period']} clock {c} > 300")
    per_period: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for e in latest_revisions(events):
        per_period[(e["body"]["game_id"], e["body"]["period"])].append(e["body"])
    for (gid, period), evs in per_period.items():
        clocks = [Decimal(b["clock_seconds_remaining"]) for b in evs
                  if b["clock_seconds_remaining"] is not None]
        if any(a < b for a, b in zip(clocks, clocks[1:], strict=False)):
            p.append(f"{gid} period {period}: clock increases along provider sequence")

    # ---- labels: reversed outcomes
    shots = {(e["body"]["game_id"], e["body"]["provider_event_id"]): e["body"]
             for e in latest_revisions(events) if e["body"]["action"] == "SHOT"}
    for gid, g in games.items():
        pts = {g["home_team_id"]: 0, g["away_team_id"]: 0}
        for (sgid, _), s in shots.items():
            if sgid == gid and s["shot"]["made"] and s["team_id"] in pts:
                pts[s["team_id"]] += s["shot"]["points_if_made"]
        finals = [lab["body"] for lab in of_type(records, "RESTRICTED_LABEL")
                  if lab["body"]["game_id"] == gid and lab["body"]["label_kind"] == "GAME_FINAL_SCORE"]
        if len(finals) != 1:
            p.append(f"{gid}: expected one GAME_FINAL_SCORE label, found {len(finals)}")
        for f in finals:
            v = f["value"]
            want = {"home_points": pts[g["home_team_id"]], "away_points": pts[g["away_team_id"]]}
            if v != want:
                swapped = v == {"home_points": want["away_points"], "away_points": want["home_points"]}
                p.append(f"{gid}: final score label {v} != event totals {want}"
                         + (" (HOME/AWAY REVERSED)" if swapped else ""))
            if v["home_points"] == v["away_points"] and g["status"] == "FINAL":
                p.append(f"{gid}: FINAL game with tied score {v}")
            if real and f["reconciliation"] != "RECONCILED":
                p.append(f"{gid}: GAME_FINAL_SCORE reconciliation is {f['reconciliation']}"
                         " (A3 not met)")
    made_labels: dict[str, list[bool]] = defaultdict(list)
    for lab in of_type(records, "RESTRICTED_LABEL"):
        b = lab["body"]
        if b["label_kind"] != "SHOT_MADE":
            continue
        hit = [s for (gid, peid), s in shots.items()
               if gid == b["game_id"] and b["target_id"].endswith(":" + peid)]
        if len(hit) != 1:
            p.append(f"SHOT_MADE label {b['target_id']} resolves to {len(hit)} shots")
            continue
        made_labels[hit[0]["provider_event_id"]].append(b["value"]["made"])
        if b["value"]["made"] != hit[0]["shot"]["made"]:
            p.append(f"SHOT_MADE label {b['target_id']} = {b['value']['made']} but EVENT says"
                     f" {hit[0]['shot']['made']} (REVERSED)")
    missing_labels = [peid for (_, peid) in shots if peid not in made_labels]
    if missing_labels:
        p.append(f"{len(missing_labels)} shots have no SHOT_MADE label, e.g. {missing_labels[:3]}")

    # ---- pre-shot leakage on the committed rows
    excluded = {x["id"] for x in manifest["exclusions"]}
    rows = [r for r in of_type(records, "FEATURE_ROW") if r["body"]["target_kind"] == "PRE_SHOT_MAKE"]
    covered: Counter[str] = Counter()
    for gid, g in games.items():
        ref = reference_features(
            [e for e in events if e["body"]["game_id"] == gid], g["home_team_id"], g["away_team_id"])
        for r in rows:
            b = r["body"]
            if b["game_id"] != gid:
                continue
            try:
                s = resolve_shot(r, events)
            except AssertionError as exc:
                p.append(str(exc))
                continue
            covered[s["provider_event_id"]] += 1
            seq = s["sequence"]
            cut = b["cutoff"]
            if cut["kind"] == "GAME_SEQUENCE" and cut["before_sequence"] != seq:
                p.append(f"{b['target_id']}: cutoff before_sequence {cut['before_sequence']}"
                         f" != shot sequence {seq}" + (" (LEAK)" if cut["before_sequence"] > seq
                                                       else ""))
            if b["max_input_sequence"] is not None and b["max_input_sequence"] >= seq:
                p.append(f"{b['target_id']}: max_input_sequence {b['max_input_sequence']} >= {seq}")
            for h in b["source_record_hashes"]:
                src = by_hash.get(h)
                if src is None:
                    p.append(f"{b['target_id']}: input hash {h[:12]} not in bundle")
                elif src["record_type"] in ("RESTRICTED_LABEL",):
                    p.append(f"{b['target_id']}: input is a RESTRICTED_LABEL (LEAK)")
                elif src["record_type"] == "EVENT" and src["body"]["sequence"] >= seq:
                    p.append(f"{b['target_id']}: input EVENT sequence "
                             f"{src['body']['sequence']} >= shot {seq} (LEAK)")
            for name in b["features"]:
                if LEAKY_NAME.search(name) and name not in MIN_FEATURES and "prior" not in name:
                    p.append(f"{b['target_id']}: feature name {name!r} suggests outcome data")
            for name in MIN_FEATURES:
                fv = b["features"].get(name)
                if fv is None:
                    p.append(f"{b['target_id']}: minimum feature {name} missing")
                    continue
                want = ref[s["provider_event_id"]][name]
                if fv["value"] is not None and want is not None and float(fv["value"]) != float(want):
                    p.append(f"{b['target_id']}: {name}={fv['value']} reviewer recomputed {want}")
    for (_, peid) in shots:
        if covered[peid] == 0 and not any(peid in x for x in excluded):
            p.append(f"shot {peid} has no PRE_SHOT_MAKE row and no manifest exclusion")
        if covered[peid] > 1:
            p.append(f"shot {peid} has {covered[peid]} PRE_SHOT_MAKE rows")
    return p


# =========================================================================== Experience (E-001)


def _dec(x: Any) -> Decimal | None:
    try:
        return Decimal(str(x)) if not isinstance(x, bool) else None
    except Exception:
        return None


def experience_problems(directory: Path, manifest: dict, records: list[dict], *,
                        stale_s: int) -> list[str]:
    p: list[str] = []
    snaps = {r["record_id"]: r["body"] for r in of_type(records, "RAW_SNAPSHOT")}
    markets = {r["record_id"]: r["body"] for r in of_type(records, "VENUE_MARKET")}
    mappings = {r["body"]["mapping_id"]: r["body"] for r in of_type(records, "VENUE_MAPPING")}
    games = {r["body"]["game_id"]: r for r in of_type(records, "GAME")}
    quotes = of_type(records, "QUOTE")
    created = parse_utc(manifest["created_utc"]) if _is_utc(manifest["created_utc"]) else None
    if created is None:
        p.append(f"manifest created_utc {manifest['created_utc']!r} is not a UTC timestamp")
    if manifest["created_by_role"] != "EXPERIENCE":
        p.append(f"created_by_role {manifest['created_by_role']} != EXPERIENCE")
    if not quotes:
        p.append("no QUOTE records")

    modes = set(manifest["data_modes"])
    if "RECORDED_MARKET" in modes and any(gid.startswith("syn") for gid in games):
        p.append("RECORDED_MARKET bundle uses synthetic game ids")
    if modes == {"SYNTHETIC"} and "invent" not in manifest["notes"].lower():
        p.append("SYNTHETIC bundle notes do not say the data is invented")

    # ---- mappings: reversed outcomes, teams, overtime
    per_market_team: Counter[tuple[str, str]] = Counter()
    for m in mappings.values():
        market = markets.get(m["venue_market_record_id"])
        g = games.get(m["game_id"])
        per_market_team[(m["venue_market_record_id"], m["team_id"])] += 1
        if m["status"] != "PROPOSED":
            p.append(f"{m['mapping_id']}: status {m['status']}; E-001 requires PROPOSED")
        if market is None or g is None:
            continue
        label = next((o["label"] for o in market["outcomes"]
                      if o["contract_id"] == m["contract_id"]), "")
        if label.strip().upper() in {"NO", "AWAY", "HOME"}:
            p.append(f"{m['mapping_id']}: outcome label {label!r} does not name a team; "
                     "direction needs manual confirmation against the rules text")
        if m["overtime_convention"] != "UNKNOWN":
            if market["rules_text_sha256"] is None:
                p.append(f"{m['mapping_id']}: overtime {m['overtime_convention']} claimed "
                         "without a rules_text_sha256")
            text = " ".join(str(v) for s in market["source_snapshot_ids"]
                            for _, v in walk_values(_raw(directory, snaps.get(s)))).lower()
            if text and "overtime" not in text and "ot" not in text.split():
                p.append(f"{m['mapping_id']}: overtime {m['overtime_convention']} but the raw "
                         "metadata never mentions overtime")
        if m["overtime_convention"] == "REGULATION_ONLY":
            p.append(f"{m['mapping_id']}: REGULATION_ONLY contract is not comparable with a "
                     "full-game TEAM_WINS forecast")
    p += [f"market {k[0]} has {n} contracts mapped to team {k[1]} TEAM_WINS (REVERSED?)"
          for k, n in per_market_team.items() if n > 1]

    # ---- quotes: units, ticks, timestamps, staleness, raw trace
    for q in quotes:
        b = q["body"]
        rid = q["record_id"]
        m = mappings.get(b["mapping_id"])
        market = markets.get(m["venue_market_record_id"]) if m else None
        tick = Decimal(market["tick_size"]) if market and market["tick_size"] else None
        fetch, recv = parse_utc(b["fetch_start_utc"]), parse_utc(b["received_utc"])
        if (recv - fetch).total_seconds() > stale_s:
            p.append(f"{rid}: fetch took {(recv - fetch).total_seconds():.0f}s > {stale_s}s")
        if b["provider_time_utc"] is not None:
            prov = parse_utc(b["provider_time_utc"])
            if (prov - recv).total_seconds() > CLOCK_TOLERANCE_S:
                p.append(f"{rid}: provider_time {b['provider_time_utc']} after received "
                         f"{b['received_utc']} (timezone/unit error?)")
            age = (recv - prov).total_seconds()
            if b["status"] == "OK" and age > stale_s:
                p.append(f"{rid}: status OK but book is {age:.0f}s old > {stale_s}s (STALE)")
        elif b["status"] == "OK":
            p.append(f"{rid}: status OK with no provider_time_utc; freshness unprovable")
        if created is not None and created < recv:
            p.append(f"{rid}: received {b['received_utc']} after manifest created_utc")
        snap = snaps.get(b["raw_snapshot_id"])
        if snap is not None:
            ret = parse_utc(snap["retrieved_utc"])
            if not (fetch.timestamp() - CLOCK_TOLERANCE_S <= ret.timestamp()
                    <= recv.timestamp() + CLOCK_TOLERANCE_S):
                p.append(f"{rid}: raw snapshot retrieved {snap['retrieved_utc']} outside fetch "
                         f"window {b['fetch_start_utc']}..{b['received_utc']}")
        g = games.get(m["game_id"]) if m else None
        if g is not None and b["status"] == "OK":
            tip = parse_utc(g["body"]["scheduled_tip_utc"])
            if recv >= tip:
                p.append(f"{rid}: OK quote received at/after scheduled tip "
                         f"{g['body']['scheduled_tip_utc']}; not a pre-tip quote")
            if g["body"]["status"] in ("POSTPONED", "CANCELLED", "FINAL"):
                p.append(f"{rid}: OK quote for game with status {g['body']['status']}")
        raw_values = walk_values(_raw(directory, snap)) if snap else []
        for lv in b["levels"]:
            price = Decimal(lv["price"])
            if lv["derivation"] != "DIRECT":
                p.append(f"{rid}: level derivation {lv['derivation']}; E-001 stores DIRECT only")
            if Decimal(lv["size"]) <= 0:
                p.append(f"{rid}: level size {lv['size']} is not positive")
            if tick is not None and price % tick != 0:
                p.append(f"{rid}: price {lv['price']} off tick grid {tick}")
            if snap is not None and snap["bundle_path"] is not None:
                direct = any(_dec(v) == price for _, v in raw_values)
                cents = any(_dec(v) == price * 100 and "cent" in k.lower() for k, v in raw_values)
                if not (direct or cents):
                    p.append(f"{rid}: price {lv['price']} not traceable to raw payload")
                if direct and any(_dec(v) == price * 100 for _, v in raw_values) and not cents:
                    pass  # coincidence is possible; not reported
            if lv["price"] in ("0", "0.0") or price == 0:
                p.append(f"{rid}: zero price level (empty book must be status EMPTY)")
        if b["status"] == "EMPTY" and b["levels"]:
            p.append(f"{rid}: EMPTY quote carries levels")
    return p


def _is_utc(value: Any) -> bool:
    try:
        parse_utc(value)
        return isinstance(value, str) and value.endswith("Z")
    except Exception:
        return False


def _raw(directory: Path, snap: dict | None) -> Any:
    import json

    if not snap or snap["bundle_path"] is None:
        return None
    try:
        return json.loads((directory / snap["bundle_path"]).read_bytes())
    except (OSError, ValueError):
        return None
