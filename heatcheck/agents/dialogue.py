"""Free dialogue around the Discoverer -> Challenger -> Referee loop.

Display names: the Discoverer is shown to users as "Heater"; the Referee as "the Ref". The
role name in code, protocol and evidence stays "discoverer".

Order of one turn (``Dialogue.turn``):
1. Map the user's question to a registered claim id or NONE: LLM with a strict json_schema
   enum, validated again here; on any failure a deterministic keyword stand-in.
2. NONE: no test runs, nothing is written to the ledger. Heater may answer in character; the
   Ref text is a fixed template saying no registered test exists.
3. If the ledger holds a recorded, custodian-receipted Research result for the claim
   (heatcheck/agents/recorded.py: the 2023-24 GAME_PREDICTION final, later the confirmatory
   final), that entry answers it: nothing runs and nothing is written.
4. Otherwise the loop runs that registered claim: the Challenger (add-only) and the
   deterministic Referee. The evidence entry is written to the append-only ledger.
   Confirmatory claims (CONF-*) without a recorded final go to ``ConfirmatoryLane`` instead,
   which in its default dry-run mode runs and writes nothing.
5. The Ref's text is a deterministic template built from the evidence entry (no model call).
   Heater (the only model-written text) reacts in character; its text passes the number guard
   against the record, else Heater's fixed line is used.

No LLM output reaches ``decide()`` or the Ref. Every model call has an 8 s deadline and a
deterministic fallback, so a turn always returns all fields.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from typing import Any

from heatcheck.agents import frost
from heatcheck.agents.confirmatory import (
    CONFIRMATORY_IDS,
    EVIDENCE,
    LANE_CONFIRMATORY,
    SUBDIR,
    ConfirmatoryLane,
)
from heatcheck.agents.llm import LLMUnavailable, MetaChat, prompt_sha256
from heatcheck.agents.loop import run_once
from heatcheck.agents.recorded import RECORDED_ONLY_STATEMENTS, find_recorded
from heatcheck.agents.recorded import SOURCE as RECORDED_SOURCE
from heatcheck.agents.registry import ATTACKS, CLAIMS, Claim, catalogue
from heatcheck.agents.roles import (
    DeterministicChallenger,
    ProposalRefused,
    parse_selection,
    required_attacks,
    validate_selection,
    view_capabilities,
)
from heatcheck.agents.views import ShotView
from heatcheck.api.display_titles import display_title
from heatcheck.contracts.records import loads_strict
from heatcheck.ledger.evidence import EvidenceLedger

DISCOVERER_DISPLAY_NAME = "Heater"
REFEREE_DISPLAY_NAME = "the Ref"
NONE = "NONE"
DECISIONS = ("SURVIVED_PROTOCOL", "NOT_SUPPORTED", "INSUFFICIENT_EVIDENCE", "DATA_INVALID", "BLOCKED")

# --------------------------------------------------------------------------- mapping

_CONF_STATEMENTS: dict[str, str] = {}


def confirmatory_statements() -> dict[str, str]:
    """Claim text of the frozen confirmatory plans (read from Research's evidence)."""
    if not _CONF_STATEMENTS:
        for hid in CONFIRMATORY_IDS:
            plan = json.loads((EVIDENCE / SUBDIR / f"{hid}.plan.json").read_text(encoding="utf-8"))
            _CONF_STATEMENTS[hid] = plan["claim"]
    return _CONF_STATEMENTS


def mapping_catalogue() -> list[dict]:
    """What a question may map to: registry claims, recorded-only claims (GP-ELO), then the
    confirmatory family."""
    return ([{"claim_id": c["claim_id"], "statement": c["statement"]} for c in catalogue()]
            + [{"claim_id": h, "statement": t} for h, t in RECORDED_ONLY_STATEMENTS.items()]
            + [{"claim_id": h, "statement": t} for h, t in confirmatory_statements().items()])


def mappable_ids() -> set[str]:
    return {c["claim_id"] for c in mapping_catalogue()}


def statement_of(claim_id: str) -> str:
    if claim_id in CLAIMS:
        return CLAIMS[claim_id].statement
    if claim_id in RECORDED_ONLY_STATEMENTS:
        return RECORDED_ONLY_STATEMENTS[claim_id]
    return confirmatory_statements()[claim_id]



# The page's three question chips always go to the same claim (user instruction, 8 Nov), before
# any model call, like home advantage. Exact chip text only (case, spaces and the final "?" ignored);
# any other wording is mapped by the model as before.
CHIP_ROUTES = {"is the hot hand real": "CONF-HH", "does rest matter": "GP-REST",
               "do home teams win more": "CONF-HA"}


def chip_route(question: str) -> str | None:
    key = re.sub(r"\s+", " ", question).strip().rstrip("?!. ").strip().lower()
    return CHIP_ROUTES.get(key)


HOME_ADVANTAGE = re.compile(
    r"\bhome[- ](court|teams?|sides?|advantage|crowds?|floor)\b|\bat home\b|\bhome (win|wins|winning)\b",
    re.IGNORECASE)


def keyword_map(question: str) -> str:
    """Deterministic stand-in mapping. Field-goal streak questions only (free throws are out
    of scope per docs/DECISIONS.md)."""
    q = question.lower()
    if re.search(r"\bfree[- ]throws?\b", q):
        return NONE
    if re.search(r"\bhome[- ](court|teams?|advantage)\b", q):
        return "CONF-HA"
    if re.search(r"\belo\b|base[- ]rate|coin[- ]?flip", q):
        return "GP-ELO"
    if re.search(r"\b(rest|back[- ]to[- ]backs?|days? off|b2b)\b", q):
        return "GP-REST"
    streak = re.search(r"hot hand|streak|in a row|straight|consecutive|heat(ing)? up|on fire", q)
    if streak:
        if re.search(r"\b(two|2)\b", q) and not re.search(r"\b(three|3)\b", q):
            return "HH-K2"
        return "HH-K3"
    return NONE


MAP_SYSTEM = (
    "You route a basketball fan's question to a registered statistical claim. Answer with the "
    "single claim_id whose statement the question is asking about, or NONE if no registered "
    "claim tests it. Do not stretch: a different statistic, a different sport, free throws, or "
    "a question needing a test not listed is NONE. Registered claims: {catalogue}"
)


def map_schema() -> dict:
    ids = [c["claim_id"] for c in mapping_catalogue()] + [NONE]
    return {"type": "json_schema", "json_schema": {"name": "claim_mapping", "strict": True, "schema": {
        "type": "object", "additionalProperties": False, "required": ["claim_id"],
        "properties": {"claim_id": {"type": "string", "enum": ids}}}}}


def parse_mapping(text: str) -> str:
    """Strict (RV-AL6): exactly {"claim_id": <registered id or NONE>} with no duplicate keys,
    a string id matched exactly. Raises ValueError otherwise; nothing is coerced."""
    try:
        obj = loads_strict(text)
    except (TypeError, ValueError) as e:
        raise ValueError(f"mapping is not strict JSON: {e}") from None
    if not isinstance(obj, dict) or set(obj) != {"claim_id"}:
        raise ValueError("mapping must be exactly {claim_id}")
    cid = obj["claim_id"]
    if not isinstance(cid, str):
        raise ValueError(f"claim_id must be a string, not {type(cid).__name__}")
    if cid != NONE and cid not in mappable_ids():
        raise ValueError(f"claim_id {cid!r} is not registered")
    return cid


# --------------------------------------------------------------------------- Discoverer


class MappedDiscoverer:
    """Proposer for run_once: proposes the claim the user's question was mapped to."""

    def __init__(self, claim_id: str, question: str, mapping_identity: dict):
        self.claim_id = claim_id
        self.question_sha256 = hashlib.sha256(question.encode()).hexdigest()
        self.identity = {"role": "discoverer", "display_name": DISCOVERER_DISPLAY_NAME,
                         "version": "1", **mapping_identity}

    def propose(self, catalogue_: list[dict], already_evaluated: set[str]) -> str:
        return json.dumps({"claim_id": self.claim_id,
                           "rationale": f"user question sha256:{self.question_sha256}"})


# --------------------------------------------------------------------------- Challenger

CHALLENGER_SYSTEM = (
    "You are the Challenger in a statistics protocol. The required checks always run. From the "
    "additional registered checks listed, select every one that could expose a way this claim "
    "is wrong on this data. Use only the listed ids."
)


def addable_attacks(claim: Claim, view: ShotView) -> list[str]:
    """Registered attacks a Challenger may ADD: applicable to the view and not already required.
    Under heatcheck-registry/1 every applicable attack is required, so this is empty."""
    have, req = view_capabilities(view), set(required_attacks(claim, view))
    return sorted(a.attack_id for a in ATTACKS.values()
                  if set(a.requires) <= have and a.attack_id not in req)


class LLMChallenger:
    """Model Challenger that can only ADD registered attacks to the Referee's required set
    (user rule, RV-AL4/AL5). Its JSON is parsed strictly (RV-AL6). With nothing addable the
    model is not called. Any failure falls back to the deterministic Challenger."""

    def __init__(self, llm: MetaChat):
        self.llm = llm
        self.identity: dict = {}
        self.fallback_reason: str | None = None
        self.note: str | None = None

    def select(self, claim: Claim, view: ShotView) -> list[str]:
        required = required_attacks(claim, view)
        addable = addable_attacks(claim, view)
        if not addable:
            self.note = "LLM not called: every applicable registered attack is already required"
            self.identity = {**DeterministicChallenger.identity, "llm_not_called": self.note}
            return required
        messages = [{"role": "system", "content": CHALLENGER_SYSTEM},
                    {"role": "user", "content": json.dumps({
                        "claim": {"claim_id": claim.claim_id, "statement": claim.statement},
                        "required": required,
                        "additional": [{"attack_id": a, "way_claim_could_be_wrong":
                                        ATTACKS[a].way_claim_could_be_wrong} for a in addable]})}]
        # No "uniqueItems": Meta structured outputs reject it (HTTP 400, live turn 17:27Z).
        fmt = {"type": "json_schema", "json_schema": {"name": "attack_selection", "strict": True, "schema": {
            "type": "object", "additionalProperties": False, "required": ["attacks"],
            "properties": {"attacks": {"type": "array", "items": {"type": "string", "enum": addable}}}}}}
        try:
            res = self.llm.complete("challenger", messages, response_format=fmt)
            chosen = validate_selection(claim, parse_selection(res.text))
            bad = [a for a in chosen if a not in addable]
            if bad:
                raise ProposalRefused(f"not addable here: {bad}")
            self.identity = {"role": "challenger", "kind": "LLM", "version": "1", **self.llm.identity,
                             "prompt": prompt_sha256(messages, fmt)}
            return sorted(set(required) | set(chosen))
        except (LLMUnavailable, ProposalRefused, ValueError, TypeError) as e:
            self.fallback_reason = getattr(e, "reason", None) or f"{type(e).__name__}: {e}"
            self.identity = {**DeterministicChallenger.identity, "fallback_from": "LLM",
                             "fallback_reason": self.fallback_reason[:200]}
            return required


# --------------------------------------------------------------------------- Ref guard

_SPELLED = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
    "fifteen sixteen seventeen eighteen nineteen twenty".split())}
