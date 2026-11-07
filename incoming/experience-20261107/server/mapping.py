"""EventMapping proposals between a canonical NBA game and a venue market spec.

The proposer only PROPOSES. A mapping becomes APPROVED only through `approve()` with a named
human reviewer (Max owns the trusted workflow; this module enforces the minimum: no automated
or model reviewer can approve, unknowns block, and any rules change invalidates approval).
"""
import hashlib
import json
import re
from datetime import datetime, timezone

NBA_TEAMS = {
    "ATL": ("Atlanta", "Hawks"), "BOS": ("Boston", "Celtics"), "BKN": ("Brooklyn", "Nets"),
    "CHA": ("Charlotte", "Hornets"), "CHI": ("Chicago", "Bulls"), "CLE": ("Cleveland", "Cavaliers"),
    "DAL": ("Dallas", "Mavericks"), "DEN": ("Denver", "Nuggets"), "DET": ("Detroit", "Pistons"),
    "GSW": ("Golden State", "Warriors"), "HOU": ("Houston", "Rockets"), "IND": ("Indiana", "Pacers"),
    "LAC": ("LA", "Clippers"), "LAL": ("Los Angeles", "Lakers"), "MEM": ("Memphis", "Grizzlies"),
    "MIA": ("Miami", "Heat"), "MIL": ("Milwaukee", "Bucks"), "MIN": ("Minnesota", "Timberwolves"),
    "NOP": ("New Orleans", "Pelicans"), "NYK": ("New York", "Knicks"), "OKC": ("Oklahoma City", "Thunder"),
    "ORL": ("Orlando", "Magic"), "PHI": ("Philadelphia", "76ers"), "PHX": ("Phoenix", "Suns"),
    "POR": ("Portland", "Trail Blazers"), "SAC": ("Sacramento", "Kings"), "SAS": ("San Antonio", "Spurs"),
    "TOR": ("Toronto", "Raptors"), "UTA": ("Utah", "Jazz"), "WAS": ("Washington", "Wizards"),
}
AUTOMATED_REVIEWERS = {"", "llm", "model", "auto", "automatic", "system", "heatcheck", "discoverer",
                       "challenger", "referee", "assistant", "ai"}


def _sha(o):
    return hashlib.sha256(json.dumps(o, sort_keys=True, default=str).encode()).hexdigest()


def teams_in(text):
    """Return team codes whose nickname appears as a whole word. Nicknames are unique in the NBA;
    city names are not (LA / Los Angeles), so cities alone never identify a team."""
    found = []
    low = (text or "").lower()
    for code, (_, nick) in NBA_TEAMS.items():
        if re.search(r"\b" + re.escape(nick.lower()) + r"\b", low):
            found.append(code)
    return found


def _dt(s):
    if not s:
        return None
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00").replace(" ", "T"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _overtime_convention(rules):
    r = (rules or "").lower()
    if re.search(r"regulation (time )?only|excluding overtime|not including overtime|at the end of regulation", r):
        return "REGULATION_ONLY"
    if re.search(r"including (any )?overtime|includes overtime|overtime (periods )?(count|included|will count)", r):
        return "INCLUDES_OVERTIME"
    return "UNKNOWN"


def _cancel_convention(rules):
    r = (rules or "").lower()
    if re.search(r"postpone|cancel|reschedul", r):
        m = re.search(r"[^.]*(postpone|cancel|reschedul)[^.]*\.", r)
        return {"stated": True, "excerpt": m.group(0).strip() if m else None}
    return {"stated": False, "excerpt": None}


