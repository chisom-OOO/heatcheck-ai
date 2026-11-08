"""Free-text routing and scenario questions over the live forecast. Pure: no HTTP, files or clock.

Routing (``route``): a message about tonight's markets opens the market board; a message naming a
team or game opens that game's card; a message describing a change ("what if Cleveland were on a
neutral floor", "assume it costs Boston 5%") becomes a SCENARIO; anything else goes to the existing
dialogue (claims and research questions).

Scenario flow:
1. ``parse_scenario`` turns the message into structured changes and a plain-words interpretation.
   Nothing is estimated yet. The interpretation is bound by ``interpretation_id`` (sha256 of the
   game, forecast file and exact changes).
2. The user confirms. ``check_confirmation`` refuses an estimate unless the echoed interpretation
   reproduces the same id: any edit to a change revokes the confirmation (CLAUDE.md rule 4).
3. ``estimate_scenario`` gives baseline vs scenario for the focus team:
   - VENUE_NEUTRAL and HOME_AWAY_SWAP are recalculated with the forecast's own Elo formula
     (p = 1/(1+10^(-(Elo_h - Elo_a + H)/400)), H = 100 Elo points of home court, or 0 at a neutral
     site), but only after the baseline row reproduces from its own Elo values.
   - PLAYER_OUT and REST go to Research's scenario functions through ``EffectsProvider``. Until
     research/scenario-effects is merged the provider is ``ResearchStub``, which says the estimate is
     not available and gives no number.
   - USER_ADJUSTMENT is the user's own number, applied as arithmetic and labelled "Your assumption,
     not modelled". Percentage points and Elo points apply directly; game points need a
     points-to-Elo conversion from the provider, otherwise no number.
   - MARKET_PRICE is a hypothetical market price; it changes the comparison, not the forecast.
   Effects that failed Research's tests are shown with that verdict and left out of the total.
   The Challenger checks double counting, sample size and staleness. The Ref verdict is always
   "HYPOTHETICAL · Edge unverified": a scenario is never evidence that the model beats the market.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Protocol

FORMAT = "heatcheck-whatif/1"           # Max's free-text what-if (POST /api/scenario[/estimate])
MENU_FORMAT = "heatcheck-scenario/1"    # Experience's per-game scenario list (GET /api/scenario), adopted
PROTOCOL_VERSION = "scenario-1"
LANE = "SCENARIO"
VERDICT = "HYPOTHETICAL · Edge unverified"
HOME_COURT_ELO = 100.0  # B1 Elo constant, stated in the live forecast's model text
Z95 = 1.959963984540054  # same constant as Research's combiner
MIN_N = 30              # same floor as the hot-hand comparison: below this a sample is "small"
FORECAST_MAX_AGE = timedelta(hours=48)
ESTIMATE_MAX_AGE = timedelta(days=400)
REPRODUCE_TOL = 5e-4    # the row's p_home_win is rounded to 6 places
REF_IDENTITY = {"name": "scenario-referee", "version": "1"}
YOUR_ASSUMPTION = "Your assumption, not modelled"
KINDS = ("MARKET_PRICE", "VENUE_NEUTRAL", "HOME_AWAY_SWAP", "PLAYER_OUT", "REST", "USER_ADJUSTMENT")

# ------------------------------------------------------------------ teams

# (full name as in the forecast file, aliases matched case-insensitively, abbreviation matched as-is)
TEAMS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("Atlanta Hawks", ("atlanta", "hawks"), "ATL"),
    ("Boston Celtics", ("boston", "celtics"), "BOS"),
    ("Brooklyn Nets", ("brooklyn", "nets"), "BKN"),
    ("Charlotte Hornets", ("charlotte", "hornets"), "CHA"),
    ("Chicago Bulls", ("chicago", "bulls"), "CHI"),
    ("Cleveland Cavaliers", ("cleveland", "cavaliers", "cavs"), "CLE"),
    ("Dallas Mavericks", ("dallas", "mavericks", "mavs"), "DAL"),
    ("Denver Nuggets", ("denver", "nuggets"), "DEN"),
    ("Detroit Pistons", ("detroit", "pistons"), "DET"),
    ("Golden State Warriors", ("golden state", "warriors", "dubs"), "GSW"),
    ("Houston Rockets", ("houston", "rockets"), "HOU"),
    ("Indiana Pacers", ("indiana", "pacers"), "IND"),
    ("LA Clippers", ("la clippers", "los angeles clippers", "clippers"), "LAC"),
    ("Los Angeles Lakers", ("la lakers", "los angeles lakers", "lakers"), "LAL"),
    ("Memphis Grizzlies", ("memphis", "grizzlies"), "MEM"),
    ("Miami Heat", ("miami",), "MIA"),  # "heat" alone is HeatCheck's own word
    ("Milwaukee Bucks", ("milwaukee", "bucks"), "MIL"),
    ("Minnesota Timberwolves", ("minnesota", "timberwolves", "wolves"), "MIN"),
    ("New Orleans Pelicans", ("new orleans", "pelicans"), "NOP"),
    ("New York Knicks", ("new york", "knicks"), "NYK"),
    ("Oklahoma City Thunder", ("oklahoma city", "oklahoma", "thunder"), "OKC"),
    ("Orlando Magic", ("orlando", "magic"), "ORL"),
    ("Philadelphia 76ers", ("philadelphia", "76ers", "sixers"), "PHI"),
    ("Phoenix Suns", ("phoenix", "suns"), "PHX"),
    ("Portland Trail Blazers", ("portland", "trail blazers", "blazers"), "POR"),
    ("Sacramento Kings", ("sacramento", "kings"), "SAC"),
    ("San Antonio Spurs", ("san antonio", "spurs"), "SAS"),
    ("Toronto Raptors", ("toronto", "raptors"), "TOR"),
    ("Utah Jazz", ("utah", "jazz"), "UTA"),
    ("Washington Wizards", ("washington", "wizards"), "WAS"),
)


def _team_patterns() -> list[tuple[str, re.Pattern]]:
    out = []
    for name, aliases, abbr in TEAMS:
        words = sorted({name.lower(), *aliases}, key=len, reverse=True)
        alt = "|".join(re.escape(w) for w in words)
        out.append((name, re.compile(rf"(?<![\w-])(?:(?i:{alt})|{abbr})(?![\w-])")))
    return out


TEAM_PATTERNS = _team_patterns()


def teams_in(text: str) -> list[tuple[int, str]]:
    """(position, full team name) for every team mention, in order; one entry per team."""
    found: dict[str, int] = {}
    for name, pat in TEAM_PATTERNS:
        m = pat.search(text)
        if m:
            found[name] = m.start()
    return sorted((pos, name) for name, pos in found.items())


# ------------------------------------------------------------------ routing

MARKET_CUE = re.compile(
    r"\b(markets?|odds|prices?|polymarket|kalshi|lines?|games? tonight|tonight'?s games|tonight|"
    r"slate|board|interesting (?:game|market|one)|which games?)\b", re.IGNORECASE)
GAME_CUE = re.compile(r"\b(game|games|match-?up|play(?:s|ing)?|vs\.?|versus|against|@|tip|card)\b",
                      re.IGNORECASE)
SCENARIO_CUE = re.compile(
    r"\b(what if|what happens if|what would|suppose|imagine|assume|assuming|hypothetical(?:ly)?|"
    r"if\b|were\b|without)\b", re.IGNORECASE)


def _game_label(row: dict) -> str:
    return f"{row['away_team']} at {row['home_team']}"


def pick_game(text: str, games: list[dict], now_utc: str | None = None) -> tuple[dict | None, list[dict]]:
    """The one game the text names: both teams if two are named, otherwise the team's next game
    (earliest tip at or after now, else the earliest). Returns (game or None, candidates)."""
    named = [n for _, n in teams_in(text)]
    if not named:
        return None, []
    both = [g for g in games if g["home_team"] in named and g["away_team"] in named]
    if both:
        return (both[0], both) if len(both) == 1 else (None, both)
    cands = [g for g in games if g["home_team"] in named or g["away_team"] in named]
    if not cands:
        return None, []
    if len({g["home_team"] for g in cands} | {g["away_team"] for g in cands}) > 2 and len(named) > 1:
        return None, cands  # two teams named that play different games: ask which
    upcoming = sorted((g for g in cands if now_utc is None or g["tip_utc"] >= now_utc),
                      key=lambda g: g["tip_utc"])
    chosen = upcoming[0] if upcoming else sorted(cands, key=lambda g: g["tip_utc"])[0]
    return chosen, cands


def route(message: str, games: list[dict], now_utc: str | None = None) -> dict:
    """Decide what the page does with a free-text message. Never estimates anything."""
    text = message.strip()
    game, cands = pick_game(text, games, now_utc)
    changes = parse_changes(text, game) if game else parse_changes(text, None)
    if changes or (SCENARIO_CUE.search(text) and game and not MARKET_CUE.search(text)
                   and re.search(r"\b(what if|suppose|imagine|assume|hypothetical)", text, re.I)):
        return {"action": "SCENARIO", "game_id": game["game_id"] if game else None,
                "candidates": [g["game_id"] for g in cands], "reason": "the message describes a change"}
    if game:
        return {"action": "OPEN_CARD", "game_id": game["game_id"], "candidates": [g["game_id"] for g in cands],
                "reason": f"names {_game_label(game)}"}
    if cands:
        return {"action": "OPEN_BOARD", "game_id": None, "candidates": [g["game_id"] for g in cands],
                "reason": "names teams in more than one game"}
    if MARKET_CUE.search(text) and not re.search(r"\bhome teams?\b|\bhot hand\b|\brest\b", text, re.I):
        return {"action": "OPEN_BOARD", "game_id": None, "candidates": [], "reason": "asks about tonight's markets"}
    return {"action": "DIALOGUE", "game_id": None, "candidates": [], "reason": "no market, game or scenario"}


def board_intro(n_games: int, n_comparable: int | None = None) -> str:
    """Heater's line when the board opens. No forecast numbers: those are on the cards."""
    games = "one game" if n_games == 1 else f"{_words(n_games)} games"
    return (f"Here's tonight's board: {games}, each with the model's forecast next to the market's "
            "bid and ask. A gap is a question to investigate, not a tip. Pick a card and I'll walk you "
            "through it.")


