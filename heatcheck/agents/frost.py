"""Frost: the visible challenger. Every question Frost asks names a check that actually
ran (or a recorded fact of the run); every result chip is a template filled only from
ref_facts()/recorded_facts(). The model may rephrase Frost's QUESTION only, under the
same number guard as Heater. Frost never decides anything."""
from __future__ import annotations

import re
from dataclasses import dataclass

MAX_CHALLENGES = 3
KINDS = ("numbers", "basketball", "process")   # internal only; not shown in the UI


@dataclass(frozen=True)
class Challenge:
    check: str          # which real check/fact this is anchored to
    kind: str
    question: str       # Frost's default wording
    chip: str           # plain-English result, filled from facts only
    source: str         # where the chip's facts came from (attack id or record field)


def _attack(facts: dict, prefix: str) -> dict | None:
    for a in facts.get("attacks", []):
        if a["test"].startswith(prefix) and a["status"] == "EXECUTED":
            return a
    return None


def _fmt_p(p) -> str:
    return "n/a" if p is None else (f"{p:.3f}" if p >= 0.001 else "< 0.001")


def _p_text(p) -> str | None:
    """A p-value as the chip may print it: the 3-decimal form only when it equals the recorded value
    exactly (so the number guard accepts it), else the recorded value itself. Max, 8 Nov 2026."""
    if p is None:
        return None
    short = _fmt_p(p)
    try:
        from decimal import Decimal
        if Decimal(short) == Decimal(repr(p)):
            return short
    except ArithmeticError:
        pass
    return repr(p)


def candidates(facts: dict) -> list[Challenge]:
    """All challenges that are ANCHORED for this record, in priority order.

    Chip fixes (Max, 8 Nov 2026, from the tightened number test): numbers are printed exactly as
    recorded; wording that the guard reads as a number ("This one", "zero") or a fraction ("half",
    "twice") is avoided; a statement the record does not support is dropped."""
    out: list[Challenge] = []
    cid = facts["claim_id"]
    data = facts.get("data") or {}
    res = facts.get("result") or {}
    params = facts.get("params") or {}
    reason = str(facts.get("reason") or "")

    # ---- live agent-loop entries (shot claims): one challenge per executed attack
    a = _attack(facts, "A-PERMUTATION-NULL")
    alpha = params.get("alpha")
    if a and a.get("p_value") is not None and alpha is not None:
        out.append(Challenge("A-PERMUTATION-NULL", "numbers",
            "Streaks happen by chance. If nobody had a hot hand at all, how streaky would shooting look?",
            f"Shuffled every player's shots within each game. Real shooting was "
            f"{'no streakier than' if a['p_value'] >= alpha else 'streakier than'} the shuffles "
            f"(p = {_p_text(a['p_value'])}, alpha {_p_text(alpha)}).", "A-PERMUTATION-NULL"))
    a = _attack(facts, "A-SHOT-VALUE-SELECTION")
    gap = params.get("max_shot_value_share_gap")
    if a and a.get("statistic") is not None and gap is not None:
        flagged = abs(a["statistic"]) > gap
        out.append(Challenge("A-SHOT-VALUE-SELECTION", "basketball",
            "Hot shooters take harder shots. Fewer makes after a streak could be confidence, not cold hands.",
            "Checked whether players took more 3-pointers after streaks: "
            + ("they did, so part of any drop is shot choice." if flagged else "no shift beyond the limit.")
            + f" ({a['reason']})", "A-SHOT-VALUE-SELECTION"))
    a = _attack(facts, "A-SPLIT-HALF-REPLICATION")
    if a:
        out.append(Challenge("A-SPLIT-HALF-REPLICATION", "process",
            "Show me it again. Does it hold in two separate slices of the data, or only one?",
            f"Even and odd groups tested separately: {a['reason']}", "A-SPLIT-HALF-REPLICATION"))
    a = _attack(facts, "A-SAMPLE-SIZE")
    if a and data.get("n_attempts") is not None:
        out.append(Challenge("A-SAMPLE-SIZE", "numbers",
            "How many shots are we talking? A few good nights isn't evidence.",
            f"{data.get('n_attempts')} shots in the sample. {a['reason']}", "A-SAMPLE-SIZE"))

    # ---- recorded / sealed results
    n_seen = data.get("n_games") or data.get("n_attempts")
    if facts.get("lane") == "CONFIRMATORY" and data.get("season") and n_seen:
        out.append(Challenge("sealed_season", "process",
            "Did anyone look at this season before the test was written?",
            f"The whole {data.get('season')} season was sealed before any test ran; the test ran "
            f"once, on {n_seen} {'games' if data.get('n_games') else 'shots'} the system had never seen.",
            "custodian seal"))
    if res.get("p_holm") is not None:
        low = reason.lower()
        p = _p_text(res["p_holm"])
        if "not rejected at holm" in low:
            outcome = f" It didn't clear it (p = {p})."
        elif "holm p<" in low and facts["decision"] == "SURVIVED_PROTOCOL":
            # the record's own readable form ("Holm p<0.05") when the exact value is long
            m = re.search(r"holm p<\s*[0-9.]+", reason, re.IGNORECASE)
            outcome = (f" It still passed (p = {p})." if len(p) <= 6 or not m
                       else f" It still passed ({m.group(0)}).")
        else:   # the verdict turned on something else (e.g. the interval): say nothing about clearing
            outcome = ""
        out.append(Challenge("multiplicity", "numbers",
            "You tested several ideas at once. Any of them could pass by luck. Did you raise the bar for that?",
            "Yes, the bar was raised for testing the ideas together." + outcome, "result.p_holm"))
    if cid in ("CONF-HH", "CONF-MOM", "HH-K3", "HH-K2") and facts["decision"] == "INSUFFICIENT_EVIDENCE":
        out.append(Challenge("no_equivalence_test", "process",
            "Same rate after makes and misses. That's not 'no hot hand', that's 'couldn't find one'. Which is it?",
            "Couldn't find one. The test can only say 'not shown'; nobody registered a test for "
            "'no effect exists'.", "decision rule"))
    ci = res.get("ci95") or res.get("ci")
    if ci and facts["decision"] == "INSUFFICIENT_EVIDENCE" and "both sides" in reason.lower():
        out.append(Challenge("ci_rule", "process",
            "The adjusted p-value looks small. Why isn't that a yes?",
            "The rule written before the test needed the whole plausible range clear of the line. "
            "The recorded range includes values on both sides of the decision thresholds, and the Ref "
            "doesn't round.", "result.ci95"))
    if cid == "GP-REST":   # the claim itself is "over Elo" (not true of GP-ELO, which is vs the base rate)
        out.append(Challenge("elo_baseline", "basketball",
            "Is this just the better team winning, not rest?",
            "Compared against the Elo rating's own forecast, so team strength was already counted.",
            "claim statement: rest on top of Elo"))
    return out