_SPELLED.update({"thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
                 "eighty": 80, "ninety": 90, "hundred": 100, "thousand": 1000})
# Spelled-out numbers are a style allowance for small values (e.g. "three makes"). Larger
# values must be quoted as digits exactly as the record writes them.
MAX_SPELLED = 10
# A unit suffix changes what a number means (0.061 vs 6.1%, 3 vs "3 times"). Such a number is
# allowed only if the record has the same value with the same kind of suffix.
_SUFFIX = r"(\s*(?:%|percent\b|per\s+cent\b|times\b|x\b|-?fold\b))?"
_NUM = re.compile(r"(?<![\w.])([-+−]?)([0-9]{1,3}(?:,[0-9]{3})+(?:\.[0-9]+)?|[0-9]+(?:\.[0-9]+)?|\.[0-9]+)"
                  + _SUFFIX)
_WORDNUM = re.compile(r"\b(" + "|".join(_SPELLED) + r")\b" + _SUFFIX, re.IGNORECASE)
_SCI = re.compile(r"[0-9.][eE][-+]?[0-9]")
_FRACTION = re.compile(r"\b(half|halves|thirds?|quarters?|twice|double[ds]?|triple[ds]?|"
                       r"dozens?|majority|minority)\b", re.IGNORECASE)

