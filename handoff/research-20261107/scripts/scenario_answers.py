"""Write heatcheck-scenario/1 answers for both teams of every game in a heatcheck-live-forecast/1 file.

Usage: python -I scripts/scenario_answers.py <forecasts.json> <player_absence_effects.json> <schedule_effects.json> <out.json>

Max's /api/scenario can serve these directly, or call heatcheck.scenario.scenario_api_answer() with the card's own
team and baseline string. The baseline is the forecast exactly: p_home_win for the home team, 1 - p_home_win
(decimal arithmetic) for the away team.
"""
import json
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from heatcheck import scenario as SC  # noqa: E402
from heatcheck.util import sha256_file  # noqa: E402


def main(fc_path: Path, abs_path: Path, sch_path: Path, out: Path):
    fc = json.loads(fc_path.read_text())
    absence = json.loads(abs_path.read_text())["effects"]
    schedule = json.loads(sch_path.read_text())["effects"]
    fc_sha = sha256_file(fc_path)
    source = (f"Research scenario estimates (Elo residuals, 2023-24 to 2025-26): {abs_path.name} sha256 "
              f"{sha256_file(abs_path)[:16]}, {sch_path.name} sha256 {sha256_file(sch_path)[:16]}")
    answers = {}
    for g in fc["games"]:
        ph = Decimal(repr(g["p_home_win"]))
        for side, tid, name, base in (("home", g["home_team_id"], g["home_team"], ph),
                                      ("away", g["away_team_id"], g["away_team"], Decimal(1) - ph)):
            answers.setdefault(g["game_id"], {})[tid] = SC.scenario_api_answer(
                g, tid, name, str(base), f"forecasts.json sha256 {fc_sha[:16]}", absence, schedule, source=source)
    doc = {"format_of_each_answer": SC.SCENARIO_FORMAT, "label": "ESTIMATE",
           "forecasts_sha256": fc_sha, "answers": answers}
    out.write_text(json.dumps(doc, indent=1) + "\n", newline="\n")
    n = sum(len(a["scenarios"]) for t in answers.values() for a in t.values())
    print(json.dumps({"games": len(answers), "answers": sum(len(t) for t in answers.values()), "scenarios": n}))


if __name__ == "__main__":
    main(*map(Path, sys.argv[1:5]))