def card_intro(row: dict) -> str:
    return (f"Here's {_game_label(row)}: the model's forecast next to the market's bid and ask. Ask me "
            "about it, or try a what-if.")


_WORDS = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
          "eleven", "twelve", "thirteen", "fourteen", "fifteen")


def _words(n: int) -> str:
    return _WORDS[n] if 0 <= n < len(_WORDS) else str(n)


# ------------------------------------------------------------------ parsing

NUM = r"(\d{1,3}(?:\.\d+)?)"
PRICE_RE = re.compile(
    rf"\b(?:price|market|odds|line|ask|bid|polymarket|kalshi|priced|trading)\b[^.?!]{{0,40}}?"
    rf"(?:(?:at|to|of|is|was|were|be|=)\s+)?{NUM}\s*(%|percent|cents?|¢)|"
    rf"\b(?:price|market|odds|priced|trading)\b[^.?!]{{0,40}}?\b(0?\.\d{{1,4}})\b", re.IGNORECASE)
NEUTRAL_RE = re.compile(r"\bneutral\s+(?:site|court|floor|venue|ground|arena)\b|\bon a neutral\b|"
                        r"\bin (?:mexico city|london|paris|manchester|berlin|abu dhabi)\b", re.IGNORECASE)
SWAP_RE = re.compile(r"\bswap(?:ped)?\s+(?:home|venue|court|sides|home and away)\b|"
                     r"\bhome and away (?:were |are )?(?:swapped|reversed|flipped)\b|"
                     r"\b(?:flip|reverse)(?:ped|d)?\s+(?:the\s+)?(?:venue|home court|home and away)\b", re.IGNORECASE)
