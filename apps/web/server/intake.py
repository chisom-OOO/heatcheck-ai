"""Natural-language claim intake.

Rule-based proposer: it NEVER picks a definition silently. Every field is either
filled from a quoted source span or listed as an unresolved question.
Supported literal commands are parsed first.
"""
import re

COMMANDS = {
    "challenge this claim": "challenge",
    "attach evidence": "attach_evidence",
    "show why rejected": "show_rejected",
    "compare a game forecast": "compare_forecast",
    "compare an nba market": "compare_market",
    "stop": "stop",
    "export": "export",
}

STAT_PATTERNS = [
    ("clutch", r"\bclutch\b", "SHOT_ASSOCIATION"),
    ("hot_hand", r"\b(hot hand|hot streak|heat check|after (?:\d+|two|three|four) makes?)\b", "SHOT_ASSOCIATION"),
    ("home_court", r"\bhome[- ]court\b|\bhome advantage\b", "GAME_PREDICTION"),
    ("rest", r"\b(back[- ]to[- ]back|rest days?|rested)\b", "GAME_PREDICTION"),
    ("game_win", r"\b(will|to) win\b|\bwin probability\b", "GAME_PREDICTION"),
]

NUM_WORDS = {"two": 2, "three": 3, "four": 4, "five": 5}


def parse_command(text):
    t = text.strip().lower().rstrip(".!")
    return COMMANDS.get(t)


def interpret(text):
    """Return a proposed interpretation. Free text is data, never instructions."""
    text = (text or "").strip()
    if not text:
        return {"status": "EMPTY", "unresolved": ["Enter or say a claim."], "fields": {}}
    if len(text) > 2000:
        return {"status": "REJECTED", "unresolved": ["Claim is longer than 2000 characters."], "fields": {}}
    cmd = parse_command(text)
    if cmd:
        return {"status": "COMMAND", "command": cmd, "fields": {}, "unresolved": []}

    low = text.lower()
    fields, spans, unresolved = {}, {}, []

    kind = channel = None
    for k, pat, ch in STAT_PATTERNS:
        m = re.search(pat, low)
        if m:
            kind, channel = k, ch
            spans["statistic"] = [m.start(), m.end()]
            break
    if kind is None:
        return {
            "status": "UNSUPPORTED",
            "fields": {},
            "unresolved": ["No supported claim type recognised (clutch, hot hand, home court, rest, game win)."],
            "source_text": text,
        }
    fields["kind"] = kind
    fields["channel"] = channel

    # subject
    m = re.match(r"\s*([A-Z][\w.'-]*(?:\s+[A-Z][\w.'-]*){0,2})\s+(?:is|are|has|have|shoots?|plays?)\b", text)
    if m and m.group(1).lower() not in {"the", "players", "teams"}:
        fields["population"] = {"type": "named_player", "label": m.group(1)}
        spans["population"] = [m.start(1), m.end(1)]
    elif re.search(r"\b(players|shooters|teams|nba)\b", low):
        mm = re.search(r"\b(players|shooters|teams|nba)\b", low)
        fields["population"] = {"type": "group", "label": mm.group(1)}
        spans["population"] = [mm.start(), mm.end()]
    else:
        unresolved.append("Population: which player, group or teams?")

    # kind specific definition questions
    if kind == "clutch":
        mw = re.search(r"(\d+)\s*(?:min|minutes)", low)
        mm = re.search(r"(?:within|margin|by)\s*(\d+)\s*(?:points?|pts)", low)
        if mw:
            fields["window_minutes"] = int(mw.group(1))
            spans["window"] = [mw.start(), mw.end()]
        else:
            unresolved.append("Time window: last 2 or 5 minutes, or another value? (not chosen for you)")
        if mm:
            fields["margin_points"] = int(mm.group(1))
            spans["margin"] = [mm.start(), mm.end()]
        else:
            unresolved.append("Score margin: within 3, within 5, or another value?")
        unresolved.append("Comparator: the same player's non-clutch shooting, or the league baseline?")
        unresolved.append("Statistic: FG%, eFG% or TS%?")
    elif kind == "hot_hand":
        mk = re.search(r"after\s+(\d+|two|three|four|five)\s+makes?", low)
        if mk:
            v = mk.group(1)
            fields["streak_length"] = int(v) if v.isdigit() else NUM_WORDS[v]
            spans["streak"] = [mk.start(), mk.end()]
        else:
            unresolved.append("Streak length: 2, 3 or 4 consecutive makes?")
        unresolved.append("Setting: free throws only, field goals, or both?")
        unresolved.append("Comparator: shrunk talent baseline or shot-difficulty-adjusted expectation?")
    elif kind in ("home_court", "rest", "game_win"):
        unresolved.append("Target: team-win probability for a named scheduled game and cutoff time.")
        unresolved.append("Seasons / data scope for the retrospective test.")
        if kind == "game_win" and "game" not in fields:
            unresolved.append("Which scheduled game (teams and tip date)?")

    for _label, ptn in (("Direction", r"\b(better|higher|more|improve|increase|worse|lower|less|decline)\b"),):
        m = re.search(ptn, low)
        if m:
            fields["direction"] = "positive" if m.group(1) in {"better", "higher", "more", "improve", "increase"} else "negative"
            spans["direction"] = [m.start(), m.end()]
        else:
            fields["direction"] = None
            unresolved.append("Direction: positive, negative or two-sided?")

    status = "NEEDS_CLARIFICATION" if unresolved else "REVIEWABLE"
    return {
        "status": status,
        "fields": fields,
        "source_spans": spans,
        "unresolved": unresolved,
        "source_text": text,
        "note": "Proposal only. Nothing runs until every field is approved and the exact plan is confirmed.",
    }