DECISION_PHRASES = {
    "SURVIVED_PROTOCOL": r"\bsurviv(?:ed|es|al)\b|\bsurvived_protocol\b",
    "NOT_SUPPORTED": r"\bnot[ _]supported\b|\bunsupported\b",
    "INSUFFICIENT_EVIDENCE": r"\binsufficient[ _]evidence\b|\bnot enough evidence\b",
    "DATA_INVALID": r"\bdata[ _](?:is |are )?invalid\b|\binvalid data\b",
    "BLOCKED": r"\bblocked\b",
}
# Verdict-like words no decision uses. Allowed only if the record's own text contains them.
OVERCLAIM = re.compile(
    r"\b(prov(?:e|en|es|ed)|proof|confirm(?:s|ed)?|debunk(?:s|ed)?|myth|guarantee[ds]?|"
    r"definitely|certain(?:ly)?|significan(?:t|tly|ce)|real|fake|true|false|(?<!not )supported|"
    r"supports?|verified|validated|wins?|loses?|right|wrong|luck|lucky|confident|confidence|"
    r"chance)\b", re.IGNORECASE)


def _kind(suffix: str | None) -> str:
    s = (suffix or "").strip().lower()
    if not s:
        return ""
    return "%" if s in ("%", "percent") or s.startswith("per") else "x"