def select(facts: dict, limit: int = MAX_CHALLENGES) -> list[Challenge]:
    """Up to `limit` challenges, at most one per kind while kinds remain, priority order."""
    chosen: list[Challenge] = []
    used: set[str] = set()
    pool = candidates(facts)
    for c in pool:                       # first pass: one per kind
        if c.kind not in used and len(chosen) < limit:
            chosen.append(c)
            used.add(c.kind)
    for c in pool:                       # second pass: fill remaining slots
        if c not in chosen and len(chosen) < limit:
            chosen.append(c)
    return chosen


FROST_REACTION = {
    "SURVIVED_PROTOCOL": "Fair. I'll allow it.",
    "NOT_SUPPORTED": "Told you. Not shown.",
    "INSUFFICIENT_EVIDENCE": "Not shown. That's not the same as wrong, Heater.",
    "DATA_INVALID": "The data failed its own checks. No ruling.",
    "BLOCKED": "No test, no ruling. Those are the rules.",
    None: "Nobody knows yet. Including you.",
}

FROST_SYSTEM = (
    "You are Frost, a calm, dry, British sceptic who challenges a loud sports pundit called Heater. "
    "Rephrase the given question in your own voice in ONE short sentence, keeping its meaning exactly. "
    "Never state any number, statistic, verdict, test result or evidence. Never suggest betting."
)


def to_payload(challenges: list[Challenge], phrased: dict[str, str] | None = None) -> list[dict]:
    """What the API returns: question (template or guarded model phrasing), chip, source."""
    return [{"check": c.check, "question": (phrased or {}).get(c.check, c.question),
             "chip": c.chip, "source": c.source} for c in challenges]
