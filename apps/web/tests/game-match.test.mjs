// Main-screen routing (Experience, 8 Nov 2026): a typed question naming tonight's teams. Mocks only.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import { NBA_TEAMS, matchGame, namesAnyTeam, teamParts, teamsIn, tonightList, whichGameLine } from "../web/market/game-match.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const JS = readFileSync(join(HERE, "..", "web", "demo.js"), "utf8");

// MOCK rows in Max's live-forecast shape (the user's example games)
const ROWS = [
  { game_id: "g1", away_team: "Philadelphia 76ers", home_team: "Chicago Bulls" },
  { game_id: "g2", away_team: "Los Angeles Lakers", home_team: "Detroit Pistons" },
  { game_id: "g3", away_team: "Utah Jazz", home_team: "Minnesota Timberwolves" },
];

test("team parts: city and nickname from the full name", () => {
  assert.deepEqual(teamParts("Philadelphia 76ers"), { full: "Philadelphia 76ers", city: "Philadelphia", nickname: "76ers" });
  assert.deepEqual(teamParts("Portland Trail Blazers"), { full: "Portland Trail Blazers", city: "Portland", nickname: "Trail Blazers" });
  assert.deepEqual(teamParts("Oklahoma City Thunder"), { full: "Oklahoma City Thunder", city: "Oklahoma City", nickname: "Thunder" });
  assert.equal(NBA_TEAMS.length, 30);
  assert.equal(new Set(NBA_TEAMS.map((n) => teamParts(n).nickname)).size, 30, "nicknames are unique");
});

test("exactly one of tonight's games: that game, by full name, city or nickname, any case", () => {
  for (const q of ["any edge in 76ers vs Bulls tonight", "any edge with tonight's 76ers vs Bulls", "ANY EDGE IN 76ERS?",
    "what about chicago", "Philadelphia at Chicago", "Chicago Bulls tonight", "bulls"]) {
    assert.deepEqual(matchGame(q, ROWS), { kind: "GAME", gameId: "g1", teams: teamsIn(q, [...ROWS.flatMap((r) => [r.home_team, r.away_team]), ...NBA_TEAMS]) }, q);
  }
  assert.equal(matchGame("Jazz or Timberwolves?", ROWS).gameId, "g3", "both teams of one game");
});

test("two games, or a team not playing tonight: Heater asks which game, built from the list", () => {
  const text = "Which game? Tonight: 76ers at Bulls, Lakers at Pistons, Jazz at Timberwolves.";
  assert.equal(whichGameLine(ROWS), text);
  assert.equal(tonightList(ROWS), "76ers at Bulls, Lakers at Pistons, Jazz at Timberwolves");
  for (const q of ["Bulls or Lakers?", "76ers vs Pistons", "how about the Celtics", "Knicks tonight?", "Bulls and the Knicks"]) {
    const m = matchGame(q, ROWS);
    assert.equal(m.kind, "WHICH", q);
    assert.equal(m.text, text, q);
  }
  assert.equal(whichGameLine([]), "Which game? There are no games on tonight's list.");
});

test("no team named: the claim path (NONE); the product's words are not teams", () => {
  for (const q of ["Is the hot hand real?", "Do home teams win more?", "Does rest matter?", "heat check this",
    "Run a heat-check on momentum", "Is Heater right?", "a magical night", "netsuke", ""]) {
    assert.equal(matchGame(q, ROWS).kind, "NONE", q);
    assert.equal(namesAnyTeam(q), false, q);
  }
  assert.equal(matchGame("the Heat tonight", ROWS).kind, "WHICH", "Miami named, not playing tonight");
});

test("one team however it is spelled: LA Clippers in the fixed list, Los Angeles Clippers tonight", () => {
  const rows = [{ game_id: "c", away_team: "Los Angeles Clippers", home_team: "Phoenix Suns" }];
  assert.equal(matchGame("Clippers tonight", rows).gameId, "c");
  assert.equal(matchGame("Suns", rows).gameId, "c");
});

test("demo.js: the game check runs before the router and the claim path, inside busyTurn", () => {
  const i = JS.indexOf("async function askTurn(");
  const src = JS.slice(i, JS.indexOf("\n}\n", i));
  assert.ok(src.indexOf("if (await gameTurn(question)) return;") >= 0);
  assert.ok(src.indexOf("if (await gameTurn(question)) return;") < src.indexOf("routeMessage(question)"));
  const j = JS.indexOf("async function gameTurn(");
  const g = JS.slice(j, JS.indexOf("\n}\n", j));
  assert.match(g, /await marketTurn\(g, \{ asked: question \}\);/, "the card's own turn, on the stage");
  assert.match(g, /if \(m\.kind === "WHICH"\) \{[\s\S]*?await showHeaterLine\(m\.text\);/);
  assert.doesNotMatch(g, /openBoard|setView\("board"\)/, "no navigation to the board");
  assert.match(JS, /async function marketTurn\(g, \{ asked: typed = "" \} = \{\}\) \{\s*setView\("talk"\);/);
});
