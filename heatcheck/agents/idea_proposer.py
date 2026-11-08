"""Idea-family proposer (runtime Discoverer) for Research's grammar heatcheck-idea-family/1.

Grammar: docs/IDEA_GRAMMAR.md on research/idea-family@d43b29a7, with Research's
``handoff/research-20261107/src/heatcheck/ideas.py`` governing where the two differ.

The proposer turns a fan's message into a family request. It sees only the message, the mode
and the grammar's enumerations: no data, no results, no truth. It cannot supply thresholds,
filters, seeds, sample sizes or tests; the grammar has no field for them.

- LLM path: the model must answer with a JSON schema whose every value is an enumeration.
  Its text is then validated strictly (``validate_request``, a Max mirror of Research's
  validator). Anything invalid is refused, never repaired, and the deterministic proposer is
  used instead with the refusal recorded in ``source``.
- Deterministic path: fixed keyword rules map basketball phrases to grammar ideas.

Running the family (register, freeze, test, Holm) is Research's runner; this module only
proposes. Pure apart from the optional ``llm`` callable.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from typing import Any

from heatcheck.contracts.records import loads_strict

FORMAT = "heatcheck-idea-family/1"
GRAMMAR_SOURCE = "research/idea-family@d43b29a7 docs/IDEA_GRAMMAR.md + src/heatcheck/ideas.py"
MAX_IDEAS = 20
ALTERNATIVES = ("two_sided", "greater", "less")
MODES = ("development", "synthetic")

# Copied from Research's ideas.py at d43b29a7; tests compare them to that file's literals.
GAME_LEVELS: dict[str, tuple[str, ...]] = {
    "home_rest_days": ("0", "1", "2", "3+"),
    "away_rest_days": ("0", "1", "2", "3+"),
    "rest_advantage": ("home_more", "equal", "away_more"),
    "home_back_to_back": ("yes",),
    "away_back_to_back": ("yes",),
    "elo_gap": ("home_fav_100+", "home_fav_0_100", "away_fav_0_100", "away_fav_100+"),
    "month": ("10", "11", "12", "01", "02", "03"),
    "day_of_week": ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"),
}
SHOT_LEVELS: dict[str, tuple[str, ...]] = {
    "after_makes": ("1", "2", "3", "4"),
    "after_misses": ("1", "2", "3", "4"),
    "shot_value": ("3",),
    "period": ("1", "2", "3", "4", "OT"),
}
TEMPLATES = {"GAME_HOME_WIN_SPLIT": ("feature", GAME_LEVELS),
             "SHOT_MAKE_AFTER_CONDITION": ("condition", SHOT_LEVELS)}


class IdeaRefused(ValueError):
    pass


def canonical(idea: dict) -> bytes:
    return json.dumps(idea, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def idea_hash(idea: dict) -> str:
    return hashlib.sha256(canonical(idea)).hexdigest()


def _exact(obj: Any, keys: set[str], what: str) -> None:
    if not isinstance(obj, dict) or set(obj) != keys:
        raise IdeaRefused(f"{what} must have exactly the keys {sorted(keys)}")


def _enum(v: Any, allowed: tuple[str, ...], what: str) -> str:
    if type(v) is not str or v not in allowed:
        raise IdeaRefused(f"{what} must be one of {list(allowed)}; got {v!r}")
    return v


def validate_request(obj: Any, mode: str) -> list[dict]:
    """Strict mirror of Research's validate_request. Returns canonical ideas; raises IdeaRefused."""
    if mode not in MODES:
        raise IdeaRefused(f"mode must be one of {MODES}")
    if isinstance(obj, (str, bytes)):
        try:
            obj = loads_strict(obj.decode("utf-8") if isinstance(obj, bytes) else obj)
        except (ValueError, UnicodeDecodeError) as e:
            raise IdeaRefused(f"not strict JSON: {e}") from None
    _exact(obj, {"format", "ideas"}, "request")
    if obj["format"] != FORMAT:
        raise IdeaRefused(f"format must be {FORMAT!r}")
    ideas = obj["ideas"]
    if not isinstance(ideas, list) or not 1 <= len(ideas) <= MAX_IDEAS:
        raise IdeaRefused(f"ideas must be a list of 1 to {MAX_IDEAS} ideas")
    out, seen = [], set()
    for i, it in enumerate(ideas):
        _exact(it, {"template", "params"}, f"idea {i}")
        tpl = _enum(it["template"], tuple(TEMPLATES), f"idea {i} template")
        if mode == "synthetic" and tpl != "SHOT_MAKE_AFTER_CONDITION":
            raise IdeaRefused(f"idea {i}: {tpl} is not available in synthetic mode")
        key, levels = TEMPLATES[tpl]
        _exact(it["params"], {key, "level", "alternative"}, f"idea {i} params")
        k = _enum(it["params"][key], tuple(levels), f"idea {i} {key}")
        lv = _enum(it["params"]["level"], levels[k], f"idea {i} level for {key}={k}")
        alt = _enum(it["params"]["alternative"], ALTERNATIVES, f"idea {i} alternative")
        if mode == "synthetic" and k == "period" and lv == "OT":
            raise IdeaRefused(f"idea {i}: synthetic leagues have no overtime period")
        idea = {"params": {key: k, "level": lv, "alternative": alt}, "template": tpl}
        h = idea_hash(idea)
        if h in seen:
            raise IdeaRefused(f"idea {i} duplicates an earlier idea")
        seen.add(h)
        out.append(idea)
    return out