def _numbers(text: str) -> list[tuple[str, Decimal, str]]:
    """(sign, magnitude, kind) for every number in text; kind is '', '%' or 'x'."""
    out = []
    for sign, digits, suffix in _NUM.findall(text):
        try:
            d = Decimal(digits.replace(",", ""))
        except InvalidOperation:
            continue
        out.append(("-" if sign and sign in "-−" else "+", d, _kind(suffix)))
    for w, suffix in _WORDNUM.findall(text):
        out.append(("+", Decimal(_SPELLED[w.lower()]), _kind(suffix)))
    return out


def _walk(o: Any):
    if isinstance(o, dict):
        for v in o.values():
            yield from _walk(v)
    elif isinstance(o, list):
        for v in o:
            yield from _walk(v)
    else:
        yield o


def ref_facts(entry: dict) -> dict:
    """The part of an evidence entry the Ref may talk about. Hashes are excluded so their hex
    digits cannot license invented numbers."""
    i = entry["identity"]
    if i.get("source") == RECORDED_SOURCE:
        return recorded_facts(entry)
    claim = CLAIMS[i["claim"]["claim_id"]]
    return {
        "claim_id": claim.claim_id, "statement": claim.statement, "decision": i["decision"],
        "reason": i["reason"], "limits": i["limits"],
        "data": {k: i["data"].get(k) for k in ("data_mode", "n_attempts", "n_groups", "n_games")},
        "params": {k: v for k, v in i["claim"]["plan"]["params"].items() if k != "seed"},
        "attacks": [{"test": r["test_id_version"], "status": r["status"], "reason": r["reason"],
                     "statistic": r["statistic"], "effect_estimate": r["effect_estimate"],
                     "p_value": r["p_value"]} for r in i["attack_results"]],
    }


def recorded_facts(entry: dict) -> dict:
    """Ref facts for an entry recorded from Research's receipted results (no hashes)."""
    i = entry["identity"]
    r = i["result"]
    detail = r.get("detail") or {}
    n_games = i["data"].get("n_games") or r.get("n_games") or detail.get("n_games")
    season = i["data"].get("season")
    return {
        "claim_id": i["claim"]["claim_id"], "statement": i["claim"]["statement"],
        "decision": i["decision"], "reason": i["reason"], "limits": i["limits"],
        "lane": i["lane"], "phase": i["phase"],
        "data": {"data_mode": i["data"].get("data_mode"), "season": season,
                 "n_attempts": detail.get("n_fga"), "n_groups": None, "n_games": n_games},
        "params": {}, "attacks": [],
        "result": {k: v for k, v in r.items() if k != "detail"},
        "source_note": (f"Source: Research's recorded {i['phase'].lower()} run"
                        + (f" on {n_games} unseen {season} games" if n_games and season else "")
                        + ", under a custodian exposure receipt; copied here, not recomputed."),
    }


def _record_text(facts: dict) -> str:
    return " ".join(str(v) for v in _walk(facts) if isinstance(v, str)).lower()


def allowed_numbers(facts: dict) -> set[tuple[str, Decimal, str]]:
    out: set[tuple[str, Decimal, str]] = set()
    for v in _walk(facts):
        if isinstance(v, bool) or v is None:
            continue
        if isinstance(v, (int, float)):
            d = Decimal(repr(v))
            out.add(("-" if d < 0 else "+", abs(d), ""))
        elif isinstance(v, str):
            out.update(_numbers(v))
    return out


def number_violations(text: str, facts: dict) -> list[str]:
    allowed = allowed_numbers(facts)
    bad = []
    for ch in text:
        if ch.isdigit() and ch not in "0123456789":
            bad.append(f"non-ASCII digit {ch!r}")
            break
    if _SCI.search(text):
        bad.append("scientific notation")
    # Fraction words only if the verdict reason or claim statement itself uses them (e.g. "not
    # replicated on both halves"); an attack's method name such as "split-half" does not count.
    verdict_text = f"{facts.get('reason', '')} {facts.get('statement', '')}".lower()
    for m in _FRACTION.finditer(text):
        if m.group(0).lower() not in verdict_text:
            bad.append(f"fraction word {m.group(0)!r}")
    for w, _suffix in _WORDNUM.findall(text):
        if _SPELLED[w.lower()] > MAX_SPELLED:
            bad.append(f"spelled-out {w!r} (quote counts as digits from the record)")
    for sign, d, kind in _numbers(text):
        if (sign, d, kind) not in allowed:
            bad.append(("-" if sign == "-" else "") + str(d) + kind)
    return bad


