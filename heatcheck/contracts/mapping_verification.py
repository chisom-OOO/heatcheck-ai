"""Max's verification of venue mappings against stored rules text (M-002). Pure, no I/O.

Experience proposes a VENUE_MAPPING; Max verifies it here from the bundle's own bytes:
the VENUE_MARKET record, its raw venue payload (bound by ``source_snapshot_ids``) and the
GAME record. A mapping becomes VERIFIED only when every check passes. Nothing is inferred
from titles or similarity; any deviation from the exact rules template leaves it PROPOSED.

Only Polymarket NBA moneyline markets are handled. Kalshi stays PROPOSED: its stored payload
does not state an overtime rule (user instruction, 7 November).

A verification document (heatcheck-mapping-verification/1) is stored by Max outside
Experience's bundle and binds the bundle's ``records_sha256`` and the exact proposed mapping
and market records. ``apply_verifications`` swaps in the VERIFIED record only if those
bindings still hold, so Experience's content-addressed bytes are never edited.
"""

from __future__ import annotations

import copy
import hashlib
import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from heatcheck.contracts.records import parse_utc, record_hash, validate_record

FORMAT = "heatcheck-mapping-verification/1"
VERIFIER = "MAX heatcheck/contracts/mapping_verification.py v1"
ET = ZoneInfo("America/New_York")

# NBA team id -> (nickname as Polymarket labels it, city). Written by Max from NBA team ids;
# deliberately not imported from Experience's adapter so the check is independent.
NBA_TEAMS: dict[str, tuple[str, str]] = {
    "nba-team:1610612737": ("Hawks", "Atlanta"), "nba-team:1610612738": ("Celtics", "Boston"),
    "nba-team:1610612751": ("Nets", "Brooklyn"), "nba-team:1610612766": ("Hornets", "Charlotte"),
    "nba-team:1610612741": ("Bulls", "Chicago"), "nba-team:1610612739": ("Cavaliers", "Cleveland"),
    "nba-team:1610612742": ("Mavericks", "Dallas"), "nba-team:1610612743": ("Nuggets", "Denver"),
    "nba-team:1610612765": ("Pistons", "Detroit"), "nba-team:1610612744": ("Warriors", "Golden State"),
    "nba-team:1610612745": ("Rockets", "Houston"), "nba-team:1610612754": ("Pacers", "Indiana"),
    "nba-team:1610612746": ("Clippers", "LA"), "nba-team:1610612747": ("Lakers", "Los Angeles"),
    "nba-team:1610612763": ("Grizzlies", "Memphis"), "nba-team:1610612748": ("Heat", "Miami"),
    "nba-team:1610612749": ("Bucks", "Milwaukee"), "nba-team:1610612750": ("Timberwolves", "Minnesota"),
    "nba-team:1610612740": ("Pelicans", "New Orleans"), "nba-team:1610612752": ("Knicks", "New York"),
    "nba-team:1610612760": ("Thunder", "Oklahoma City"), "nba-team:1610612753": ("Magic", "Orlando"),
    "nba-team:1610612755": ("76ers", "Philadelphia"), "nba-team:1610612756": ("Suns", "Phoenix"),
    "nba-team:1610612757": ("Trail Blazers", "Portland"), "nba-team:1610612758": ("Kings", "Sacramento"),
    "nba-team:1610612759": ("Spurs", "San Antonio"), "nba-team:1610612761": ("Raptors", "Toronto"),
    "nba-team:1610612762": ("Jazz", "Utah"), "nba-team:1610612764": ("Wizards", "Washington"),
}

RULES_HEAD = re.compile(
    r'^In the upcoming NBA game between (?P<a>[^\n,]+?) and (?P<b>[^\n,]+?), originally scheduled '
    r'for (?P<when>[^\n()]+?) \(as of creation of the first market related to the event\):\n'
    r'If the (?P=a) win, the market will resolve to "(?P=a)"\.\n'
    r'If the (?P=b) win, the market will resolve to "(?P=b)"\.\n')
OVERTIME = "The result will be determined based on the final score including any overtime periods."
CANCEL = re.compile(r"If the game is canceled, does not start by [^\n.]+?, or is abandoned with no "
                    r"official result by that time, this market will resolve 50-50\.")


