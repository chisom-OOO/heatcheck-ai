"""Free dialogue around the Discoverer -> Challenger -> Referee loop.

Display names: the Discoverer is shown to users as "Heater"; the Referee as "the Ref". The
role name in code, protocol and evidence stays "discoverer".

Order of one turn (``Dialogue.turn``):
1. Map the user's question to a registered claim id or NONE: LLM with a strict json_schema
   enum, validated again here; on any failure a deterministic keyword stand-in.
2. NONE: no test runs, nothing is written to the ledger. Heater may answer in character; the
   Ref text is a fixed template saying no registered test exists.
3. Otherwise the loop runs that registered claim: the Challenger (LLM choosing among eligible
   optional attacks, mandatory attacks always added; stand-in on failure) and the
   deterministic Referee. The evidence entry is written to the append-only ledger.
4. Heater reacts and the Ref phrases the verdict, in parallel. The Ref's text passes
   ``ref_guard``: every number and verdict word must come from the evidence record, else the
   deterministic template is used. Heater's text passes the number part of the guard.

No LLM output reaches ``decide()``. Every LLM call has an 8 s deadline and a deterministic
fallback, so a turn always returns all four fields.
"""

from __future__ import annotations

import concurrent.futures as cf
import hashlib
import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from heatcheck.agents.llm import LLMUnavailable, MetaChat, prompt_sha256
from heatcheck.agents.loop import run_once
from heatcheck.agents.registry import ATTACKS, CLAIMS, Claim, catalogue
from heatcheck.agents.roles import DeterministicChallenger
from heatcheck.agents.views import ShotView
from heatcheck.ledger.evidence import EvidenceLedger
from heatcheck.ledger.referee_view import referee_view

DISCOVERER_DISPLAY_NAME = "Heater"
REFEREE_DISPLAY_NAME = "the Ref"
NONE = "NONE"
DECISIONS = ("SURVIVED_PROTOCOL", "NOT_SUPPORTED", "INSUFFICIENT_EVIDENCE", "DATA_INVALID", "BLOCKED")

# --------------------------------------------------------------------------- mapping


def keyword_map(question: str) -> str:
    """Deterministic stand-in mapping. Field-goal streak questions only (free throws are out
    of scope per docs/DECISIONS.md)."""
    q = question.lower()
    if re.search(r"\bfree[- ]throws?\b", q):
        return NONE
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
    ids = [c["claim_id"] for c in catalogue()] + [NONE]
    return {"type": "json_schema", "json_schema": {"name": "claim_mapping", "strict": True, "schema": {
        "type": "object", "additionalProperties": False, "required": ["claim_id"],
        "properties": {"claim_id": {"type": "string", "enum": ids}}}}}


def parse_mapping(text: str) -> str:
    """Strict: exactly {"claim_id": <registered id or NONE>}. Raises ValueError otherwise."""
    obj = json.loads(text)
    if not isinstance(obj, dict) or set(obj) != {"claim_id"}:
        raise ValueError("mapping must be exactly {claim_id}")
    cid = obj["claim_id"]
    if cid != NONE and cid not in CLAIMS:
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
    "You are the Challenger in a statistics protocol. Mandatory checks always run. From the "
    "eligible optional checks listed, select every check that could expose a way this claim is "
    "wrong on this data. Use only the listed ids."
)


def _eligible_optional(view: ShotView) -> list[str]:
    std = DeterministicChallenger().select(None, view)  # type: ignore[arg-type]
    return [a for a in std if not ATTACKS[a].mandatory]


class LLMChallenger:
    """Selects optional attacks with the LLM; mandatory attacks are always added. Falls back to
    the deterministic Challenger on any provider or validation failure."""

    def __init__(self, llm: MetaChat):
        self.llm = llm
        self.identity: dict = {}
        self.fallback_reason: str | None = None

    def select(self, claim: Claim, view: ShotView) -> list[str]:
        eligible = _eligible_optional(view)
        mandatory = sorted(a.attack_id for a in ATTACKS.values() if a.mandatory)
        messages = [{"role": "system", "content": CHALLENGER_SYSTEM},
                    {"role": "user", "content": json.dumps({
                        "claim": {"claim_id": claim.claim_id, "statement": claim.statement},
                        "mandatory": mandatory,
                        "eligible_optional": [{"attack_id": a, "way_claim_could_be_wrong":
                                               ATTACKS[a].way_claim_could_be_wrong} for a in eligible]})}]
        fmt = {"type": "json_schema", "json_schema": {"name": "attack_selection", "strict": True, "schema": {
            "type": "object", "additionalProperties": False, "required": ["optional_attacks"],
            # No "uniqueItems": Meta structured outputs reject it (HTTP 400, live turn 17:27Z);
            # duplicates are removed below.
            "properties": {"optional_attacks": {"type": "array",
                                                "items": {"type": "string", "enum": eligible or ["__none__"]}}}}}}
        try:
            if not eligible:
                raise LLMUnavailable("no eligible optional attacks; nothing for the LLM to choose")
            res = self.llm.complete("challenger", messages, response_format=fmt)
            obj = json.loads(res.text)
            if not isinstance(obj, dict) or set(obj) != {"optional_attacks"} \
                    or not isinstance(obj["optional_attacks"], list):
                raise ValueError("selection must be exactly {optional_attacks: [...]}")
            chosen = obj["optional_attacks"]
            bad = [a for a in chosen if a not in eligible]
            if bad:
                raise ValueError(f"unregistered or ineligible attacks {bad}")
            self.identity = {"role": "challenger", "kind": "LLM", "version": "1", **self.llm.identity,
                             "prompt": prompt_sha256(messages, fmt)}
            return sorted(set(mandatory) | set(chosen))
        except (LLMUnavailable, ValueError, TypeError) as e:
            self.fallback_reason = getattr(e, "reason", None) or f"{type(e).__name__}: {e}"
            std = DeterministicChallenger()
            self.identity = {**std.identity, "fallback_from": "LLM",
                             "fallback_reason": self.fallback_reason[:200]}
            return std.select(claim, view)