AT_HOME_RE = re.compile(r"(?P<who>[\w .'-]{2,40}?)\s+(?:were|was|is|are|played|plays|play|hosted|hosting)\s+"
                        r"(?:at home|the home team|hosting|at their place)\b", re.IGNORECASE)
AWAY_RE = re.compile(r"(?P<who>[\w .'-]{2,40}?)\s+(?:were|was|is|are|played|plays|play)\s+"
                     r"(?:away|on the road|the away team|visiting|the visitors?)\b", re.IGNORECASE)
PLAYER_OUT_RE = re.compile(
    r"\bwithout\s+(?P<a>[A-Z][\w.'-]+(?:\s+[A-Z][\w.'-]+){0,2})|"
    r"(?P<b>[A-Z][\w.'-]+(?:\s+[A-Z][\w.'-]+){0,2})\s+(?:is|was|were|are|'s|gets?|got)\s+"
    r"(?:ruled\s+)?(?:out|injured|hurt|sidelined|benched|scratched|resting|sitting(?: out)?|suspended)\b|"
    r"(?P<c>[A-Z][\w.'-]+(?:\s+[A-Z][\w.'-]+){0,2})\s+(?:sits|misses|doesn't play|does not play|can't play|"
    r"won't play|sits out)\b")
REST_RE = re.compile(r"\bback[- ]to[- ]back\b|\bb2b\b|\b(?:zero|no|one|two|three|four|\d)\s+days?\s+(?:of\s+)?rest\b|"
                     r"\b(?:well[- ])?rested\b|\bon (?:no|zero|short) rest\b|\bfatigue[d]?\b|\btired\b", re.IGNORECASE)
ADJ_RE = re.compile(
    r"\b(?:assume|assuming|suppose|say|if)\b(?P<clause>[^.?!;]{0,80}?)\b"
    r"(?P<verb>costs?|takes?|knocks?|drops?|cuts?|loses?|subtracts?|minus|gives?|adds?|boosts?|"
    r"worth|lowers?|raises?|helps?|hurts?)\b(?P<rest>[^.?!;]{0,60}?)"
    r"(?:by\s+)?(?P<amount>\d{1,3}(?:\.\d+)?)\s*(?P<unit>percentage points?|pp|%|percent|elo(?: points?)?|points?|pts)(?!\w)",
    re.IGNORECASE)
NEGATIVE_VERBS = ("cost", "take", "knock", "drop", "cut", "lose", "subtract", "minus", "lower", "hurt")
NOT_PLAYERS = {"what", "if", "the", "home", "away", "assume", "suppose", "imagine", "market", "price"}


def _team_in(text: str, row: dict | None) -> str | None:
    """The first team in ``text`` that plays in ``row`` (or any team when no row)."""
    for _, name in teams_in(text):
        if row is None or name in (row["home_team"], row["away_team"]):
            return name
    return None


def _team_near(text: str, pos: int, row: dict | None) -> str | None:
    """The game's team mentioned closest before ``pos`` in the same clause, else after it, else any."""
    start = max(text.rfind(ch, 0, pos) for ch in ".?!;,") + 1
    for before, seg in ((True, text[start:pos]), (False, text[pos:])):
        hits = [(p, n) for p, n in teams_in(seg) if row is None or n in (row["home_team"], row["away_team"])]
        if hits:
            return hits[-1][1] if before else hits[0][1]
    return _team_in(text, row)


def parse_changes(message: str, row: dict | None) -> list[dict]:
    """Structured changes, in a fixed order. Unrecognised text is not guessed at."""
    changes: list[dict] = []
    text = message.strip()
    for m in ADJ_RE.finditer(text):
        verb = m.group("verb").lower()
        sign = -1 if verb.startswith(NEGATIVE_VERBS) else 1
        unit_raw = m.group("unit").lower()
        unit = ("PROB_POINTS" if unit_raw.startswith(("percent", "pp", "%")) else
                "ELO" if unit_raw.startswith("elo") else "GAME_POINTS")
        team = _team_in(m.group("clause") + " " + m.group("rest"), row)
        changes.append({"kind": "USER_ADJUSTMENT", "team": team, "amount": sign * float(m.group("amount")),
                        "unit": unit, "source_text": m.group(0).strip()})
    adj_spans = [m.span() for m in ADJ_RE.finditer(text)]
    for m in PRICE_RE.finditer(text):
        if any(a <= m.start() < b for a, b in adj_spans):
            continue
        if m.group(1) is not None:
            v = float(m.group(1)) / 100.0
        else:
            v = float(m.group(3))
        if 0.0 < v < 1.0:
            changes.append({"kind": "MARKET_PRICE", "team": _team_near(text, m.start(), row), "price": round(v, 4),
                            "source_text": m.group(0).strip()})
        break
    if NEUTRAL_RE.search(text):
        changes.append({"kind": "VENUE_NEUTRAL", "source_text": NEUTRAL_RE.search(text).group(0)})
    swap = SWAP_RE.search(text)
    if not swap and row is not None:
        for rx, want_home in ((AT_HOME_RE, True), (AWAY_RE, False)):
            for m in rx.finditer(text):
                who = _team_in(m.group("who"), row)
                if who is None:
                    continue
                is_home = who == row["home_team"]
                if is_home != want_home:  # the away team at home, or the home team away
                    swap = m
                    break
            if swap:
                break
    if swap:
        changes.append({"kind": "HOME_AWAY_SWAP", "source_text": swap.group(0).strip()})
    seen_players = set()
    for m in PLAYER_OUT_RE.finditer(text):
        name = (m.group("a") or m.group("b") or m.group("c")).strip()
        first = name.split()[0].lower()
        if first in NOT_PLAYERS or teams_in(name) or name.lower() in seen_players:
            continue
        seen_players.add(name.lower())
        changes.append({"kind": "PLAYER_OUT", "player": name, "team": _team_near(text, m.start(), row),
                        "source_text": m.group(0).strip()})
    rest = REST_RE.search(text)
    if rest:
        changes.append({"kind": "REST", "team": _team_near(text, rest.start(), row), "detail": rest.group(0).lower(),
                        "source_text": rest.group(0)})
    return changes


