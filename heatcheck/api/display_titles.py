"""Display titles for claim ids: presentation only.

These short titles are shown to fans (dialogue responses, the console page, Experience's UI
via GET /api/display-titles). They are NOT registry text: they never enter a plan, a plan
hash, an evidence identity or an evidence id. The registered statement stays the record of
what was tested; a title may be edited freely without changing any evidence.
"""

from __future__ import annotations

DISPLAY_TITLES: dict[str, str] = {
    "HH-K3": "Hot hand: three makes in a row",
    "HH-K2": "Hot hand: two makes in a row",
    "GP-REST": "Rest and back-to-backs on top of Elo",
    "GP-ELO": "Elo vs the home-win base rate",
    "CONF-HA": "Home advantage (2024-25, confirmatory)",
    "CONF-MOM": "One-shot momentum (2024-25, confirmatory)",
    "CONF-HH": "Hot hand: three in a row (2024-25, confirmatory)",
    "NONE": "No registered test",
}


def display_title(claim_id: str | None) -> str:
    """Title for display; an unknown id is shown as itself, never invented."""
    if claim_id is None:
        return DISPLAY_TITLES["NONE"]
    return DISPLAY_TITLES.get(claim_id, claim_id)
