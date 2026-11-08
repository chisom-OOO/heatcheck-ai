"""MARKET_COMPARISON investigation: read-only and descriptive (heatcheck-market-investigation/1).

One game card = one Research forecast row (heatcheck-live-forecast/1) + one Experience venue
mapping and its quotes (heatcheck-records/1) + the user's message. Steps:

1. Heater explains the flag. He may cite only the forecast's ``inputs_used``; any other factor
   (rest, injuries, lineups, ...) must sit in a sentence that is a question. ``heater_guard``
   enforces this along with the number guard and a no-betting-language rule. A rejected or
   unavailable LLM falls back to a fixed template.
2. Challenger checks are deterministic code (``challenger_checks``).
3. Ref verdict is a deterministic template: "Worth investigating · Edge unverified" when the card
   is matched and fresh, "Can't compare" otherwise. It never says "bet" or "edge found".
4. ``ledger_identity`` binds forecast, quote, checks and verdict with timestamps, so the game can
   be scored after it ends.
5. A hypothetical ("what if X is out?") gets a fixed answer: the model cannot quantify lineup
   changes, plus the data that would be needed.

Everything here is pure: no HTTP, provider, file or database side effects. The caller passes
records, the clock value and an optional ``heater_llm`` callable.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

from heatcheck.agents.dialogue import betting_words, number_violations, take_mentions_ref
from heatcheck.contracts.eligibility import LIVE_MAX_AGE, QuoteSelection
from heatcheck.contracts.live_forecast import LiveForecast
from heatcheck.contracts.records import PROTOCOL_VERSION, parse_utc, validate_record, validate_utc

FORMAT = "heatcheck-market-investigation/1"
LANE = "MARKET_INVESTIGATION"
CHANNEL = "MARKET_COMPARISON"
MODES = ("LIVE", "RECORDED")

VERDICT_WORTH = "Worth investigating · Edge unverified"
VERDICT_CANT = "Can't compare"
REF_IDENTITY = {"kind": "DETERMINISTIC_CODE", "rule": FORMAT, "version": "1"}

# Factors a pre-game NBA forecast could use. MISSING_INPUTS reports those the model lacks.
# Each factor lists the input-name fragments that would cover it.
FACTORS: dict[str, tuple[str, tuple[str, ...]]] = {
    "elo": (r"\belo\b|\bratings?\b|\bteam strength\b", ("elo",)),
    "home_court": (r"\bhome[- ](?:court|advantage|crowd|floor)\b", ("home_court",)),
    "rest": (r"\brest(?:ed|ing|s)?\b|\bback[- ]to[- ]backs?\b|\bb2b\b|\bfatigue\w*|\btired\b|"
             r"\btravel\w*|\bschedule\w*", ("rest", "b2b", "back_to_back")),
    "injuries": (r"\binjur\w*|\bhurt\b|\bquestionable\b|\bruled out\b|\bsit(?:s|ting)? out\b|"
                 r"\bis out\b|\bare out\b|\bhealth\w*", ("injur",)),
    "lineups": (r"\blineups?\b|\bstarters?\b|\bstarting\b|\brotations?\b|\bminutes\b",
                ("lineup",)),
    "recent_form": (r"\bform\b|\bstreak\w*|\bmomentum\b|\bhot\b|\bcold\b|\brecent\w*",
                    ("form", "recent")),
    "matchups": (r"\bmatch-?ups?\b|\bpace\b|\bdefen[cs]\w*|\boffen[cs]\w*", ("matchup", "pace")),
    "market_flow": (r"\bsharps?\b|\bsmart money\b|\bmoney\b|\bbettors?\b|\bline movement\b|"
                    r"\bpublic\b", ()),
}
# Needed for a pre-game forecast but always absent from an Elo-only card. Reported, not guessed.
ALWAYS_CHECK_MISSING = ("lineups", "injuries")

BANNED = re.compile(
    r"\bbet(?:s|ting|tor)?\b|\bwager\w*|\bedge found\b|\bfound (?:an |the )?edge\b|"
    r"\bedge\b(?!\s+(?:is\s+)?unverified)|\bvalue\b|\block\b|\bprofit\w*|\bguarantee\w*|"
    r"\bsure thing\b|\bfree money\b|\bmispric\w*|\bstake\b|\bproves?\b|\bproof\b|\bdefinitely\b|"
    r"\bcertain\w*|\bwill win\b|\bbeats? the market\b|\boutperform\w*", re.IGNORECASE)

HYPOTHETICAL = re.compile(
    r"\bwhat if\b|\bwhat happens if\b|\bif\s+[\w .'-]{1,40}?\s+(?:is|are|was|were)\s+"
    r"(?:out|ruled out|injured|benched|resting|sitting)\b|\bwithout\s+[A-Z][\w'-]+|"
    r"\bsuppose\b|\bimagine\b", re.IGNORECASE)
HYPOTHETICAL_ANSWER = (
    "This model can't quantify lineup changes. It uses only {inputs}, so it has no way to say "
    "how a player being out would move the forecast. To answer that you would need confirmed "
    "pre-tip injury and lineup reports, player-level on/off or plus-minus data for the players "
    "involved, and a lineup-aware model evaluated on past games before it is trusted.")

# Research's calibration report (research/calibration@6cd2431), fixed text; shown when the model
# favours the home team more than the market (home team's forecast above the ask). No model change.
HOME_BIAS_CAVEAT = ("On last season's games, this model overrated home teams by about 7 points "
                    "(62.4% predicted vs 55.5% actual). Part of any home-side gap is the model's own bias.")
HOME_BIAS_HEATER = ("Fair call. And the calibration note says this model has overrated home teams before, "
                    "so part of this gap could be the model's own bias, not the market's.")

SAMPLE_HEATER = (
    "This card uses a SAMPLE forecast: its numbers are made up, so there is nothing real to "
    "explain yet. Once Research's real forecast arrives, I can walk through where it sits against "
    "the market.")

THESIS = re.compile(r"\bback[- ]to[- ]backs?\b|\bb2b\b|\brest(?:ed|ing)?\b|\brest days?\b|"
                    r"\bfatigue\w*|\btired\b|\bsecond night\b", re.IGNORECASE)
THESIS_CLAIM = "GP-REST"

HEATER_REACTION = {
    VERDICT_WORTH: "Fair call. A gap is a question to look into, not a finding.",
    VERDICT_CANT: "Fair enough: no comparison, no take on this game.",
}

HEATER_SYSTEM = (
    "You speak BEFORE the Ref and do not know the verdict: never mention the Ref, a verdict, a "
    "check or whether the comparison is valid. "
    "You are the Heater, a friendly NBA explainer. In two to four short sentences, explain the "
    "flag on this game card: where the model's forecast sits against the market's quoted bid and "
    "ask. Cite only the model inputs listed in inputs_used and the card's own numbers, copied "
    "exactly. Any other factor (rest, back-to-backs, injuries, lineups, form, matchups) must be "
    "asked as a question to investigate, never stated as a reason. Never suggest betting, never "
    "say an edge was found, never say the model beats the market: no evidence shows that.")


class InvestigationInputError(ValueError):
    """The request names a game or mapping the configured sources do not have."""


@dataclass(frozen=True)
class Check:
    check_id: str
    status: str  # PASS | FAIL | INFO
    detail: str

    def as_dict(self) -> dict:
        return {"check_id": self.check_id, "status": self.status, "detail": self.detail}


def _pct(p: Decimal) -> str:
    return f"{(p * 100).quantize(Decimal('0.1'), ROUND_HALF_EVEN)}%"


def _d(x: float | str) -> Decimal:
    return Decimal(repr(x)) if isinstance(x, float) else Decimal(str(x))


# --------------------------------------------------------------------------- Heater guard


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+|\n+", text.strip()) if s.strip()]


def covered_factors(inputs_used: list[str]) -> set[str]:
    out = set()
    for factor, (_pat, frags) in FACTORS.items():
        if any(f in name for name in inputs_used for f in frags):
            out.add(factor)
    return out


def missing_factors(inputs_used: list[str]) -> list[str]:
    return [f for f in FACTORS if f not in covered_factors(inputs_used) and f != "market_flow"]


def heater_guard(text: str, inputs_used: list[str], facts: dict) -> list[str]:
    """Problems with Heater text; empty means it may be shown. Deterministic and pure."""
    problems = [f"number {n} is not on the card" for n in number_violations(text, facts)]
    for m in BANNED.finditer(text):
        problems.append(f"betting or over-claim wording {m.group(0)!r}")
    for w in betting_words(text):
        if not any(repr(w) in p.lower() for p in problems):
            problems.append(f"betting wording {w!r}")
    covered = covered_factors(inputs_used)
    for s in _sentences(text):
        if s.rstrip().endswith("?"):
            continue
        for factor, (pat, _frags) in FACTORS.items():
            if factor in covered:
                continue
            m = re.search(pat, s, re.IGNORECASE)
            if m:
                problems.append(f"{factor} ({m.group(0)!r}) is not a model input; ask it as a question")
    return problems


# --------------------------------------------------------------------------- card resolution


def _by_type(records: list[dict], rtype: str) -> list[dict]:
    return [r for r in records if r["record_type"] == rtype]


def _best(levels: list[dict], side: str) -> Decimal | None:
    prices = [Decimal(lv["price"]) for lv in levels if lv["side"] == side]
    if not prices:
        return None
    return max(prices) if side == "BID" else min(prices)


def challenger_checks(
    lf: LiveForecast,
    game_id: str,
    mapping_id: str,
    market_records: list[dict],
    as_of_utc: str,
    *,
    max_age: timedelta = LIVE_MAX_AGE,
) -> tuple[list[Check], dict]:
    """Deterministic Challenger checks for one card. Returns (checks, resolved card facts)."""
    validate_utc(as_of_utc, "as_of_utc")
    as_of = parse_utc(as_of_utc)
    for r in market_records:
        validate_record(r)
    checks: list[Check] = []
    card: dict[str, Any] = {"game_id": game_id, "mapping_id": mapping_id}

    rows = [g for g in lf.doc["games"] if g["game_id"] == game_id]
    if not rows:
        raise InvestigationInputError(f"{game_id} is not in the live forecast file")
    row = rows[0]
    card["forecast_row"] = row
    tip = parse_utc(row["tip_utc"])

    mappings = [m for m in _by_type(market_records, "VENUE_MAPPING")
                if m["body"]["mapping_id"] == mapping_id]
    if not mappings:
        raise InvestigationInputError(f"mapping {mapping_id} is not in the quote source")
    mapping = mappings[0]
    mb = mapping["body"]
    card["mapping"] = mb

    # 1. Game and team match: forecast row, venue mapping and the quote source's GAME record.
    games = [g for g in _by_type(market_records, "GAME") if g["body"]["game_id"] == game_id]
    gproblems = []
    if mb["game_id"] != game_id:
        gproblems.append(f"mapping is for {mb['game_id']}, not {game_id}")
    if not games:
        gproblems.append(f"quote source has no GAME record for {game_id}")
    else:
        gb = games[0]["body"]
        if (gb["home_team_id"], gb["away_team_id"]) != (row["home_team_id"], row["away_team_id"]):
            gproblems.append("home/away teams differ between forecast and quote source")
        if gb["scheduled_tip_utc"] is None:
            gproblems.append("quote source has no scheduled tip time")
        elif parse_utc(gb["scheduled_tip_utc"]) != tip:
            gproblems.append(f"tip time differs: forecast {row['tip_utc']}, "
                             f"quote source {gb['scheduled_tip_utc']}")
        if gb["status"] in ("POSTPONED", "CANCELLED"):
            gproblems.append(f"game status {gb['status']}")
    checks.append(Check("GAME_MATCH", "FAIL" if gproblems else "PASS",
                        "; ".join(gproblems) or f"{game_id}: same teams and tip time in both sources"))

    # 2. Outcome match: the contract pays on the mapped team winning, and the mapping is verified.
    oproblems = []
    team = mb["team_id"]
    if team not in (row["home_team_id"], row["away_team_id"]):
        oproblems.append(f"mapped team {team} is not playing in {game_id}")
    if mb["outcome_direction"] != "TEAM_WINS":
        oproblems.append(f"outcome direction {mb['outcome_direction']}")
    if mb["status"] != "VERIFIED":
        oproblems.append(f"mapping {mb['status']}: contract rules not verified against the game")
    markets = [v for v in _by_type(market_records, "VENUE_MARKET")
               if v["record_id"] == mb["venue_market_record_id"]]
    if not markets:
        oproblems.append("venue market record missing")
    elif mb["contract_id"] not in {o["contract_id"] for o in markets[0]["body"]["outcomes"]}:
        oproblems.append("mapped contract is not an outcome of the venue market")
    checks.append(Check("OUTCOME_MATCH", "FAIL" if oproblems else "PASS",
                        "; ".join(oproblems) or f"contract pays if {team} wins ({mb['overtime_convention']})"))

    p_home = _d(row["p_home_win"])
    is_home = team == row["home_team_id"]
    p_team = p_home if is_home else Decimal(1) - p_home
    card.update(team_id=team, team_name=row["home_team"] if is_home else row["away_team"],
                p_team_win=p_team)

    # 3. Quote freshness and side. Always evaluated, even when the mapping failed.
    quotes = _by_type(market_records, "QUOTE")
    mapped_quotes = [q for q in quotes if q["body"]["mapping_id"] == mapping_id]
    # Freshness is judged even for an unverified mapping (OUTCOME_MATCH owns the status), so the
    # same selection rule as select_quote_for_cutoff is applied directly, without forging a
    # VERIFIED copy of the mapping.
    sel = latest_quote(mapped_quotes, as_of_utc, max_age)
    quote = next((q for q in mapped_quotes if q["record_id"] == sel.quote_record_id), None)
    card["quote"] = quote
    fproblems = []
    if sel.status != "ELIGIBLE":
        fproblems.append(f"{sel.status}: {sel.reason}")
    if quote is not None and parse_utc(quote["body"]["received_utc"]) >= tip:
        fproblems.append("quote received at or after tip")
    if as_of >= tip:
        fproblems.append("game has tipped off; this is no longer a pre-game comparison")
    age = f"{sel.age_seconds:.0f}s old" if sel.age_seconds is not None else "no quote"
    checks.append(Check("QUOTE_FRESH", "FAIL" if fproblems else "PASS",
                        "; ".join(fproblems) or f"latest quote {age}, limit {int(max_age.total_seconds())}s"))

    bid = ask = None
    if quote is not None:
        bid, ask = _best(quote["body"]["levels"], "BID"), _best(quote["body"]["levels"], "ASK")
    card.update(best_bid=bid, best_ask=ask)
    if quote is None:
        side = Check("QUOTE_SIDE", "FAIL", "no quote to read")
    elif bid is None or ask is None:
        side = Check("QUOTE_SIDE", "FAIL", f"one-sided book (bid {bid}, ask {ask}); "
                     "a midpoint or last trade is never shown as a price you could get")
    else:
        side = Check("QUOTE_SIDE", "PASS", f"YES contract on {team}: best bid {bid}, best ask {ask} "
                     "(probability dollars); not an executable order")
    checks.append(side)

    # 4. Forecast cutoff before tip and not after the comparison time.
    cutoff = parse_utc(lf.doc["data_cutoff_utc"])
    cproblems = []
    if not cutoff < tip:
        cproblems.append("forecast data cutoff is not before tip")
    if cutoff > as_of:
        cproblems.append("forecast data cutoff is later than the comparison time")
    checks.append(Check("FORECAST_CUTOFF", "FAIL" if cproblems else "PASS",
                        "; ".join(cproblems) or f"data cutoff {lf.doc['data_cutoff_utc']} is before tip {row['tip_utc']}"))

    # 5. Inputs the model lacks.
    lacks = missing_factors(lf.doc["inputs_used"])
    lacks = [f for f in ALWAYS_CHECK_MISSING if f in lacks] + [f for f in lacks if f not in ALWAYS_CHECK_MISSING]
    card["missing_inputs"] = lacks
    checks.append(Check("MISSING_INPUTS", "INFO",
                        f"model uses only {', '.join(lf.doc['inputs_used'])}; it does not see "
                        f"{', '.join(lacks)}" if lacks else "no listed factor is missing"))

    # 6. Evidence that this model beats the market. None has been run; say so.
    checks.append(Check("MARKET_SKILL_EVIDENCE", "INFO",
                        "no evaluation shows this model beats the market; none has been run"))
    if lf.is_sample:
        checks.append(Check("FORECAST_SAMPLE", "FAIL",
                            "forecast file is a hand-made SAMPLE; its values are invented"))
    return checks, card


def latest_quote(quotes: list[dict], as_of_utc: str, max_age: timedelta) -> QuoteSelection:
    """select_quote_for_cutoff's rule without the mapping-status gate: the latest quote received
    at or before ``as_of_utc``; non-OK latest is reported, never skipped; older than max_age is STALE."""
    as_of = parse_utc(as_of_utc)
    cands = [(parse_utc(q["body"]["received_utc"]), q["record_id"], q) for q in quotes
             if parse_utc(q["body"]["received_utc"]) <= as_of]
    if not cands:
        return QuoteSelection("NO_QUOTE_BY_CUTOFF", None, "no quote received at or before the comparison time", None)
    received, rid, q = max(cands, key=lambda c: (c[0], c[1]))
    age = (as_of - received).total_seconds()
    if q["body"]["status"] != "OK":
        return QuoteSelection("QUOTE_NOT_OK", rid, f"latest quote status {q['body']['status']}", age)
    if as_of - received > max_age:
        return QuoteSelection("STALE", rid, f"quote age {age}s exceeds {max_age}", age)
    return QuoteSelection("ELIGIBLE", rid, "latest OK quote received by the comparison time", age)


GATING = ("GAME_MATCH", "OUTCOME_MATCH", "QUOTE_FRESH", "QUOTE_SIDE", "FORECAST_CUTOFF", "FORECAST_SAMPLE")


def ref_verdict(checks: list[Check]) -> tuple[str, str]:
    """Deterministic Ref. Returns (verdict, ref_text)."""
    failed = [c for c in checks if c.check_id in GATING and c.status == "FAIL"]
    if failed:
        why = "; ".join(f"{c.check_id}: {c.detail}" for c in failed)
        return VERDICT_CANT, f"{VERDICT_CANT}. {why}."
    return VERDICT_WORTH, (
        f"{VERDICT_WORTH}. The forecast and the quote are for the same game, team and outcome, "
        "and the quote is fresh. No evaluation shows this model beats the market, so a gap "
        "between them is a question to investigate, not a finding.")


def flag_of(card: dict) -> str:
    p, bid, ask = card["p_team_win"], card.get("best_bid"), card.get("best_ask")
    if bid is None or ask is None:
        return "NO_TWO_SIDED_QUOTE"
    if p > ask:
        return "FORECAST_ABOVE_ASK"
    if p < bid:
        return "FORECAST_BELOW_BID"
    return "FORECAST_INSIDE_SPREAD"


def card_facts(card: dict, inputs_used: list[str]) -> dict:
    """Numbers Heater may say, in the exact forms he may say them. No hashes."""
    p = card["p_team_win"]
    facts: dict[str, Any] = {"p_team_win": str(p), "p_team_win_pct": _pct(p),
                             "inputs_used": inputs_used, "team": card["team_name"]}
    for k in ("best_bid", "best_ask"):
        if card.get(k) is not None:
            facts[k] = str(card[k])
            facts[k + "_pct"] = _pct(card[k])
    row = card["forecast_row"]
    facts.update(elo_home=row["elo_home"], elo_away=row["elo_away"])
    return facts


def heater_template(card: dict, flag: str, inputs_used: list[str]) -> str:
    p = _pct(card["p_team_win"])
    team = card["team_name"]
    ins = ", ".join(inputs_used)
    if flag == "NO_TWO_SIDED_QUOTE":
        where = "There is no market quote with both a bid and an ask to set it against."
    else:
        bid, ask = _pct(card["best_bid"]), _pct(card["best_ask"])
        where = {"FORECAST_ABOVE_ASK": f"That is above the market's ask of {ask}.",
                 "FORECAST_BELOW_BID": f"That is below the market's bid of {bid}.",
                 "FORECAST_INSIDE_SPREAD": f"That sits inside the market's spread, bid {bid} to ask {ask}."}[flag]
    return (f"The model has {team} at {p} to win. {where} It only uses {ins}. "
            "Could rest, injuries or lineup news explain the gap? Those are questions to "
            "investigate, because the model can't see them.")


def thesis_summary(message: str, thesis_entry: dict | None) -> dict | None:
    """Research's recorded rest/back-to-back check, when the message raises that thesis."""
    if not THESIS.search(message):
        return None
    if thesis_entry is None:
        return {"claim_id": THESIS_CLAIM, "status": "NOT_AVAILABLE",
                "text": "The rest/back-to-back thesis has a registered test, but no recorded "
                        "result is available here."}
    i = thesis_entry["identity"]
    return {"claim_id": THESIS_CLAIM, "status": "RECORDED", "evidence_id": thesis_entry["evidence_id"],
            "decision": i["decision"], "reason": i["reason"],
            "text": f"Research's recorded test of rest days and back-to-backs ({THESIS_CLAIM}, "
                    f"2023-24 final games) returned {i['decision']}: {i['reason']} It was not run "
                    "on tonight's game, and the forecast here does not use rest."}