def ref_guard(text: str, facts: dict, *, require_verdict: bool = True) -> list[str]:
    """Problems with the Ref's text; empty means it may be shown. Deterministic and pure.

    Checks that every number (digits, signed, spelled, with % or "times") is in the record;
    that the verdict is stated (``require_verdict``); that no other verdict's wording appears;
    and that over-claim words appear only if the record uses them. It checks numbers, not what
    a number refers to: an in-record count attached to the wrong noun is not caught."""
    problems = [f"number {n} is not in the evidence record" for n in number_violations(text, facts)]
    decision = facts["decision"]
    if require_verdict and not re.search(DECISION_PHRASES[decision], text, re.IGNORECASE):
        problems.append(f"verdict {decision} is not stated")
    for other, pat in DECISION_PHRASES.items():
        if other != decision and re.search(pat, text, re.IGNORECASE):
            problems.append(f"verdict word for {other} contradicts the record ({decision})")
    record_text = _record_text(facts)
    for m in OVERCLAIM.finditer(text):
        if m.group(0).lower() not in record_text:
            problems.append(f"verdict word {m.group(0)!r} is not in the evidence record")
    return problems


def ref_guard_allows(text: str, entry: dict) -> bool:
    """Reviewer interface (HEATCHECK_REVIEW_REF_GUARD=heatcheck.agents.dialogue:ref_guard_allows):
    True when ``text`` may be spoken about evidence ``entry``. Numbers and verdict words only;
    whether the text states the verdict is checked separately by the dialogue."""
    return not ref_guard(text, ref_facts(entry), require_verdict=False)


PLAIN = {"SURVIVED_PROTOCOL": "Survived the registered checks (SURVIVED_PROTOCOL)",
         "NOT_SUPPORTED": "Not supported by the registered checks (NOT_SUPPORTED)",
         "INSUFFICIENT_EVIDENCE": "Insufficient evidence (INSUFFICIENT_EVIDENCE)",
         "DATA_INVALID": "Data invalid (DATA_INVALID)",
         "BLOCKED": "Blocked: the test could not run (BLOCKED)"}


def ref_template(facts: dict) -> str:
    """The Ref's words: deterministic, built only from the evidence record (no model call).
    Numbers appear only inside the record's own reason and source note, verbatim."""
    statement = facts["statement"].rstrip(".")
    text = (f"{PLAIN[facts['decision']]}. {display_title(facts['claim_id'])} "
            f"({facts['claim_id']}). What was tested: {statement}. Why: {facts['reason']}.")
    if facts.get("source_note"):
        text += " " + facts["source_note"]
    return text


CONF_PENDING_REF = (
    "{cid} is a pre-registered confirmatory claim on the sealed {season} season: {statement} "
    "Its single final test has not been run, so there is no verdict yet. It runs once, recorded, "
    "after the reviewer verifies the seal. Dry run: {summary}.")


def dry_run_summary(report: dict) -> str:
    by = {c["check"]: c["status"] for c in report["checks"]}
    core = [k for k in by if k.startswith(("family", "plan:")) or k in
            ("research_code", "seal", "registration", "exposure")]
    bad = [k for k in core if by[k] != "PASS"]
    parts = ["plans, code and seal match" if not bad else f"MISMATCH in {', '.join(bad)}"]
    if by.get("sealed_data") == "NOT_CHECKED":
        parts.append("the sealed data were not checked on this machine")
    elif by.get("sealed_data") == "FAIL":
        parts.append("the data do NOT match the seal")
    return "; ".join(parts)


NO_TEST_REF = ("No registered test exists for this question, so nothing was run and there is no "
               "verdict. Registered claims: {ids}.")

NO_RECORD_REF = ("{title} ({cid}) is answered only by a recorded Research result, and none is in "
                 "this evidence ledger, so there is no verdict here.")

# --------------------------------------------------------------------------- Heater

HEATER_SYSTEM = (
    "You are Heater, an original character: a loud, theatrical sports-debate pundit on a "
    "basketball statistics show. You are fictional. Never name, quote, imitate or allude to any "
    "real commentator, broadcaster, host or media personality, and do not use their catchphrases. "
    "Speak in at most three short sentences, with big energy and the odd ALL-CAPS burst. You are "
    "entertainment, not evidence: never state statistics or numbers. You speak BEFORE the Ref and "
    "do not know the verdict: give your hot take on the fan's question only, and never mention the "
    "Ref, a verdict, a test, a result or the evidence."
)