# --------------------------------------------------------------------------- deterministic proposer


def _g(feature: str, level: str, alt: str) -> dict:
    return {"template": "GAME_HOME_WIN_SPLIT", "params": {"feature": feature, "level": level, "alternative": alt}}


def _s(condition: str, level: str, alt: str) -> dict:
    return {"template": "SHOT_MAKE_AFTER_CONDITION",
            "params": {"condition": condition, "level": level, "alternative": alt}}


_NUM = {"one": "1", "two": "2", "three": "3", "four": "4", "1": "1", "2": "2", "3": "3", "4": "4"}
_DAYS = {d.lower(): d[:3] for d in ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
                                    "Saturday", "Sunday")}
_MONTHS = {"october": "10", "november": "11", "december": "12", "january": "01", "february": "02",
           "march": "03"}


def keyword_ideas(message: str) -> list[dict]:
    """Fixed rules from phrases to ideas. Direction follows the fan's stated belief where the
    phrase states one; otherwise two-sided."""
    q = message.lower()
    ideas: list[dict] = []
    if re.search(r"back[- ]to[- ]backs?|\bb2b\b|second night|tired|fatigue", q):
        ideas += [_g("away_back_to_back", "yes", "greater"), _g("home_back_to_back", "yes", "less")]
    if re.search(r"\brest(ed|ing)?\b|days? off|rest days?", q):
        ideas += [_g("rest_advantage", "home_more", "greater"), _g("rest_advantage", "away_more", "less")]
    if re.search(r"\belo\b|favou?rites?|underdogs?|better team|stronger team", q):
        ideas += [_g("elo_gap", "home_fav_100+", "greater"), _g("elo_gap", "away_fav_100+", "less")]
    for name, d in _DAYS.items():
        if re.search(rf"\b{name}s?\b", q):
            ideas.append(_g("day_of_week", d, "two_sided"))
    for name, m in _MONTHS.items():
        if re.search(rf"\b{name}\b", q):
            ideas.append(_g("month", m, "two_sided"))
    streak = re.search(r"hot hand|streak|in a row|straight|consecutive|heat(ing)? up|on fire", q)
    n = re.search(r"\b(one|two|three|four|[1-4])\s+(?:straight|in a row|makes?|shots?|buckets?|consecutive)", q)
    level = _NUM[n.group(1)] if n else "3"
    if streak or re.search(r"after (a )?makes?", q):
        ideas.append(_s("after_makes", level, "greater"))
    if re.search(r"after (a )?miss(es)?|cold|slump|ice[- ]cold|bricks?", q):
        ideas.append(_s("after_misses", level, "less"))
    if re.search(r"three[- ]pointers?|\b3[- ]pointers?|\bthrees\b|from deep|beyond the arc", q):
        ideas.append(_s("shot_value", "3", "two_sided"))
    if re.search(r"overtime|\bot\b", q):
        ideas.append(_s("period", "OT", "two_sided"))
    if re.search(r"fourth quarter|4th quarter|\bclutch\b|late in games?|crunch time", q):
        ideas.append(_s("period", "4", "two_sided"))
    if re.search(r"first quarter|1st quarter|start of (the )?games?|opening quarter", q):
        ideas.append(_s("period", "1", "two_sided"))
    unique, seen = [], set()
    for i in ideas:
        h = idea_hash(i)
        if h not in seen:
            seen.add(h)
            unique.append(i)
    return unique[:MAX_IDEAS]


# --------------------------------------------------------------------------- LLM proposer

SYSTEM = (
    "You propose testable basketball ideas for a fixed test machine. Answer only with JSON in the "
    "schema given. Choose {min} to {max} different ideas from the enumerations that match what the fan is asking. "
    "Use 'greater' or 'less' only when the fan states a direction (for example 'tired teams lose more'); "
    "otherwise 'two_sided'. Do not invent features. If nothing in the enumerations fits, return the "
    "single closest idea. Templates: GAME_HOME_WIN_SPLIT compares the home-win rate in games with one "
    "feature value against all other games. SHOT_MAKE_AFTER_CONDITION compares field-goal make rates "
    "when a condition holds against when it does not. Free throws are out of scope."
)


