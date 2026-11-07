"""Event mapping between a canonical NBA game forecast and a venue contract (Research §10, G10).
Title similarity is never sufficient; every field must be declared by the contract metadata."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ForecastTarget:
    game_id: str
    game_date_et: str
    home_tricode: str
    away_tricode: str
    team_tricode: str              # team whose win probability is shown
    includes_overtime: bool = True


@dataclass(frozen=True)
class ContractSpec:
    venue: str
    market_id: str
    league: str | None
    game_date_et: str | None
    teams: frozenset | None        # tricodes declared by rules/metadata
    yes_team: str | None           # team that YES / selected outcome pays on
    includes_overtime: bool | None
    postponement_rule: str | None  # e.g. "VOID", "ROLL_TO_RESCHEDULED", None=unknown
    rules_hash: str | None


@dataclass(frozen=True)
class Mapping:
    status: str                    # MATCHED | AMBIGUOUS | INCOMPATIBLE
    outcome_direction: str | None  # "SAME" (contract YES == forecast team) | None
    reasons: tuple[str, ...]


def map_contract(t: ForecastTarget, c: ContractSpec) -> Mapping:
    incompatible, unknown = [], []
    if c.league is None: unknown.append("LEAGUE_UNKNOWN")
    elif c.league != "NBA": incompatible.append(f"LEAGUE_{c.league}")
    if c.teams is None: unknown.append("TEAMS_UNKNOWN")
    elif c.teams != frozenset({t.home_tricode, t.away_tricode}): incompatible.append("TEAMS_DIFFER")
    if c.game_date_et is None: unknown.append("DATE_UNKNOWN")
    elif c.game_date_et != t.game_date_et: incompatible.append("DIFFERENT_GAME_DATE")
    if c.yes_team is None: unknown.append("OUTCOME_SEMANTICS_UNKNOWN")
    elif c.yes_team not in {t.home_tricode, t.away_tricode}: incompatible.append("OUTCOME_TEAM_NOT_IN_GAME")
    elif c.yes_team != t.team_tricode: incompatible.append("REVERSED_OUTCOME")
    if c.includes_overtime is None: unknown.append("OVERTIME_RULE_UNKNOWN")
    elif c.includes_overtime != t.includes_overtime: incompatible.append("OVERTIME_MISMATCH")
    if c.postponement_rule is None: unknown.append("POSTPONEMENT_RULE_UNKNOWN")
    if c.rules_hash is None: unknown.append("RULES_NOT_HASHED")
    if incompatible:
        return Mapping("INCOMPATIBLE", None, tuple(incompatible + unknown))
    if unknown:
        return Mapping("AMBIGUOUS", None, tuple(unknown))
    return Mapping("MATCHED", "SAME", ())