def propose(game, target_team, spec, max_tip_gap_hours=12):
    """game: {game_id, home_team, away_team, scheduled_tip_utc}; target_team: code; spec: MarketSpec."""
    reasons = []
    rules = spec.get("rules_text", "")
    title_blob = " ".join([spec.get("title", ""), spec.get("yes_sub_title") or "",
                           " ".join(o["label"] for o in spec.get("outcome_contract_ids", []))])
    teams = set(teams_in(title_blob))
    want = {game["home_team"], game["away_team"]}
    status = "PROPOSED"

    if target_team not in want:
        return _result(game, spec, target_team, None, "UNSUPPORTED_TARGET", ["target team is not in this game"])
    if not want.issubset(teams):
        missing = sorted(want - teams)
        reasons.append(f"market text does not name both teams; missing {missing}")
        status = "NO_MATCH"
    extra = teams - want
    if extra:
        reasons.append(f"market mentions other teams {sorted(extra)}")
        status = "NO_MATCH"

    tip = _dt(game.get("scheduled_tip_utc"))
    mstart = _dt((spec.get("nba_event_identity") or {}).get("game_start_utc"))
    if mstart is None:
        reasons.append("market has no game start time; date cannot be verified")
        status = "NO_MATCH" if status == "NO_MATCH" else "RULES_UNVERIFIED"
    elif tip and abs((mstart - tip).total_seconds()) > max_tip_gap_hours * 3600:
        reasons.append(f"market start {mstart.isoformat()} differs from scheduled tip {tip.isoformat()} "
                       f"by more than {max_tip_gap_hours}h (same teams, different game?)")
        status = "NO_MATCH"

    # outcome direction: which contract means "target team wins"
    nick = NBA_TEAMS[target_team][1].lower()
    contract = None
    if spec["venue"] == "polymarket":
        hits = [o for o in spec["outcome_contract_ids"] if nick in o["label"].lower()]
        if len(hits) == 1:
            contract = hits[0]["contract_id"]
        else:
            reasons.append("no single outcome label names the target team")
            status = "NO_MATCH" if status != "NO_MATCH" else status
    elif spec["venue"] == "kalshi":
        yes = (spec.get("yes_sub_title") or "").lower()
        if nick in yes and not any(NBA_TEAMS[t][1].lower() in yes for t in want - {target_team}):
            contract = f"{spec['market_id']}:yes"
        elif yes:
            reasons.append(f"YES means {spec.get('yes_sub_title')!r}, not the target team; a reversed-outcome comparison is refused")
            status = "NO_MATCH"
        else:
            reasons.append("YES meaning is not stated in the market metadata")
            status = "RULES_UNVERIFIED" if status == "PROPOSED" else status

    ot = _overtime_convention(rules)
    if ot == "REGULATION_ONLY":
        reasons.append("contract resolves on regulation only; the forecast target is the game result including overtime")
        status = "OVERTIME_MISMATCH" if status == "PROPOSED" else status
    elif ot == "UNKNOWN":
        reasons.append("rules do not state whether overtime counts")
        status = "RULES_UNVERIFIED" if status == "PROPOSED" else status
    cancel = _cancel_convention(rules)
    if not cancel["stated"]:
        reasons.append("rules do not state postponement/cancellation handling")
        status = "RULES_UNVERIFIED" if status == "PROPOSED" else status
    if spec.get("market_status") == "PAUSED_MARKET":
        reasons.append("market is not open")
        status = "PAUSED_MARKET" if status == "PROPOSED" else status

    return _result(game, spec, target_team, contract, status, reasons, ot, cancel)


def _result(game, spec, target_team, contract, status, reasons, ot="UNKNOWN", cancel=None):
    m = {
        "forecast_game_id": game["game_id"],
        "market_spec_hash": _sha({k: spec.get(k) for k in ("venue", "market_id", "outcome_contract_ids", "rules_hash", "title")}),
        "venue": spec.get("venue"), "market_id": spec.get("market_id"),
        "participants_date": {"home": game["home_team"], "away": game["away_team"],
                              "scheduled_tip_utc": game.get("scheduled_tip_utc"),
                              "market_game_start": (spec.get("nba_event_identity") or {}).get("game_start_utc")},
        "regulation_overtime_convention": ot,
        "cancel_postpone_convention": cancel or {"stated": False, "excerpt": None},
        "outcome_direction": {"target_team": target_team, "contract_id": contract},
        "rules_hash": spec.get("rules_hash"),
        "trusted_reviewer": None,
        "status": status,
        "reason": "; ".join(reasons) if reasons else "all automated checks matched; awaiting human review",
        "proposed_by": "rule-based matcher (cannot approve)",
    }
    m["mapping_id"] = "map_" + _sha(m)[:16]
    return m


def approve(mapping, reviewer, current_rules_hash):
    reviewer = (reviewer or "").strip()
    if reviewer.lower() in AUTOMATED_REVIEWERS or len(reviewer) < 2:
        raise PermissionError("a named human reviewer is required; automated or model approval is not accepted")
    if mapping["status"] != "PROPOSED":
        raise PermissionError(f"mapping status {mapping['status']} cannot be approved: {mapping['reason']}")
    if mapping["rules_hash"] != current_rules_hash:
        raise PermissionError("market rules changed since the mapping was proposed; re-propose")
    out = dict(mapping)
    out["status"] = "APPROVED"
    out["trusted_reviewer"] = {"name": reviewer, "at": datetime.now(timezone.utc).isoformat(),
                               "attested": "checked teams, date, outcome direction, overtime and postponement rules"}
    return out