class VerificationError(ValueError):
    pass


def et_phrase(tip_utc: str) -> str:
    """'Saturday, November 7, 2026 at 7:30 PM ET' for a UTC tip (DST-aware)."""
    t = parse_utc(tip_utc).astimezone(ET)
    hour = t.hour % 12 or 12
    return f"{t:%A}, {t:%B} {t.day}, {t.year} at {hour}:{t:%M} {'AM' if t.hour < 12 else 'PM'} ET"


def _json_list(v: Any) -> list:
    import json
    return json.loads(v) if isinstance(v, str) else list(v)


def verify_polymarket_mapping(mapping: dict, market: dict, game: dict, payload: dict,
                              payload_sha256: str) -> list[dict]:
    """Run every check. Returns [{check, status PASS|FAIL, detail}]. Never raises on a mismatch."""
    for r in (mapping, market, game):
        validate_record(r)
    mb, vb, gb = mapping["body"], market["body"], game["body"]
    out: list[dict] = []

    def check(name: str, ok: bool, detail: str) -> None:
        out.append({"check": name, "status": "PASS" if ok else "FAIL", "detail": detail})

    check("venue", vb["venue"] == "POLYMARKET" and market["record_id"] == mb["venue_market_record_id"],
          f"market {market['record_id']} venue {vb['venue']}")
    check("payload_bound", payload_sha256 in vb["source_snapshot_ids"],
          f"payload sha256 {payload_sha256[:16]} is a source snapshot of the market record")
    rules = payload.get("description")
    if not isinstance(rules, str):
        check("rules_text_hash", False, "payload has no rules text")
        return out
    rh = hashlib.sha256(rules.encode("utf-8")).hexdigest()
    check("rules_text_hash", rh == vb["rules_text_sha256"], f"sha256(description) {rh[:16]} vs record "
          f"{vb['rules_text_sha256'][:16]}")
    check("market_id", str(payload.get("id")) == vb["market_id"], f"payload id {payload.get('id')}")
    check("moneyline", payload.get("sportsMarketType") == "moneyline",
          f"sportsMarketType {payload.get('sportsMarketType')!r}")

    home, away = gb["home_team_id"], gb["away_team_id"]
    names = {t: NBA_TEAMS.get(t, (None, None))[0] for t in (home, away)}
    check("known_teams", None not in names.values(), f"home {names[home]}, away {names[away]}")
    check("game_id", mb["game_id"] == gb["game_id"], f"mapping {mb['game_id']} game {gb['game_id']}")

    m = RULES_HEAD.match(rules)
    check("rules_template", m is not None, "rules text follows the exact winner template" if m else
          "rules text does not follow the exact winner template")
    if m:
        check("rules_teams", {m["a"], m["b"]} == set(names.values()),
              f"rules name {m['a']!r} and {m['b']!r}; game teams {sorted(names.values())}")
        tip = gb["scheduled_tip_utc"]
        want = et_phrase(tip) if tip else None
        check("rules_scheduled_time", m["when"] == want, f"rules {m['when']!r} vs tip {tip} = {want!r}")
    gst = payload.get("gameStartTime")
    try:
        gst_ok = gst is not None and gb["scheduled_tip_utc"] is not None and \
            datetime.fromisoformat(gst.replace(" ", "T").replace("+00", "+00:00")) == parse_utc(gb["scheduled_tip_utc"])
    except ValueError:
        gst_ok = False
    check("game_start_time", gst_ok, f"payload gameStartTime {gst!r} vs scheduled tip {gb['scheduled_tip_utc']}")

    overtime_ok = rules.count(OVERTIME) == 1
    check("overtime_rule", overtime_ok and mb["overtime_convention"] == "INCLUDES_OVERTIME",
          f"rules state overtime counts: {overtime_ok}; mapping says {mb['overtime_convention']}")
    cm = CANCEL.search(rules)
    check("cancel_rule", cm is not None and mb["cancel_postpone_convention"] == f"RULES TEXT: {cm.group(0)}",
          "cancellation/postponement sentence copied exactly" if cm else "no cancellation rule found")

    try:
        outcomes, tokens = _json_list(payload.get("outcomes")), _json_list(payload.get("clobTokenIds"))
    except ValueError:
        outcomes, tokens = [], []
    team_name = names.get(mb["team_id"])
    ok = (len(outcomes) == 2 == len(tokens) and set(outcomes) == set(names.values())
          and team_name in outcomes and tokens[outcomes.index(team_name)] == mb["contract_id"])
    check("contract_is_team", ok and mb["outcome_direction"] == "TEAM_WINS"
          and mb["team_id"] in (home, away),
          f"contract {mb['contract_id'][:12]}.. is outcome {team_name!r} (TEAM_WINS)")
    record_outcomes = {o["contract_id"]: o["label"] for o in vb["outcomes"]}
    check("record_outcome_label", record_outcomes.get(mb["contract_id"]) == team_name,
          f"market record labels the contract {record_outcomes.get(mb['contract_id'])!r}")
    check("active", payload.get("active") is True and payload.get("closed") is False,
          f"active {payload.get('active')}, closed {payload.get('closed')}")
    return out