def response_schema(mode: str, min_ideas: int = 1, max_ideas: int = MAX_IDEAS) -> dict:
    game = {"type": "object", "additionalProperties": False, "required": ["template", "params"],
            "properties": {"template": {"type": "string", "enum": ["GAME_HOME_WIN_SPLIT"]},
                           "params": {"type": "object", "additionalProperties": False,
                                      "required": ["feature", "level", "alternative"],
                                      "properties": {"feature": {"type": "string", "enum": list(GAME_LEVELS)},
                                                     "level": {"type": "string", "enum": sorted(
                                                         {v for vs in GAME_LEVELS.values() for v in vs})},
                                                     "alternative": {"type": "string", "enum": list(ALTERNATIVES)}}}}}
    shot = {"type": "object", "additionalProperties": False, "required": ["template", "params"],
            "properties": {"template": {"type": "string", "enum": ["SHOT_MAKE_AFTER_CONDITION"]},
                           "params": {"type": "object", "additionalProperties": False,
                                      "required": ["condition", "level", "alternative"],
                                      "properties": {"condition": {"type": "string", "enum": list(SHOT_LEVELS)},
                                                     "level": {"type": "string", "enum": sorted(
                                                         {v for vs in SHOT_LEVELS.values() for v in vs})},
                                                     "alternative": {"type": "string", "enum": list(ALTERNATIVES)}}}}}
    items = shot if mode == "synthetic" else {"anyOf": [game, shot]}
    return {"type": "json_schema", "json_schema": {"name": "idea_family", "strict": True, "schema": {
        "type": "object", "additionalProperties": False, "required": ["format", "ideas"],
        "properties": {"format": {"type": "string", "enum": [FORMAT]},
                       "ideas": {"type": "array", "minItems": min_ideas, "maxItems": max_ideas, "items": items}}}}}


def propose_family(message: str, mode: str = "development",
                   llm: Callable[[list[dict], dict], str] | None = None, *, min_ideas: int = 1,
                   max_ideas: int = MAX_IDEAS) -> dict:
    """Returns {"request", "source", "proposer", "ideas": [{idea, idea_hash}]} or, when nothing
    in the grammar fits, {"request": None, "source", "reason"}. The request always validates."""
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    source = "KEYWORD_STANDIN"
    proposer: dict[str, Any] = {"kind": "DETERMINISTIC_STANDIN", "grammar": GRAMMAR_SOURCE,
                                "message_sha256": hashlib.sha256(message.encode("utf-8")).hexdigest()}
    if not 1 <= min_ideas <= max_ideas <= MAX_IDEAS:
        raise ValueError("need 1 <= min_ideas <= max_ideas <= MAX_IDEAS")
    request, llm_raw = None, None
    if llm is not None:
        fmt = response_schema(mode, min_ideas, max_ideas)
        messages = [{"role": "system", "content": SYSTEM.format(min=min_ideas, max=max_ideas)},
                    {"role": "user", "content": message}]
        prompt = hashlib.sha256(json.dumps([messages, fmt], sort_keys=True).encode()).hexdigest()
        try:
            text = llm(messages, fmt)
            llm_raw = text
            n = len(validate_request(text, mode))  # strict parse of the model's exact text
            if not min_ideas <= n <= max_ideas:
                raise IdeaRefused(f"{n} ideas, outside {min_ideas} to {max_ideas}")
            request = loads_strict(text)
            source = "LLM"
            proposer.update(kind="LLM", prompt_sha256=prompt)
        except IdeaRefused as e:
            source = f"KEYWORD_STANDIN (LLM proposal refused: {str(e)[:160]})"
        except Exception as e:  # provider failure: no invented ideas
            source = f"KEYWORD_STANDIN (fallback: {type(e).__name__})"
    if request is None:
        ideas = keyword_ideas(message)
        if mode == "synthetic":
            ideas = [i for i in ideas if i["template"] == "SHOT_MAKE_AFTER_CONDITION"
                     and i["params"] != {"condition": "period", "level": "OT", "alternative": "two_sided"}]
        if not ideas:
            return {"request": None, "source": source, "proposer": proposer,
                    "reason": "no idea in heatcheck-idea-family/1 matches this message"}
        request = {"format": FORMAT, "ideas": ideas}
    ideas = validate_request(request, mode)  # always re-validated, whichever path produced it
    return {"request": request, "source": source, "proposer": proposer, "mode": mode, "llm_raw": llm_raw,
            "ideas": [{"idea": i, "idea_hash": idea_hash(i)} for i in ideas]}


__all__ = ["FORMAT", "IdeaRefused", "idea_hash", "keyword_ideas", "propose_family",
           "response_schema", "validate_request"]
