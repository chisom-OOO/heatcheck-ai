// Which of tonight's games a typed question is about (Experience, 8 Nov 2026; UI only, no API).
// A question naming a team is about a game: exactly one of tonight's games -> that game's card
// exchange on the stage; two or more, or a team that is not playing tonight -> Heater asks which
// game; no team -> the normal claim path. Names come from the loaded forecast's own team names
// (full name, city, nickname); the fixed list of the 30 NBA teams is used only to notice a team
// that is not playing tonight. No other aliases ("Sixers", "Cavs", ...) are added.

/** The 30 NBA teams, full names as Max's forecast spells them. */
export const NBA_TEAMS = [
  "Atlanta Hawks", "Boston Celtics", "Brooklyn Nets", "Charlotte Hornets", "Chicago Bulls",
  "Cleveland Cavaliers", "Dallas Mavericks", "Denver Nuggets", "Detroit Pistons", "Golden State Warriors",
  "Houston Rockets", "Indiana Pacers", "LA Clippers", "Los Angeles Lakers", "Memphis Grizzlies",
  "Miami Heat", "Milwaukee Bucks", "Minnesota Timberwolves", "New Orleans Pelicans", "New York Knicks",
  "Oklahoma City Thunder", "Orlando Magic", "Philadelphia 76ers", "Phoenix Suns", "Portland Trail Blazers",
  "Sacramento Kings", "San Antonio Spurs", "Toronto Raptors", "Utah Jazz", "Washington Wizards",
];

const TWO_WORD_NICKNAMES = ["Trail Blazers"];

/** {full, city, nickname} from a full team name ("Portland Trail Blazers" -> Portland / Trail Blazers). */
export function teamParts(full) {
  const name = String(full || "").trim().replace(/\s+/g, " ");
  const two = TWO_WORD_NICKNAMES.find((n) => name.endsWith(` ${n}`));
  const nickname = two || name.split(" ").pop();
  const city = name.slice(0, name.length - nickname.length).trim();
  return { full: name, city, nickname };
}

const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
/** "heat" in "heat check" is the product, not Miami. */
const AFTER = { heat: "(?!\\s*-?\\s*check)" };

/** True when ``term`` appears in ``text`` as whole words, case-insensitive. */
function mentions(text, term) {
  if (!term) return false;
  const tail = AFTER[term.toLowerCase()] || "";
  return new RegExp(`(?:^|[^\\p{L}\\p{N}])${esc(term)}(?![\\p{L}\\p{N}])${tail}`, "iu").test(text);
}

/** The terms that name one team: full name, city, nickname. */
const termsFor = (full) => {
  const p = teamParts(full);
  return [p.full, p.city, p.nickname].filter(Boolean);
};

/** Teams named in ``text``, each once, from ``names`` (full names). A city shared by two teams
 *  (Los Angeles) names both. */
export function teamsIn(text, names) {
  const t = String(text || "");
  return [...new Set(names)].filter((n) => termsFor(n).some((term) => mentions(t, term)));
}

/** "76ers at Bulls, Lakers at Pistons": tonight's games by nickname, away at home. */
export function tonightList(rows) {
  return (rows || []).map((r) => `${teamParts(r.away_team).nickname} at ${teamParts(r.home_team).nickname}`).join(", ");
}

/** Heater's question when the game is not clear. */
export function whichGameLine(rows) {
  const list = tonightList(rows);
  return list ? `Which game? Tonight: ${list}.` : "Which game? There are no games on tonight's list.";
}

/** What a typed question is about, given tonight's forecast rows
 *  ({game_id, home_team, away_team}):
 *  {kind: "NONE"} no team named; {kind: "GAME", gameId} exactly one of tonight's games and no
 *  other team; {kind: "WHICH", text} two or more games, or a team not playing tonight. */
export function matchGame(question, rows) {
  const games = rows || [];
  const tonight = games.flatMap((r) => [r.home_team, r.away_team]);
  const named = teamsIn(question, [...tonight, ...NBA_TEAMS]);
  if (!named.length) return { kind: "NONE" };
  // one team, however it is spelled ("LA Clippers" / "Los Angeles Clippers"): by nickname
  const nick = (n) => teamParts(n).nickname.toLowerCase();
  const namedNicks = new Set(named.map(nick));
  const tonightNicks = new Set(tonight.map(nick));
  const notTonight = [...namedNicks].filter((n) => !tonightNicks.has(n));
  const ids = [...new Set(games.filter((r) => namedNicks.has(nick(r.home_team)) || namedNicks.has(nick(r.away_team))).map((r) => r.game_id))];
  if (ids.length === 1 && !notTonight.length) return { kind: "GAME", gameId: ids[0], teams: named };
  return { kind: "WHICH", text: whichGameLine(games), teams: named, notTonight };
}

/** Whether ``question`` names any NBA team at all (cheap check before loading tonight's games). */
export const namesAnyTeam = (question) => teamsIn(question, NBA_TEAMS).length > 0;