# --------------------------------------------------------------------------- Ref guard

_SPELLED = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
    "fifteen sixteen seventeen eighteen nineteen twenty".split())}
_SPELLED.update({"thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
                 "eighty": 80, "ninety": 90, "hundred": 100, "thousand": 1000})
_NUM = re.compile(r"(?<![\w.])([-+−]?)(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|\.\d+)(%?)")
_WORDNUM = re.compile(r"\b(" + "|".join(_SPELLED) + r")\b", re.IGNORECASE)

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
    r"supports?|verified|validated|wins?|loses?|right|wrong)\b", re.IGNORECASE)


def _numbers(text: str) -> list[tuple[str, Decimal]]:
    out = []
    for sign, digits, _pct in _NUM.findall(text):
        try:
            d = Decimal(digits.replace(",", ""))
        except InvalidOperation:
            continue
        out.append(("-" if sign in "-−" and sign else "+", d))
    for w in _WORDNUM.findall(text):
        out.append(("+", Decimal(_SPELLED[w.lower()])))
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


def ref_brief(facts: dict) -> dict:
    """The compact subset sent to the LLM for phrasing (fewer prompt and reasoning tokens).
    The guard still checks against the full ``facts``."""
    return {"claim": facts["statement"], "verdict": facts["decision"], "reason": facts["reason"],
            "field_goal_attempts": facts["data"]["n_attempts"], "games": facts["data"]["n_games"]}


def allowed_numbers(facts: dict) -> set[tuple[str, Decimal]]:
    out: set[tuple[str, Decimal]] = set()
    for v in _walk(facts):
        if isinstance(v, bool) or v is None:
            continue
        if isinstance(v, (int, float)):
            d = Decimal(repr(v))
            out.add(("-" if d < 0 else "+", abs(d)))
        elif isinstance(v, str):
            out.update(_numbers(v))
    return out


def number_violations(text: str, facts: dict) -> list[str]:
    allowed = allowed_numbers(facts)
    bad = []
    for sign, d in _numbers(text):
        if (sign, d) not in allowed:
            bad.append(("-" if sign == "-" else "") + str(d))
    return bad


def ref_guard(text: str, facts: dict) -> list[str]:
    """Problems with the Ref's text; empty means it may be shown. Deterministic and pure."""
    problems = [f"number {n} is not in the evidence record" for n in number_violations(text, facts)]
    decision = facts["decision"]
    if not re.search(DECISION_PHRASES[decision], text, re.IGNORECASE):
        problems.append(f"verdict {decision} is not stated")
    for other, pat in DECISION_PHRASES.items():
        if other != decision and re.search(pat, text, re.IGNORECASE):
            problems.append(f"verdict word for {other} contradicts the record ({decision})")
    record_text = " ".join(str(v) for v in _walk(facts) if isinstance(v, str)).lower()
    for m in OVERCLAIM.finditer(text):
        if m.group(0).lower() not in record_text:
            problems.append(f"verdict word {m.group(0)!r} is not in the evidence record")
    return problems


PLAIN = {"SURVIVED_PROTOCOL": "Survived the registered checks (SURVIVED_PROTOCOL)",
         "NOT_SUPPORTED": "Not supported by the registered checks (NOT_SUPPORTED)",
         "INSUFFICIENT_EVIDENCE": "Insufficient evidence (INSUFFICIENT_EVIDENCE)",
         "DATA_INVALID": "Data invalid (DATA_INVALID)",
         "BLOCKED": "Blocked: the test could not run (BLOCKED)"}


def ref_template(facts: dict) -> str:
    return (f"{PLAIN[facts['decision']]}. Claim {facts['claim_id']}: {facts['statement']} "
            f"Reason: {facts['reason']}.")


NO_TEST_REF = ("No registered test exists for this question, so nothing was run and there is no "
               "verdict. Registered claims: {ids}.")