# Heater's first line is the hot take only: it is spoken before the Ref, so it never depends on
# or mentions the verdict (rehearsal fix, 8 Nov 2026). The verdict-aware line is heater_reaction.
HEATER_TAKE_FALLBACK = "Heater here, and I've got OPINIONS on this one! My gut says YES, and my gut is LOUD."
REF_MENTION = re.compile(
    r"\b(?:the\s+)?ref(?:eree)?s?\b|\bverdict|\bsurviv\w*|\bnot\s+supported\b|\binsufficient\b|"
    r"\bevidence\b|\bregistered\b|\btest(?:ed|s)?\b|\bchecks?\b|\bruled?\b|\bruling\b|\bvault\b|"
    r"\bdata\b", re.IGNORECASE)


# Safer-gambling guard for every Heater line, model-written or template (8 Nov 2026). Whole words
# or phrases, case-insensitive: "better", "between" and "lockdown" pass; "lock" only as a phrase.
BETTING_WORDS = re.compile(
    r"(?<![\w'’])(?:bet|bets|betting|wager|value bet|free money|guaranteed|sure thing|"
    r"can['’]?t lose|cannot lose|a lock|lock it in|mortal lock)(?![\w'’])", re.IGNORECASE)


# Frost's rephrase only (Heater's list above is the user's exact list): British betting slang.
FROST_EXTRA_BETTING = re.compile(r"(?<![\w'’])punt(?:s|er|ers|ing|ed)?(?![\w'’])", re.IGNORECASE)


def betting_words(text: str) -> list[str]:
    """Betting-encouragement wording in a Heater line; empty means it may be said."""
    return sorted({m.group(0).lower() for m in BETTING_WORDS.finditer(text or "")})


def take_mentions_ref(text: str) -> list[str]:
    """Words that would have Heater speak about the Ref's verdict before the Ref has spoken."""
    return sorted({m.group(0).lower() for m in REF_MENTION.finditer(text or "")})


# Heater's reaction, spoken after the stamp (heater_reaction). Keyed by verdict; None = no test.
HEATER_REACTION = {
    None: "Heater here, and I've got OPINIONS! But the Ref says there's no registered test for "
          "that one, so take this as pure hot air.",
    "SURVIVED_PROTOCOL": "Heater here! The Ref says it SURVIVED the checks. I'm not saying I "
                         "called it... but I'm saying it LOUDLY.",
    "NOT_SUPPORTED": "Heater here, and OUCH. The Ref says not supported. I'll be back with a "
                     "hotter take.",
    "INSUFFICIENT_EVIDENCE": "Heater here! The Ref wants more evidence before ruling. Patience is "
                             "NOT my game, but rules are rules.",
    "DATA_INVALID": "Heater here, and the Ref threw out the data! You can't cook with a broken "
                    "stove.",
    "BLOCKED": "Heater here! The Ref says that test can't run yet. Stay tuned.",
    "CONFIRMATORY_PENDING": "Heater here! That one's locked in the vault for its one big "
                            "official run. No peeking, no verdict yet. I'm DYING to know.",
}
HEATER_FALLBACK = HEATER_REACTION  # old name, kept for importers


def heater_reaction(out: dict) -> str:
    """The reaction after the stamp, from the verdict the Ref actually gave."""
    if out.get("verdict"):
        return HEATER_REACTION.get(out["verdict"], "")
    return HEATER_REACTION[None] if out.get("claim_id") == NONE else HEATER_REACTION["CONFIRMATORY_PENDING"]


# --------------------------------------------------------------------------- turn