# --------------------------------------------------------------------------- Frost on market cards
# Max, 8 Nov 2026: three challenges anchored to the model-bias note, the mapping verification and
# inputs_used. Chips are filled only from this card's checks and Research's fixed calibration note.
# Templates only (no model call), so loading the board stays fast. Same payload shape as dialogue.

FROST_MARKET_REACTION = {
    VERDICT_WORTH: "A gap, Heater. Not an edge. Nobody has shown this model beats the market.",
    VERDICT_CANT: "Nothing to compare, Heater. No price we trust, no take.",
}


# Same words as the page (apps/web/web/market/board-model.js INPUT_WORDS).
INPUT_WORDS = {"elo_rating_home": "Elo rating (home)", "elo_rating_away": "Elo rating (away)",
               "home_court": "home court"}
OVERTIME_WORDS = {"INCLUDES_OVERTIME": "overtime included", "REGULATION_ONLY": "regulation time only"}


def _words(names: list[str], conj: str = "and") -> str:
    w = [INPUT_WORDS.get(n, n.replace("_", " ")) for n in names]
    return w[0] if len(w) == 1 else ", ".join(w[:-1]) + f" {conj} " + w[-1]


def frost_market(checks: list[Check], *, home_bias: bool, team_is_home: bool, team_name: str = "",
                 overtime: str = "", inputs_used: list[str] | None = None,
                 missing: list[str] | None = None) -> list:
    from heatcheck.agents.frost import Challenge
    by = {c.check_id: c for c in checks}
    if home_bias:
        bias = f"Yes, and it applies here. {HOME_BIAS_CAVEAT}"
    elif team_is_home:
        bias = f"{HOME_BIAS_CAVEAT} This card shows no gap to compare, so it changes nothing here."
    else:
        bias = f"{HOME_BIAS_CAVEAT} This card is for the away team, so that home-side bias would lean the other way."
    om = by.get("OUTCOME_MATCH")
    if om is None:
        mapping = "Not checked."
    elif om.status == "PASS":
        ot = OVERTIME_WORDS.get(overtime, overtime.replace("_", " ").lower())
        mapping = (f"Verified: the contract pays if the {team_name} win" + (f", {ot}" if ot else "") +
                   ", and the game, teams and tip time match the forecast.")
    else:
        mapping = f"Not confirmed: {om.detail}."
    mi = by.get("MISSING_INPUTS")
    if mi is None:
        inputs = "Not checked."
    elif missing:
        inputs = f"The model uses only {_words(inputs_used or [])}. It does not see {_words(missing, 'or')}."
    else:
        inputs = f"The model uses {_words(inputs_used or [])}; no listed factor is missing."
    return [
        Challenge("model_bias", "basketball", "Has this model been wrong before in a way that shows up on this card?",
                  bias, "calibration note (Research, research/calibration@6cd2431)"),
        Challenge("mapping_verification", "process",
                  "How do you know that price is for this game, and pays if this team wins?",
                  mapping, "challenger_checks.OUTCOME_MATCH"),
        Challenge("inputs_used", "numbers", "What doesn't the model know about tonight?", inputs,
                  "challenger_checks.MISSING_INPUTS"),
    ]