REF_SYSTEM = (
    "You are the Ref, a calm, exact referee. Restate the evidence record's verdict for a fan in "
    "two or three plain sentences. Use the verdict wording '{phrase}'. Copy any number exactly "
    "as written in the record and use no other numbers. Do not say proven, confirmed, myth, "
    "real, fake or significant. Do not add facts that are not in the record."
)

# --------------------------------------------------------------------------- Heater

HEATER_SYSTEM = (
    "You are Heater, an original character: a loud, theatrical sports-debate pundit on a "
    "basketball statistics show. You are fictional. Never name, quote, imitate or allude to any "
    "real commentator, broadcaster, host or media personality, and do not use their catchphrases. "
    "Speak in at most three short sentences, with big energy and the odd ALL-CAPS burst. You are "
    "entertainment, not evidence: never state statistics or numbers, and never contradict or "
    "pre-empt the Ref's verdict. If the Ref says no registered test exists, you may give a hot "
    "take, but say plainly that it is just your opinion."
)

HEATER_FALLBACK = {
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
}


# --------------------------------------------------------------------------- turn


@dataclass
class Dialogue:
    view: ShotView | None
    ledger: EvidenceLedger
    llm: MetaChat | None  # None: deterministic only
    view_identity: dict | None = None

    def turn(self, question: str) -> dict[str, Any]:
        sources: dict[str, str] = {}
        claim_id, sources["mapping"], map_identity = self._map(question)
        if claim_id == NONE:
            ref_text = NO_TEST_REF.format(ids=", ".join(c["claim_id"] for c in catalogue()))
            heater_text, sources["heater"] = self._heater(question, None, None, None)
            sources["ref"] = "TEMPLATE_NO_REGISTERED_TEST"
            return {"heater_text": heater_text, "ref_text": ref_text, "evidence_record_id": None,
                    "verdict": None, "claim_id": NONE, "sources": sources, "referee_view": None}
        challenger = LLMChallenger(self.llm) if self.llm else DeterministicChallenger()
        entry = run_once(self.view, self.ledger, view_identity=self.view_identity,
                         jone=MappedDiscoverer(claim_id, question, map_identity),
                         challenger=challenger)
        sources["challenger"] = challenger.identity.get("kind", "DETERMINISTIC_STANDIN") + (
            f" (fallback: {challenger.fallback_reason})"
            if getattr(challenger, "fallback_reason", None) else "")
        facts = ref_facts(entry)
        with cf.ThreadPoolExecutor(max_workers=2) as pool:
            h = pool.submit(self._heater, question, claim_id, facts["decision"], facts)
            r = pool.submit(self._ref, facts)
            heater_text, sources["heater"] = h.result()
            ref_text, sources["ref"] = r.result()
        return {"heater_text": heater_text, "ref_text": ref_text,
                "evidence_record_id": entry["evidence_id"], "verdict": facts["decision"],
                "claim_id": claim_id, "sources": sources, "referee_view": referee_view(entry)}

    # -- pieces

    def _map(self, question: str) -> tuple[str, str, dict]:
        if self.llm:
            messages = [{"role": "system", "content": MAP_SYSTEM.format(catalogue=json.dumps(
                [{"claim_id": c["claim_id"], "statement": c["statement"]} for c in catalogue()]))},
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

    def _heater(self, question, claim_id, decision, facts) -> tuple[str, str]:
        fallback = HEATER_FALLBACK[decision]
        if not self.llm:
            return fallback, "TEMPLATE"
        ctx = {"fan_question": question,
               "registered_claim": CLAIMS[claim_id].statement if claim_id else None,
               "refs_verdict": PLAIN[decision] if decision else "No registered test exists; nothing was run."}
        messages = [{"role": "system", "content": HEATER_SYSTEM},
                    {"role": "user", "content": json.dumps(ctx)}]
        try:
            text = self.llm.complete("heater", messages, stream=True).text.strip()
        except LLMUnavailable as e:
            return fallback, f"TEMPLATE (fallback: {e.reason[:120]})"
        bad = number_violations(text, facts or {})
        if bad:
            return fallback, f"TEMPLATE (guard rejected numbers {bad})"
        return text, "LLM"

    def _ref(self, facts: dict) -> tuple[str, str]:
        template = ref_template(facts)
        if not self.llm:
            return template, "TEMPLATE"
        phrase = PLAIN[facts["decision"]].split(" (")[0].lower()
        messages = [{"role": "system", "content": REF_SYSTEM.format(phrase=phrase)},
                    {"role": "user", "content": json.dumps(ref_brief(facts))}]
        try:
            text = self.llm.complete("ref", messages).text.strip()
        except LLMUnavailable as e:
            return template, f"TEMPLATE (fallback: {e.reason[:120]})"
        problems = ref_guard(text, facts)
        if problems:
            return template, f"TEMPLATE (guard rejected: {'; '.join(problems)[:200]})"
        return text, "LLM"