@dataclass
class Dialogue:
    view: ShotView | None
    ledger: EvidenceLedger
    llm: MetaChat | None  # None: deterministic only
    view_identity: dict | None = None
    confirmatory: ConfirmatoryLane | None = None  # None: default dry-run lane

    def turn(self, question: str) -> dict[str, Any]:
        out = self._turn(question)
        out["heater_reaction"] = heater_reaction(out)
        # Turns with no evidence entry (no registered test, not yet run): same keys, no challenges.
        out.setdefault("frost", [])
        out.setdefault("frost_reaction", frost.FROST_REACTION[None])
        return out

    def _frost_phrase(self, chal, facts) -> dict[str, str]:
        """Adviser's guarded rephrase of Frost's QUESTION only; any failure keeps the template.
        Adapted by Max: MetaChat has complete(role, messages), not chat(...); the 4 s deadline never
        raises the client's own; the calls run in parallel, so Frost adds at most one deadline."""
        from concurrent.futures import ThreadPoolExecutor
        # The adviser's max_tokens=60 left no room: live calls ended finish_reason=length with empty text
        # (8 Nov, 5/5). The client's default cap is kept; the 220-character guard keeps it short.
        llm = replace(self.llm, timeout_s=min(4.0, self.llm.timeout_s))

        def one(c):
            try:
                text = llm.complete("frost", [{"role": "system", "content": frost.FROST_SYSTEM},
                                              {"role": "user", "content": c.question}]).text
            except Exception:
                return None
            if number_violations(text, facts) or take_mentions_ref(text) or len(text) > 220:
                return None                   # fall back to the template question
            # FROST_SYSTEM says "never suggest betting"; enforce it (live, 8 Nov: "simultaneous punts")
            if betting_words(text) or FROST_EXTRA_BETTING.search(text):
                return None
            return text.strip()

        if not chal:
            return {}
        with ThreadPoolExecutor(max_workers=len(chal)) as pool:
            texts = list(pool.map(one, chal))
        return {c.check: t for c, t in zip(chal, texts, strict=True) if t}

    def _turn(self, question: str) -> dict[str, Any]:
        sources: dict[str, str] = {"ref": "TEMPLATE"}
        claim_id, sources["mapping"], map_identity = self._map(question)
        if claim_id == NONE:
            ref_text = NO_TEST_REF.format(ids=", ".join(c["claim_id"] for c in mapping_catalogue()))
            heater_text, sources["heater"] = self._heater(question, None, None, None)
            sources["ref"] = "TEMPLATE_NO_REGISTERED_TEST"
            return {"heater_text": heater_text, "ref_text": ref_text, "evidence_record_id": None,
                    "verdict": None, "claim_id": NONE, "claim_title": display_title(NONE),
                    "lane": None, "evidence_source": None, "sources": sources}
        # A recorded, receipted final result answers its claim; nothing is rerun or rewritten.
        recorded = find_recorded(self.ledger, claim_id)
        if recorded is not None:
            sources["challenger"] = "NOT_APPLICABLE (recorded final result)"
            return self._respond(question, claim_id, recorded, sources)
        if claim_id in CONFIRMATORY_IDS:
            return self._confirmatory_turn(question, claim_id, map_identity, sources)
        if claim_id in RECORDED_ONLY_STATEMENTS:
            heater_text, sources["heater"] = self._heater(question, claim_id, None, None,
                                                          pending=True)
            sources["ref"] = "TEMPLATE_NO_RECORDED_RESULT"
            return {"heater_text": heater_text,
                    "ref_text": NO_RECORD_REF.format(title=display_title(claim_id), cid=claim_id),
                    "evidence_record_id": None, "verdict": None, "claim_id": claim_id,
                    "claim_title": display_title(claim_id), "lane": None,
                    "evidence_source": None, "sources": sources}
        challenger = LLMChallenger(self.llm) if self.llm else DeterministicChallenger()
        entry = run_once(self.view, self.ledger, view_identity=self.view_identity,
                         jone=MappedDiscoverer(claim_id, question, map_identity),
                         challenger=challenger)
        note = getattr(challenger, "fallback_reason", None)
        note = f"fallback: {note}" if note else getattr(challenger, "note", None)
        sources["challenger"] = challenger.identity.get("kind", "DETERMINISTIC_STANDIN") + (
            f" ({note})" if note else "")
        return self._respond(question, claim_id, entry, sources)

    def _respond(self, question, claim_id, entry, sources) -> dict[str, Any]:
        # What is displayed is what ran or was recorded: claim and verdict come from the
        # evidence entry, and a mismatch with the mapping is an internal error (RV-AL6).
        ident = entry["identity"]
        if ident["claim"]["claim_id"] != claim_id:
            raise RuntimeError(f"evidence claim {ident['claim']['claim_id']!r} differs from the "
                               f"mapped claim {claim_id!r}")
        facts = ref_facts(entry)
        ref_text = ref_template(facts)
        heater_text, sources["heater"] = self._heater(question, claim_id, facts["decision"], facts)
        out = {"heater_text": heater_text, "ref_text": ref_text,
               "evidence_record_id": entry["evidence_id"], "verdict": ident["decision"],
               "claim_id": claim_id, "claim_title": display_title(claim_id),
               "lane": ident.get("lane"),
               "evidence_source": ident.get("source", "AGENT_LOOP"), "sources": sources}
        if ident.get("source") == RECORDED_SOURCE:
            out["phase"] = ident["phase"]
            out["custodian_receipt_id"] = ident["custodian"]["receipt_id"]
        chal = frost.select(facts)
        phrased = self._frost_phrase(chal, facts) if self.llm else None   # guarded, see _frost_phrase
        out["frost"] = frost.to_payload(chal, phrased)
        out["frost_reaction"] = frost.FROST_REACTION.get(ident["decision"], frost.FROST_REACTION[None])
        return out

    def _confirmatory_turn(self, question, claim_id, map_identity, sources) -> dict[str, Any]:
        lane = self.confirmatory or ConfirmatoryLane()
        disc = MappedDiscoverer(claim_id, question, map_identity)
        proposer = {**disc.identity, "rationale": f"user question sha256:{disc.question_sha256}"}
        out = lane.evaluate(claim_id, self.ledger, proposer)
        if "dry_run" in out:
            sources["challenger"] = "NOT_APPLICABLE (confirmatory: frozen pre-registered procedure)"
            report = out["dry_run"]
            ref_text = CONF_PENDING_REF.format(cid=claim_id, season="2024-25",
                                               statement=statement_of(claim_id),
                                               summary=dry_run_summary(report))
            heater_text, sources["heater"] = self._heater(question, claim_id, None, None,
                                                          pending=True)
            sources["ref"] = "TEMPLATE_CONFIRMATORY_NOT_RUN"
            return {"heater_text": heater_text, "ref_text": ref_text, "evidence_record_id": None,
                    "verdict": None, "claim_id": claim_id, "claim_title": display_title(claim_id),
                    "lane": LANE_CONFIRMATORY, "evidence_source": None,
                    "confirmatory_status": report["state"],
                    "dry_run": {"ready": report["ready"], "checks": report["checks"]},
                    "sources": sources}
        sources["challenger"] = "NOT_APPLICABLE (recorded final result)"
        return self._respond(question, claim_id, out["entry"], sources)

    # -- pieces

    def _map(self, question: str) -> tuple[str, str, dict]:
        # Home-advantage questions always go to the confirmatory CONF-HA result (user
        # instruction, 7 November), never to GP-ELO, whatever the LLM would choose.
        if HOME_ADVANTAGE.search(question):   # also covers the "Do home teams win more?" chip
            return "CONF-HA", "KEYWORD_RULE (home advantage -> CONF-HA)", {
                "kind": "DETERMINISTIC_RULE", "model": None, "prompt": None, "rule": "HOME_ADVANTAGE"}
        chip = chip_route(question)
        if chip is not None:
            return chip, f"FIXED_CHIP_RULE ({question.strip()} -> {chip})", {
                "kind": "DETERMINISTIC_RULE", "model": None, "prompt": None, "rule": "CHIP_ROUTES"}
        if self.llm:
            messages = [{"role": "system", "content": MAP_SYSTEM.format(
                catalogue=json.dumps(mapping_catalogue()))},
                {"role": "user", "content": question}]
            fmt = map_schema()
            try:
                cid = parse_mapping(self.llm.complete("discoverer_map", messages, response_format=fmt).text)
                return cid, "LLM", {"kind": "LLM", **self.llm.identity,
                                    "prompt": prompt_sha256(messages, fmt)}
            except (LLMUnavailable, ValueError, TypeError) as e:
                reason = getattr(e, "reason", None) or f"{type(e).__name__}: {e}"
                cid = keyword_map(question)
                return cid, f"KEYWORD_STANDIN (fallback: {reason[:120]})", {
                    "kind": "DETERMINISTIC_STANDIN", "model": None, "prompt": None,
                    "fallback_from": "LLM", "fallback_reason": reason[:200]}
        return keyword_map(question), "KEYWORD_STANDIN", {
            "kind": "DETERMINISTIC_STANDIN", "model": None, "prompt": None}

    def _heater(self, question, claim_id, decision, facts, pending=False) -> tuple[str, str]:
        """Heater's hot take, spoken before the Ref: the verdict, the decision and the pending state
        are deliberately not used, so the take cannot pre-empt the Ref."""
        del decision, pending
        fallback = HEATER_TAKE_FALLBACK
        if not self.llm:
            return fallback, "TEMPLATE"
        ctx = {"fan_question": question}
        messages = [{"role": "system", "content": HEATER_SYSTEM},
                    {"role": "user", "content": json.dumps(ctx)}]
        try:
            text = self.llm.complete("heater", messages, stream=True).text.strip()
        except LLMUnavailable as e:
            return fallback, f"TEMPLATE (fallback: {e.reason[:120]})"
        bad = number_violations(text, facts or {})
        if bad:
            return fallback, f"TEMPLATE (guard rejected numbers {bad})"
        ref_words = take_mentions_ref(text)
        if ref_words:
            return fallback, f"TEMPLATE (guard rejected Ref mention {ref_words[:4]})"
        bet_words = betting_words(text)
        if bet_words:
            return fallback, f"TEMPLATE (guard rejected betting wording {bet_words[:4]})"
        return text, "LLM"