def describe_change(c: dict, row: dict) -> str:
    team = c.get("team")
    if c["kind"] == "MARKET_PRICE":
        return f"The market prices {team or row['home_team']} at {c['price'] * 100:.1f}% (a hypothetical price)."
    if c["kind"] == "VENUE_NEUTRAL":
        return "The game is played on a neutral floor: no home court."
    if c["kind"] == "HOME_AWAY_SWAP":
        return f"Home and away are swapped: {row['home_team']} visit {row['away_team']}."
    if c["kind"] == "PLAYER_OUT":
        return f"{c['player']} does not play{f' for {team}' if team else ''}."
    if c["kind"] == "REST":
        return f"Rest or schedule changes{f' for {team}' if team else ''}: {c['detail']}."
    if c["kind"] == "USER_ADJUSTMENT":
        unit = {"PROB_POINTS": "percentage points", "ELO": "Elo points", "GAME_POINTS": "points"}[c["unit"]]
        sign = "costs" if c["amount"] < 0 else "adds"
        return f"Your assumption: it {sign} {team or 'the team'} {abs(c['amount']):g} {unit}."
    raise ValueError(c["kind"])


def _canon(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def interpretation_id(game_id: str, forecast_sha256: str, changes: list[dict], focus_team: str) -> str:
    return hashlib.sha256(_canon({"format": FORMAT, "game_id": game_id, "forecast_sha256": forecast_sha256,
                                  "changes": changes, "focus_team": focus_team})).hexdigest()


def parse_scenario(message: str, row: dict, forecast_sha256: str) -> dict:
    """The interpretation shown for confirmation. No estimate, no number from the model."""
    changes = parse_changes(message, row)
    focus = _team_in(message, row) or row["home_team"]
    lines = [describe_change(c, row) for c in changes]
    if changes:
        heater = ("Here's how I read your scenario for " + _game_label(row) + ": " + " ".join(lines)
                  + " Is that right? Confirm and I'll run it.")
    else:
        heater = ("I couldn't find a change I can work with in that. Try a neutral floor, swapping home "
                  "and away, a market price, a player out, rest, or your own adjustment (\"assume it "
                  "costs Boston five percentage points\").")
    return {"format": FORMAT, "status": "NEEDS_CONFIRMATION" if changes else "NO_CHANGES",
            "game_id": row["game_id"], "game": _game_label(row), "focus_team": focus,
            "forecast_sha256": forecast_sha256, "changes": changes, "interpretation": lines,
            "interpretation_id": interpretation_id(row["game_id"], forecast_sha256, changes, focus),
            "message_sha256": hashlib.sha256(message.encode("utf-8")).hexdigest(),
            "heater_text": heater, "label": "HYPOTHETICAL"}


class ConfirmationError(ValueError):
    pass


def _valid_change(c: Any) -> dict:
    if not isinstance(c, dict) or c.get("kind") not in KINDS:
        raise ConfirmationError("unknown change kind")
    allowed = {"kind", "team", "source_text", "price", "player", "detail", "amount", "unit"}
    if set(c) - allowed:
        raise ConfirmationError(f"unexpected fields {sorted(set(c) - allowed)}")
    for v in c.values():
        if isinstance(v, float) and not math.isfinite(v):
            raise ConfirmationError("non-finite number")
        if isinstance(v, str) and len(v) > 200:
            raise ConfirmationError("field too long")
    return c


def check_confirmation(req: dict, row: dict, forecast_sha256: str) -> tuple[list[dict], str]:
    """The confirmed changes, or ConfirmationError. The echoed interpretation must reproduce the id
    over the current forecast file: an edit, or a new forecast file, revokes the confirmation."""
    if req.get("confirmed") is not True:
        raise ConfirmationError("the interpretation was not confirmed")
    changes = req.get("changes")
    if not isinstance(changes, list) or not 1 <= len(changes) <= 8:
        raise ConfirmationError("changes must be a list of 1 to 8 items")
    changes = [_valid_change(c) for c in changes]
    focus = req.get("focus_team")
    if focus not in (row["home_team"], row["away_team"]):
        raise ConfirmationError("focus_team must be one of the game's teams")
    if interpretation_id(row["game_id"], forecast_sha256, changes, focus) != req.get("interpretation_id"):
        raise ConfirmationError("confirmation revoked: the interpretation or the forecast changed; "
                                "confirm the new interpretation")
    return changes, focus


# ------------------------------------------------------------------ Research's effects (stub until merged)

class EffectsProvider(Protocol):
    """Research's scenario functions (research/scenario-effects). ``estimate`` gets one PLAYER_OUT or
    REST change and the game context and returns a dict:

    {"status": "ESTIMATE" | "NO_DATA" | "NOT_AVAILABLE",
     "elo_shift": float,                # for change["team"], Elo points (ESTIMATE only)
     "elo_shift_range": [lo, hi],       # interval for the same shift
     "interval": "e.g. 90% bootstrap", "n": int,  # games behind the estimate
     "verdict": "SURVIVED" | "INSUFFICIENT_EVIDENCE" | "FAILED" | "NOT_TESTED",
     "data_through_utc": "...Z", "caveats": [str, ...], "reason": str, "method": str}

    ``points_to_elo`` (or None) converts game points for user adjustments.
    """

    identity: dict

    def estimate(self, change: dict, ctx: dict) -> dict: ...

    def points_to_elo(self) -> float | None: ...

    def menu(self, ctx: dict) -> list[dict] | None:
        """The changes worth showing for this game (e.g. the away team on a back-to-back), as
        PLAYER_OUT/REST change dicts with a "text" sentence; None when not available."""
        ...


class ResearchStub:
    identity = {"name": "research-scenario-effects", "version": "STUB",
                "note": "stub of the signature; research/scenario-effects not merged"}

    def estimate(self, change: dict, ctx: dict) -> dict:
        return {"status": "NOT_AVAILABLE", "reason": "Research's scenario estimates are not merged yet, "
                "so this change gets no number", "caveats": []}

    def points_to_elo(self) -> float | None:
        return None

    def menu(self, ctx: dict) -> list[dict] | None:
        return None


NOT_MERGED = "Research's scenario functions (research/scenario-effects) are not merged yet"

NEEDS = {
    "PLAYER_OUT": "player-level on/off data for the players involved and a lineup-aware model tested on past games",
    "REST": "rest-days data for both teams and a rest effect that passed its own test",
}


# ------------------------------------------------------------------ estimation

def p_from_elo(diff: float) -> float:
    return 1.0 / (1.0 + 10.0 ** (-diff / 400.0))


def elo_from_p(p: float) -> float:
    """Inverse of p_from_elo: the forecast's probability in Elo units (exact baseline)."""
    return 400.0 * math.log10(p / (1.0 - p))


@dataclass
class Check:
    check_id: str
    status: str  # PASS, FLAG, FAIL, INFO
    detail: str

    def as_dict(self) -> dict:
        return {"check_id": self.check_id, "status": self.status, "detail": self.detail}


@dataclass
class Effect:
    change: dict
    kind_label: str           # MODEL_RECALC, ESTIMATE, YOUR_ASSUMPTION, HYPOTHETICAL_PRICE, NO_NUMBER, FAILED_TEST
    text: str
    elo_shift_home: float | None = None       # applied in Elo, home-team perspective
    elo_range_home: tuple[float, float] | None = None
    prob_points_team: float | None = None     # applied after, to the focus team's probability
    n: int | None = None
    verdict: str | None = None
    caveats: list[str] = field(default_factory=list)
    included: bool = False
    detail: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"change": self.change, "type": self.kind_label, "text": self.text, "n": self.n,
                "verdict": self.verdict, "caveats": self.caveats, "included": self.included,
                "elo_shift_home": None if self.elo_shift_home is None else round(self.elo_shift_home, 2),
                "elo_range_home": None if self.elo_range_home is None else [round(x, 2) for x in self.elo_range_home],
                "prob_points_team": self.prob_points_team, **({"detail": self.detail} if self.detail else {})}


