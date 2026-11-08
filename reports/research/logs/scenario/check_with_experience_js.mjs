import { readFileSync } from "node:fs";
import { readScenarios, scenarioView } from "./scenario-model.js";
const doc = JSON.parse(readFileSync(process.argv[2], "utf8"));
let ok = 0, refused = 0, unavailable = 0, total = 0;
for (const [gid, byTeam] of Object.entries(doc.answers)) {
  for (const [tid, ans] of Object.entries(byTeam)) {
    const card = { team: ans.team, forecast: { p_team_win: ans.baseline.p_team_win }, is_sample: false };
    const r = readScenarios({ status: 200, body: ans }, { gameId: gid, resp: card });
    if (r.status !== "OK") { unavailable++; console.log("UNAVAILABLE", gid, tid, r.reason); continue; }
    total += ans.scenarios.length; ok += r.scenarios.length; refused += r.refused.length;
    for (const x of r.refused) console.log("REFUSED", gid, tid, x.text, "->", x.reason);
    for (const s of r.scenarios) scenarioView(s, r);   // must not throw
  }
}
console.log(JSON.stringify({ answers_unavailable: unavailable, scenarios_total: total, shown: ok, refused }));