def verification_doc(mapping: dict, market: dict, game: dict, payload: dict, payload_sha256: str,
                     bundle_records_sha256: str, verified_utc: str) -> dict:
    checks = verify_polymarket_mapping(mapping, market, game, payload, payload_sha256)
    passed = all(c["status"] == "PASS" for c in checks)
    doc: dict[str, Any] = {
        "format": FORMAT, "verifier": VERIFIER, "verified_utc": verified_utc,
        "bundle_records_sha256": bundle_records_sha256,
        "proposed_mapping_record_sha256": record_hash(mapping),
        "venue_market_record_sha256": record_hash(market),
        "game_record_sha256": record_hash(game),
        "rules_text_sha256": market["body"]["rules_text_sha256"], "payload_sha256": payload_sha256,
        "outcome": "VERIFIED" if passed else "LEFT_PROPOSED", "checks": checks, "record": None,
    }
    if passed:
        rec = copy.deepcopy(mapping)
        rec["body"]["status"] = "VERIFIED"
        rec["body"]["reason"] = (f"Max verified {len(checks)}/{len(checks)} checks against stored rules text "
                                 f"sha256 {market['body']['rules_text_sha256']} ({FORMAT}).")
        rec["body"]["mapping_provenance"] = (f"{mapping['body']['mapping_provenance']}; verified by {VERIFIER} "
                                             f"at {verified_utc}")
        validate_record(rec)
        doc["record"] = rec
    return doc


def apply_verifications(records: list[dict], bundle_records_sha256: str, docs: list[dict]) -> tuple[list[dict], list[str]]:
    """Swap each proposed mapping for its VERIFIED record when the verification still binds.
    Returns (records, notes). Unbound or non-matching documents are ignored with a note."""
    out = list(records)
    notes = []
    by_id = {r["record_id"]: i for i, r in enumerate(out)}
    for d in docs:
        if d.get("format") != FORMAT or d.get("outcome") != "VERIFIED" or not d.get("record"):
            continue
        if d["bundle_records_sha256"] != bundle_records_sha256:
            continue  # belongs to another bundle
        rec = d["record"]
        i = by_id.get(rec["record_id"])
        if i is None or out[i]["record_type"] != "VENUE_MAPPING":
            notes.append(f"{rec['record_id']}: proposed mapping not in bundle")
            continue
        market = next((r for r in out if r["record_id"] == rec["body"]["venue_market_record_id"]), None)
        if (record_hash(out[i]) != d["proposed_mapping_record_sha256"] or market is None
                or record_hash(market) != d["venue_market_record_sha256"]):
            notes.append(f"{rec['record_id']}: bundle records changed since verification")
            continue
        same = {k: v for k, v in rec["body"].items() if k not in ("status", "reason", "mapping_provenance")}
        orig = {k: v for k, v in out[i]["body"].items() if k not in ("status", "reason", "mapping_provenance")}
        if same != orig or rec["record_type"] != "VENUE_MAPPING" or rec["body"]["status"] != "VERIFIED":
            notes.append(f"{rec['record_id']}: verified record differs from the proposal")
            continue
        validate_record(rec)
        out[i] = rec
    return out, notes


__all__ = ["FORMAT", "NBA_TEAMS", "apply_verifications", "et_phrase", "verification_doc",
           "verify_polymarket_mapping"]