def home_court_in_forecast(row: dict) -> float | None:
    """H used for this row (100 or 0), found by reproducing p_home_win from the row's Elo; None if
    neither reproduces (then no model recalculation is offered)."""
    if not all(isinstance(row.get(k), (int, float)) for k in ("elo_home", "elo_away")):
        return None
    d = row["elo_home"] - row["elo_away"]
    for h in (HOME_COURT_ELO, 0.0):
        if abs(p_from_elo(d + h) - row["p_home_win"]) <= REPRODUCE_TOL:
            return h
    return None


def _pct(p: float) -> str:
    return f"{p * 100:.1f}%"


def _parse_utc(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def estimate_scenario(changes: list[dict], row: dict, forecast_doc: dict, is_sample: bool,
                      forecast_sha256: str, as_of_utc: str, provider: EffectsProvider,
                      focus_team: str | None = None) -> dict:
    """Baseline vs scenario for the focus team, per-change effects, Challenger checks, Ref verdict."""
    home, away = row["home_team"], row["away_team"]
    focus = focus_team or home
    sign = 1.0 if focus == home else -1.0
    checks: list[Check] = []
    effects: list[Effect] = []
    h0 = home_court_in_forecast(row)
    as_of = _parse_utc(as_of_utc)

    if is_sample:
        checks.append(Check("FORECAST_REAL", "FAIL", "the forecast is a SAMPLE with made-up numbers"))
    else:
        checks.append(Check("FORECAST_REAL", "PASS", "real forecast file"))
    if h0 is None:
        checks.append(Check("MODEL_REPRODUCES", "FAIL", "p_home_win does not reproduce from the row's Elo "
                                                        "ratings, so the model cannot be recalculated"))
    else:
        checks.append(Check("MODEL_REPRODUCES", "PASS", f"p_home_win reproduces from Elo with home court "
                                                        f"{h0:g} (to {REPRODUCE_TOL})"))

    kinds = [c["kind"] for c in changes]
    # double counting and conflicts
    dc = []
    if "VENUE_NEUTRAL" in kinds and "HOME_AWAY_SWAP" in kinds:
        dc.append(("FAIL", "a neutral floor and a home/away swap contradict each other"))
    for k in set(kinds):
        same = [c for c in changes if c["kind"] == k]
        keyset = {json.dumps({x: c.get(x) for x in ("team", "player", "price", "detail")}, sort_keys=True) for c in same}
        if len(same) > 1 and (len(keyset) < len(same) or k in ("MARKET_PRICE", "VENUE_NEUTRAL", "HOME_AWAY_SWAP")):
            dc.append(("FAIL", f"{k} appears more than once"))
    adj_teams = {c.get("team") or focus for c in changes if c["kind"] == "USER_ADJUSTMENT"}
    for c in changes:
        if c["kind"] in ("PLAYER_OUT", "REST") and (c.get("team") or focus) in adj_teams:
            dc.append(("FLAG", f"your adjustment for {c.get('team') or focus} may already include the "
                               f"{c['kind'].replace('_', ' ').lower()} effect: counted twice?"))
    if "VENUE_NEUTRAL" in kinds and h0 == 0.0:
        dc.append(("FLAG", "the forecast already treats this game as a neutral site; the change does nothing"))
    fail_dc = any(s == "FAIL" for s, _ in dc)
    if dc:
        checks.extend(Check("DOUBLE_COUNT", s, d) for s, d in dc)
    else:
        checks.append(Check("DOUBLE_COUNT", "PASS", "no change counts the same thing twice"))

    # staleness
    cutoff = _parse_utc(forecast_doc["data_cutoff_utc"])
    age = as_of - cutoff
    checks.append(Check("FORECAST_STALENESS", "FLAG" if age > FORECAST_MAX_AGE else "PASS",
                        f"forecast data to {forecast_doc['data_cutoff_utc']}, {age.total_seconds() / 3600:.0f} h "
                        f"before this scenario (limit {FORECAST_MAX_AGE.total_seconds() / 3600:.0f} h)"))
    if _parse_utc(row["tip_utc"]) <= as_of:
        checks.append(Check("GAME_STARTED", "INFO", "the game has already tipped; this is a look back"))

    can_number = not is_sample and not fail_dc
    p2e = provider.points_to_elo()
    for c in changes:
        k = c["kind"]
        team = c.get("team") or focus
        tsign = 1.0 if team == home else -1.0
        if k == "MARKET_PRICE":
            effects.append(Effect(c, "HYPOTHETICAL_PRICE", f"Hypothetical market price {_pct(c['price'])} for "
                                  f"{c.get('team') or focus}; it changes the comparison, not the forecast.",
                                  included=can_number))
        elif k in ("VENUE_NEUTRAL", "HOME_AWAY_SWAP"):
            if h0 is None:
                effects.append(Effect(c, "NO_NUMBER", "Can't recalculate: the forecast row does not reproduce "
                                      "from its own Elo ratings."))
                continue
            d = row["elo_home"] - row["elo_away"]
            if k == "VENUE_NEUTRAL":
                shift = 0.0 - h0
                text = "Model recalculated (Elo only): home court removed."
            else:
                # home-team perspective: the home team now visits, so its margin is d - H instead of d + h0
                shift = (d - HOME_COURT_ELO) - (d + h0)
                text = f"Model recalculated (Elo only): {home} play away, {away} get home court."
            effects.append(Effect(c, "MODEL_RECALC", text, elo_shift_home=shift, elo_range_home=(shift, shift),
                                  included=can_number, caveats=["Elo only: no travel, rest or crowd beyond the "
                                                                "fixed home-court constant"]))
        elif k in ("PLAYER_OUT", "REST"):
            r = provider.estimate(c, {"game": row, "home_court_elo": h0, "as_of_utc": as_of_utc})
            st = r.get("status")
            if st == "ESTIMATE":
                lo, hi = r["elo_shift_range"]
                shift = float(r["elo_shift"]) * tsign
                rng = (min(lo * tsign, hi * tsign), max(lo * tsign, hi * tsign))
                verdict = r.get("verdict", "NOT_TESTED")
                failed = verdict == "FAILED"
                e = Effect(c, "FAILED_TEST" if failed else "ESTIMATE",
                           ("Estimate shown with its verdict: it FAILED our own test, so it is left out of the "
                            "scenario." if failed else "ESTIMATE from Research's scenario functions."),
                           elo_shift_home=shift, elo_range_home=rng, n=r.get("n"), verdict=verdict,
                           caveats=list(r.get("caveats") or []), included=can_number and not failed,
                           detail={k2: r.get(k2) for k2 in ("method", "interval", "data_through_utc") if r.get(k2)})
                effects.append(e)
                if isinstance(r.get("n"), int) and r["n"] < MIN_N:
                    checks.append(Check("SAMPLE_SIZE", "FLAG", f"{describe_change(c, row)} rests on {r['n']} "
                                                               f"games (under {MIN_N})"))
                elif isinstance(r.get("n"), int):
                    checks.append(Check("SAMPLE_SIZE", "PASS", f"{r['n']} games behind {k.lower()}"))
                dt = r.get("data_through_utc")
                if dt and as_of - _parse_utc(dt) > ESTIMATE_MAX_AGE:
                    checks.append(Check("ESTIMATE_STALENESS", "FLAG", f"{k.lower()} estimate uses data through {dt}"))
            elif st == "NO_DATA":
                effects.append(Effect(c, "NO_NUMBER", f"No data: {r.get('reason') or 'nothing to estimate from'}. "
                                      "No number.", caveats=list(r.get("caveats") or [])))
            else:
                effects.append(Effect(c, "NO_NUMBER", f"Can't quantify this with the current model; it would need "
                                      f"{NEEDS[k]}. No number. ({r.get('reason') or 'not available'})"))
        elif k == "USER_ADJUSTMENT":
            amt = float(c["amount"])
            if c["unit"] == "PROB_POINTS":
                effects.append(Effect(c, "YOUR_ASSUMPTION", f"{YOUR_ASSUMPTION}: {amt:+g} percentage points for {team}.",
                                      prob_points_team=amt * (1.0 if team == focus else -1.0), included=can_number))
            elif c["unit"] == "ELO" or (c["unit"] == "GAME_POINTS" and p2e):
                elo = amt if c["unit"] == "ELO" else amt * p2e
                effects.append(Effect(c, "YOUR_ASSUMPTION", f"{YOUR_ASSUMPTION}: {amt:+g} "
                                      f"{'Elo' if c['unit'] == 'ELO' else 'points'} for {team}"
                                      + ("" if c["unit"] == "ELO" else f" (x {p2e:g} Elo per point, Research's conversion)")
                                      + ".", elo_shift_home=elo * tsign, elo_range_home=(elo * tsign, elo * tsign),
                                      included=can_number))
            else:
                effects.append(Effect(c, "NO_NUMBER", f"{YOUR_ASSUMPTION}: turning game points into a win "
                                      "probability needs a points-to-Elo conversion Research hasn't supplied, so no "
                                      "number. Give it in percentage points instead."))

    # combine
    baseline_home = float(row["p_home_win"])
    baseline = baseline_home if sign > 0 else 1.0 - baseline_home
    scen = None
    if can_number and any(e.included and e.kind_label != "HYPOTHETICAL_PRICE" for e in effects):
        if any(e.included and e.elo_shift_home is not None for e in effects) and h0 is None:
            scen = None
        else:
            d0 = elo_from_p(float(row["p_home_win"])) if h0 is not None else None
            mid = lo = hi = None
            if d0 is not None:
                inc = [e for e in effects if e.included and e.elo_shift_home is not None]
                mid = d0 + sum(e.elo_shift_home for e in inc)
                # Research's combiner: each 95% interval as a normal, combined in quadrature
                sd = math.sqrt(sum(((e.elo_range_home[1] - e.elo_range_home[0]) / (2 * Z95)) ** 2 for e in inc))
                lo, hi = mid - Z95 * sd, mid + Z95 * sd
                pm, pl, ph = (p_from_elo(x) for x in (mid, lo, hi))
            else:
                pm = pl = ph = baseline_home
            if sign < 0:
                pm, pl, ph = 1 - pm, 1 - ph, 1 - pl
            pp = sum(e.prob_points_team for e in effects if e.included and e.prob_points_team is not None) / 100.0
            pm, pl, ph = pm + pp, pl + pp, ph + pp
            if not all(0.0 < x < 1.0 for x in (pm, pl, ph)):
                checks.append(Check("RANGE", "FAIL", "the adjusted probability leaves 0-100%; no number"))
            else:
                scen = {"p": round(pm, 4), "range": [round(pl, 4), round(ph, 4)],
                        "range_is_point": abs(ph - pl) < 1e-9}
    price = next((e.change["price"] for e in effects if e.kind_label == "HYPOTHETICAL_PRICE" and e.included), None)
    if price is not None and (next(c for c in changes if c["kind"] == "MARKET_PRICE").get("team") or focus) != focus:
        price = 1.0 - price  # stated for the other team: show it for the focus team
    sample_note = "the forecast is a SAMPLE with made-up numbers" if is_sample else None
    reasons = [ch.detail for ch in checks if ch.status == "FAIL"]
    model_changes = [e for e in effects if e.kind_label != "HYPOTHETICAL_PRICE"]
    if scen is None and not reasons and model_changes:
        reasons = ["none of these changes can be quantified with the current model"]
    ref = VERDICT + ". "
    shown = scen["p"] if scen is not None else baseline
    if price is not None and not reasons:
        rel = "above" if shown > price else "below" if shown < price else "level with"
        ref += (f"Against a hypothetical market price of {_pct(price)}, the "
                f"{'scenario' if scen is not None else 'unchanged forecast'} for {focus} sits "
                f"{abs(shown - price) * 100:.1f} points {rel} it. ")
    if scen is not None:
        ref += (f"This is a what-if, not a forecast: {focus} goes from {_pct(baseline)} to {_pct(scen['p'])}"
                + ("" if scen["range_is_point"] else f" (range {_pct(scen['range'][0])} to {_pct(scen['range'][1])})")
                + ". ")
    elif reasons:
        ref += "No scenario number: " + "; ".join(reasons) + ". "
    flags = [ch.detail for ch in checks if ch.status == "FLAG"]
    if flags:
        ref += "Watch out: " + "; ".join(flags) + ". "
    ref += "Nothing here shows the model beats the market."
    return {
        "format": FORMAT, "label": "HYPOTHETICAL", "game_id": row["game_id"], "game": _game_label(row),
        "focus_team": focus, "as_of_utc": as_of_utc, "is_sample": is_sample,
        "baseline": None if is_sample else {"p": round(baseline, 4), "source": "live forecast",
                                            "data_cutoff_utc": forecast_doc["data_cutoff_utc"]},
        "scenario": scen, "hypothetical_price": price,
        "effects": [e.as_dict() for e in effects], "challenger_checks": [c.as_dict() for c in checks],
        "verdict": VERDICT, "ref_text": ref.strip(), "sample_note": sample_note,
        "provider": provider.identity,
    }


def scenario_identity(est: dict, changes: list[dict], interp_id: str, forecast_sha256: str,
                      message_sha256: str | None) -> dict:
    """What goes in the ledger: the confirmed changes, inputs, outputs and verdict."""
    return {"protocol_version": PROTOCOL_VERSION, "format": FORMAT, "lane": LANE,
            "as_of_utc": est["as_of_utc"], "game_id": est["game_id"], "focus_team": est["focus_team"],
            "forecast_sha256": forecast_sha256, "interpretation_id": interp_id,
            "message_sha256": message_sha256, "changes": changes, "baseline": est["baseline"],
            "scenario": est["scenario"], "hypothetical_price": est["hypothetical_price"],
            "effects": est["effects"], "challenger_checks": est["challenger_checks"],
            "provider": est["provider"], "referee": REF_IDENTITY, "verdict": est["verdict"],
            "label": "HYPOTHETICAL", "outcome": None}


# ------------------------------------------------------------------ GET /api/scenario (heatcheck-scenario/1)

def _prob_str(p: float) -> str:
    return f"{p:.6f}"


def scenario_menu(row: dict, forecast_doc: dict, is_sample: bool, forecast_sha256: str, as_of_utc: str,
                  provider: EffectsProvider, team: str | None = None) -> dict:
    """Experience's heatcheck-scenario/1 answer for one game card (apps/web/HANDOFF.md).

    Only Research's estimates appear in ``scenarios``, each labelled ESTIMATE with p_team_win, range
    (low, high, level), n, n_unit and at least one caveat, converted with the forecast's own Elo
    formula. Extra lists the page may ignore: ``failed_tests`` (estimates whose own test FAILED,
    never shown as plain estimates) and ``not_quantified`` (no number, with the reason).
    """
    home = row["home_team"]
    team = team or home
    if team not in (home, row["away_team"]):
        raise ValueError("team must be one of the game's teams")
    sign = 1.0 if team == home else -1.0
    p_home = float(row["p_home_win"])
    base = {"format": MENU_FORMAT, "game_id": row["game_id"], "team": team, "is_sample": is_sample,
            "baseline": {"p_team_win": _prob_str(p_home if sign > 0 else 1.0 - p_home),
                         "forecast_id": f"live-forecast:{forecast_sha256}"},
            "source": f"{provider.identity.get('name')} {provider.identity.get('version')}; probabilities via "
                      "the live forecast's Elo formula",
            "as_of_utc": as_of_utc, "scenarios": [], "failed_tests": [], "not_quantified": [],
            "verdict": VERDICT}
    if is_sample:
        return {**base, "status": "UNAVAILABLE", "reason": "the forecast is a SAMPLE with made-up numbers"}
    h0 = home_court_in_forecast(row)
    if h0 is None:
        return {**base, "status": "UNAVAILABLE",
                "reason": "the forecast row does not reproduce from its own Elo ratings"}
    ctx = {"game": row, "home_court_elo": h0, "as_of_utc": as_of_utc}
    changes = provider.menu(ctx)
    if changes is None:
        return {**base, "status": "UNAVAILABLE", "reason": NOT_MERGED}
    d0 = elo_from_p(p_home)
    as_of = _parse_utc(as_of_utc)
    for c in changes:
        text = str(c.get("text") or "").strip()
        sid = hashlib.sha256(_canon({"game_id": row["game_id"], "change": c})).hexdigest()[:16]
        r = provider.estimate(c, ctx)
        if r.get("status") != "ESTIMATE":
            base["not_quantified"].append({"scenario_id": sid, "text": text, "reason": r.get("reason") or
                                           ("no data" if r.get("status") == "NO_DATA" else "not available")})
            continue
        caveats = [x for x in (r.get("caveats") or []) if isinstance(x, str) and x.strip()]
        n, level = r.get("n"), r.get("level")
        problems = []
        if not caveats:
            problems.append("Research gave no caveats")
        if not isinstance(n, int) or n < 1:
            problems.append("Research gave no sample size")
        if not isinstance(level, (int, float)) or not 0 < level < 1:
            problems.append("Research gave no interval level")
        if problems:
            base["not_quantified"].append({"scenario_id": sid, "text": text, "reason": "; ".join(problems)})
            continue
        tsign = 1.0 if (c.get("team") or team) == home else -1.0
        mid = d0 + float(r["elo_shift"]) * tsign
        lo_hi = sorted(d0 + float(x) * tsign for x in r["elo_shift_range"])
        pm, pl, ph = p_from_elo(mid), p_from_elo(lo_hi[0]), p_from_elo(lo_hi[1])
        if sign < 0:
            pm, pl, ph = 1 - pm, 1 - ph, 1 - pl
        pl, ph = min(pl, pm), max(ph, pm)
        item = {"scenario_id": sid, "text": text, "label": "ESTIMATE", "p_team_win": _prob_str(pm),
                "range": {"low": _prob_str(pl), "high": _prob_str(ph), "level": f"{float(level):.2f}"},
                "n": n, "n_unit": r.get("n_unit") or "games", "caveats": caveats,
                "method": r.get("method") or "", "verdict": r.get("verdict") or "NOT_TESTED",
                "change": c, "evidence": r.get("evidence") or {}}
        dt = r.get("data_through_utc")
        if n < MIN_N:
            item["caveats"] = caveats + [f"small sample: {n} {item['n_unit']} (under {MIN_N})"]
        if dt and as_of - _parse_utc(dt) > ESTIMATE_MAX_AGE:
            item["caveats"] = item["caveats"] + [f"stale: uses data through {dt}"]
        (base["failed_tests"] if item["verdict"] == "FAILED" else base["scenarios"]).append(item)
    status = "OK" if base["scenarios"] else "UNAVAILABLE"
    out = {**base, "status": status}
    if status != "OK":
        out["reason"] = "Research's functions returned no estimate for this game"
    return out