def investigate(
    lf: LiveForecast,
    forecast_file_sha256: str,
    game_id: str,
    mapping_id: str,
    market_records: list[dict],
    market_records_sha256: str,
    message: str,
    as_of_utc: str,
    *,
    mode: str = "LIVE",
    max_age: timedelta = LIVE_MAX_AGE,
    thesis_entry: dict | None = None,
    heater_llm: Callable[[str, str], str] | None = None,
) -> tuple[dict, dict]:
    """Run one investigation. Returns (response, ledger identity). Pure apart from heater_llm."""
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    checks, card = challenger_checks(lf, game_id, mapping_id, market_records, as_of_utc, max_age=max_age)
    verdict, ref_text = ref_verdict(checks)
    inputs = lf.doc["inputs_used"]
    flag = flag_of(card)
    facts = card_facts(card, inputs)
    thesis = thesis_summary(message, thesis_entry)
    hypothetical = bool(HYPOTHETICAL.search(message))
    # Only where the card shows a valid comparison (every check passed) with the home team's forecast
    # above the ask; a "Can't compare" card shows no gap, so the note would not apply.
    home_bias = (not lf.is_sample and verdict == VERDICT_WORTH and flag == "FORECAST_ABOVE_ASK"
                 and card["team_id"] == card["forecast_row"]["home_team_id"])
    caveats = [HOME_BIAS_CAVEAT] if home_bias else []

    if lf.is_sample:
        # Never voice a SAMPLE value as the model's forecast; no LLM call either.
        heater_text, heater_source = SAMPLE_HEATER, "FIXED_SAMPLE"
    elif hypothetical:
        heater_text, heater_source = HYPOTHETICAL_ANSWER.format(inputs=", ".join(inputs)), "FIXED_HYPOTHETICAL"
    else:
        heater_text, heater_source = heater_template(card, flag, inputs), "TEMPLATE"
        # The model writes Heater's line only for a fan's actual message. Loading the board sends
        # an empty message for every card; calling the model there took ~4 s per card (rehearsal).
        if heater_llm is not None and message.strip():
            ctx = {"fan_message": message, "team": card["team_name"], "flag": flag,
                   "card_numbers": {k: v for k, v in facts.items() if k not in ("team", "inputs_used")},
                   "inputs_used": inputs, "inputs_model_lacks": card["missing_inputs"]}
            try:
                text = heater_llm(HEATER_SYSTEM, json.dumps(ctx)).strip()
            except Exception as e:  # provider failure never invents text
                heater_source = f"TEMPLATE (fallback: {type(e).__name__})"
            else:
                bad = heater_guard(text, inputs, facts) + [f"ref:{w}" for w in take_mentions_ref(text)]
                if bad or not text:
                    heater_source = f"TEMPLATE (guard rejected: {bad[:4] or ['empty']})"
                else:
                    heater_text, heater_source = text, "LLM"
    # Heater's reaction, spoken after the Ref's stamp: the only Heater line that may follow the verdict.
    if lf.is_sample or hypothetical:
        heater_reaction = ""
    elif home_bias:
        heater_reaction = HOME_BIAS_HEATER
    else:
        heater_reaction = HEATER_REACTION.get(verdict, "")
    if heater_reaction and heater_guard(heater_reaction, inputs, facts):
        raise AssertionError(f"Heater reaction fails guard: {heater_guard(heater_reaction, inputs, facts)}")
    template_bad = heater_guard(heater_text, inputs, facts) if heater_source.startswith("TEMPLATE") else []
    if template_bad:  # a template that fails its own guard is a code defect; fail loudly
        raise AssertionError(f"Heater template fails guard: {template_bad}")

    from heatcheck.agents.frost import to_payload
    frost = to_payload(frost_market(checks, home_bias=home_bias,
                                    team_is_home=card["team_id"] == card["forecast_row"]["home_team_id"],
                                    team_name=card["team_name"],
                                    overtime=card["mapping"].get("overtime_convention") or "",
                                    inputs_used=inputs, missing=card.get("missing_inputs") or []))
    frost_reaction = FROST_MARKET_REACTION.get(verdict, "")

    quote = card["quote"]
    row = card["forecast_row"]
    if mode == "RECORDED" and not lf.is_sample:
        # Say on screen that the price is recorded, with its time, not only in the evidence.
        when = (quote["body"]["received_utc"][:19] + "Z") if quote is not None else "no price"
        ref_text = f"{ref_text} RECORDED: price received {when}, not live."
    data_note = ("SAMPLE forecast: values are invented, not a real forecast." if lf.is_sample else
                 "RECORDED game: quote evaluated as of its capture time, not live."
                 if mode == "RECORDED" else "LIVE quote.")
    response = {
        "format": FORMAT, "mode": mode, "as_of_utc": as_of_utc, "data_note": data_note,
        "is_sample": lf.is_sample, "label": lf.doc["label"],
        "game": {"game_id": game_id, "tip_utc": row["tip_utc"], "home_team": row["home_team"],
                 "away_team": row["away_team"]},
        "team": card["team_name"], "flag": flag,
        "forecast": {"p_team_win": str(card["p_team_win"]), "model": lf.doc["model"],
                     "inputs_used": inputs, "data_cutoff_utc": lf.doc["data_cutoff_utc"]},
        "quote": None if quote is None else {
            "record_id": quote["record_id"], "venue": quote["body"]["venue"],
            "best_bid": None if card["best_bid"] is None else str(card["best_bid"]),
            "best_ask": None if card["best_ask"] is None else str(card["best_ask"]),
            "received_utc": quote["body"]["received_utc"], "status": quote["body"]["status"]},
        "heater_text": heater_text, "heater_reaction": heater_reaction, "heater_source": heater_source,
        "hypothetical": hypothetical, "frost": frost, "frost_reaction": frost_reaction,
        "challenger_checks": [c.as_dict() for c in checks], "thesis": thesis,
        "verdict": verdict, "ref_text": ref_text, "caveats": caveats,
    }
    identity = {
        "protocol_version": PROTOCOL_VERSION, "format": FORMAT, "lane": LANE, "channel": CHANNEL,
        "mode": mode, "as_of_utc": as_of_utc,
        "game": {"game_id": game_id, "tip_utc": row["tip_utc"], "home_team_id": row["home_team_id"],
                 "away_team_id": row["away_team_id"]},
        "forecast": {"file_sha256": forecast_file_sha256, "is_sample": lf.is_sample,
                     "model": lf.doc["model"], "data_cutoff_utc": lf.doc["data_cutoff_utc"],
                     "inputs_used": inputs, "team_id": card["team_id"],
                     "p_home_win": str(_d(row["p_home_win"])), "p_team_win": str(card["p_team_win"])},
        "quote": {"market_records_sha256": market_records_sha256, "mapping_id": mapping_id,
                  "mapping_status": card["mapping"]["status"],
                  "record_id": None if quote is None else quote["record_id"],
                  "venue": None if quote is None else quote["body"]["venue"],
                  "contract_id": card["mapping"]["contract_id"],
                  "best_bid": response["quote"] and response["quote"]["best_bid"],
                  "best_ask": response["quote"] and response["quote"]["best_ask"],
                  "received_utc": None if quote is None else quote["body"]["received_utc"],
                  "provider_time_utc": None if quote is None else quote["body"].get("provider_time_utc")},
        "flag": flag, "caveats": caveats, "challenger_checks": response["challenger_checks"],
        "thesis": None if thesis is None else {k: thesis.get(k) for k in ("claim_id", "status", "evidence_id", "decision")},
        "referee": REF_IDENTITY, "verdict": verdict,
        "heater": {"source": heater_source, "text": heater_text, "reaction": heater_reaction,
                   "hypothetical": hypothetical},
        "frost": {"source": "TEMPLATE", "challenges": frost, "reaction": frost_reaction},
        # The message may be personal: only its hash is kept.
        "message_sha256": hashlib.sha256(message.encode("utf-8")).hexdigest(),
        "outcome": None,  # scored after the game from the official result; never filled here
    }
    return response, identity


__all__ = ["FORMAT", "VERDICT_CANT", "VERDICT_WORTH", "Check", "InvestigationInputError",
           "challenger_checks", "heater_guard", "investigate", "ref_verdict"]
