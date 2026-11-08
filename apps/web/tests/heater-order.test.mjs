// Run from apps/web:  node --test tests/heater-order.test.mjs
//
// Heater's first line never pre-empts the Ref (rehearsal, 8 Nov 2026). Before the Ref speaks, Heater
// may not mention the Ref or say or hint at a verdict; the verdict-aware line comes after the stamp.
//
// Max's server since e4650af: heater_text is the hot take only (the model gets the fan's question
// only; his take_mentions_ref guard rejects Ref words) and heater_reaction is the line for after the
// stamp, on /api/dialogue and /api/investigate. The page uses both, and checks the take again: a take
// that mentions the Ref or a verdict (an older server) is held back until after the stamp.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import * as H from "../web/heater/heater-model.js";
import { heaterIdeaLine } from "../web/ideas/idea-model.js";
import { marketReaction } from "../web/market/board-model.js";
import { heaterScenarioLine } from "../web/market/scenario-model.js";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const REPO = join(ROOT, "..", "..");
const read = (...p) => readFileSync(join(...p), "utf8");
const DEMO = read(ROOT, "web", "demo.js");
const PERSONALITY = JSON.parse(read(ROOT, "web", "heater", "heater_personality.json"));
const CAP = JSON.parse(read(ROOT, "tests", "fixtures", "max_api", "captures.json"));
const IDEAS = JSON.parse(read(ROOT, "tests", "fixtures", "idea_family_api.json"));
const DIALOGUE_PY = read(REPO, "heatcheck", "agents", "dialogue.py");
const MARKET_PY = read(REPO, "heatcheck", "agents", "market_investigation.py");

/** A Python string constant read from Max's source (implicitly concatenated literals joined). */
function pyString(src, name) {
  const m = new RegExp(`^${name} = \\(?([\\s\\S]*?)\\)?\\n(?=\\S)`, "m").exec(src);
  assert.ok(m, `${name} not found`);
  return joinLiterals(m[1]);
}
const joinLiterals = (block) => [...block.matchAll(/"((?:[^"\\]|\\.)*)"/g)].map((x) => x[1]).join("");
/** A Python dict of string values, keyed by None / "NAME" / NAME. */
function pyDict(src, name) {
  const block = new RegExp(`^${name} = \\{([\\s\\S]*?)^\\}`, "m").exec(src)?.[1];
  assert.ok(block, `${name} not found`);
  const out = {};
  for (const entry of block.split(/,\n(?=\s+(?:None|"[A-Z_]+"|[A-Z_]+):)/)) {
    const k = /^\s*(None|"([A-Z_]+)"|([A-Z_]+)):/.exec(entry);
    if (k) out[k[2] || k[3] || "None"] = joinLiterals(entry.slice(k[0].length));
  }
  return out;
}
const REACTION = pyDict(DIALOGUE_PY, "HEATER_REACTION");
const MARKET_REACTION = pyDict(MARKET_PY, "HEATER_REACTION");
const TAKE_FALLBACK = pyString(DIALOGUE_PY, "HEATER_TAKE_FALLBACK");
const HOME_BIAS_HEATER = pyString(MARKET_PY, "HOME_BIAS_HEATER");
const SAMPLE_HEATER = pyString(MARKET_PY, "SAMPLE_HEATER");
// What 424b47c and earlier served inside heater_text (market) and as the dialogue's opener: kept here
// as the "older server" case the page must still hold back.
const OLD_HOME_BIAS = "And the Ref's calibration note says this model has overrated home teams before, "
  + "so part of this gap could be the model's own bias, not the market's.";

/** The source of one top-level function in demo.js. */
function fnSource(name) {
  const start = DEMO.search(new RegExp(`^(async )?function ${name}\\(`, "m"));
  assert.ok(start >= 0, `demo.js has no function ${name}`);
  const rest = DEMO.slice(start + 1);
  const end = rest.search(/^(async function |function |const |let |\/\/ -{10})/m);
  return DEMO.slice(start, end < 0 ? undefined : start + 1 + end);
}

test("Max's server: the take is verdict-blind, the verdict lines are heater_reaction", () => {
  assert.ok(Object.keys(REACTION).length >= 7, `read ${Object.keys(REACTION).length} reactions`);
  for (const k of ["SURVIVED_PROTOCOL", "NOT_SUPPORTED", "INSUFFICIENT_EVIDENCE", "DATA_INVALID", "BLOCKED", "None"]) {
    assert.ok(H.preemptsRef(REACTION[k]), `${k} would pre-empt if said first: ${REACTION[k]}`);
  }
  assert.ok(!H.preemptsRef(TAKE_FALLBACK), TAKE_FALLBACK);
  assert.ok(pyString(DIALOGUE_PY, "HEATER_SYSTEM").includes("You speak BEFORE the Ref"));
  assert.ok(pyString(MARKET_PY, "HEATER_SYSTEM").includes("You speak BEFORE the Ref"));
  assert.ok(Object.keys(MARKET_REACTION).length >= 2);
});

test("every line Heater can open with is verdict-blind", () => {
  for (const [claim, line] of Object.entries(PERSONALITY.claims)) assert.ok(!H.preemptsRef(line), `${claim}: ${line}`);
  for (const id of ["HH-K3", "CONF-HA", "GP-REST", "NONE", "NOT-A-CLAIM"]) assert.ok(!H.preemptsRef(H.takeFor(id, PERSONALITY, 3)));
  for (const f of IDEAS.families) for (const r of f.results) assert.ok(!H.preemptsRef(heaterIdeaLine(r)), heaterIdeaLine(r));
  const base = { team: "Atlanta Hawks", baseline: { p_team_win: "0.60" }, isSample: false };
  for (const p of ["0.70", "0.50", "0.601"]) assert.ok(!H.preemptsRef(heaterScenarioLine({ p_team_win: p }, base)));
  assert.ok(!H.preemptsRef(heaterScenarioLine({ p_team_win: "0.7" }, { ...base, isSample: true })));
  const opener = /const MARKET_OPENER = "([^"]+)";/.exec(DEMO)[1];
  assert.ok(!H.preemptsRef(opener), opener);
  assert.ok(!H.preemptsRef(SAMPLE_HEATER), SAMPLE_HEATER);
});

test("dialogueLines: Max's take first, his reaction last; an older verdict-aware take is held back", () => {
  const fb = () => "PERSONALITY TAKE";
  // the current server: take + reaction
  assert.deepEqual(H.dialogueLines({ heater_text: TAKE_FALLBACK, heater_reaction: REACTION.SURVIVED_PROTOCOL }, fb),
    { take: TAKE_FALLBACK, takeFromApi: true, lastWord: REACTION.SURVIVED_PROTOCOL });
  // an older server: the take was the verdict line itself; it moves after the stamp
  assert.deepEqual(H.dialogueLines({ heater_text: REACTION.NOT_SUPPORTED }, fb),
    { take: "PERSONALITY TAKE", takeFromApi: false, lastWord: REACTION.NOT_SUPPORTED });
  // offline / forced record / no Heater text: the personality's take; the page then uses reactFor
  for (const api of [null, {}, { heater_text: "  " }]) {
    assert.deepEqual(H.dialogueLines(api, fb), { take: "PERSONALITY TAKE", takeFromApi: false, lastWord: "" });
  }
  // a model take that slipped past the server guard is still never said first
  const slipped = H.dialogueLines({ heater_text: "The Ref will back me up on this!", heater_reaction: "TOLD YOU." }, fb);
  assert.equal(slipped.take, "PERSONALITY TAKE");
  assert.equal(slipped.lastWord, "TOLD YOU.");
});

test("splitTake keeps every sentence, in order, and puts only the pre-empting ones after the stamp", () => {
  const template = "The model has Atlanta Hawks at 62.0% to win. That is above the market's ask of 55.0%. It only uses "
    + "elo_rating_home, elo_rating_away, home_court. Could rest, injuries or lineup news explain the gap? Those are "
    + "questions to investigate, because the model can't see them.";
  const cases = [template, `${template} ${OLD_HOME_BIAS}`, `${template} ${HOME_BIAS_HEATER}`, SAMPLE_HEATER,
    TAKE_FALLBACK, ...Object.values(REACTION), ...Object.values(MARKET_REACTION),
    ...CAP.exchanges.filter((x) => x.path === "/api/investigate" && x.body?.heater_text).map((x) => x.body.heater_text)];
  for (const text of cases) {
    const { first, later } = H.splitTake(text);
    assert.ok(!H.preemptsRef(first), `first pre-empts: ${first}`);
    const words = (s) => s.split(/\s+/).filter(Boolean);
    assert.equal(words(first).length + words(later).length, words(text).length, `nothing dropped: ${text}`);
  }
  assert.deepEqual(H.splitTake(`${template} ${OLD_HOME_BIAS}`), { first: template, later: OLD_HOME_BIAS });
  assert.deepEqual(H.splitTake(template), { first: template, later: "" });
  assert.equal(H.splitTake(REACTION.SURVIVED_PROTOCOL).first, "Heater here!");
});

test("marketReaction: Max's heater_reaction after the stamp, after any held-back sentence", () => {
  const resp = { heater_reaction: HOME_BIAS_HEATER };
  assert.equal(marketReaction({ first: "x", later: "" }, resp), HOME_BIAS_HEATER);
  assert.equal(marketReaction({ first: "x", later: OLD_HOME_BIAS }, { heater_reaction: MARKET_REACTION.VERDICT_WORTH }),
    `${OLD_HOME_BIAS} ${MARKET_REACTION.VERDICT_WORTH}`);
  assert.equal(marketReaction({ first: "x", later: "" }, { heater_reaction: "" }), "");
  assert.equal(marketReaction({ first: "x", later: "" }, {}), "", "a SAMPLE or hypothetical card has no reaction");
});

/** Positions of Heater's lines, the Ref's line and the stamp in one flow, in source order. */
function order(src) {
  const at = (re) => { const m = re.exec(src); return m ? m.index : -1; };
  return {
    firstHeater: at(/speak\(\s*([\w.]+)\s*,\s*"heater"/),
    firstHeaterArg: /speak\(\s*([\w.]+)\s*,\s*"heater"/.exec(src)?.[1],
    ref: at(/speak\(\s*[\w.]+\s*,\s*"ref"/),
    stamp: at(/ui\.stamp\.hidden = false/),
    heaterAfter: [...src.matchAll(/speak\(\s*([\w.]+)\s*,\s*"heater"/g)].slice(1).map((m) => [m.index, m[1]]),
  };
}

test("demo.js, every Ref flow: Heater's opener, then the Ref, then the stamp, then the reaction", () => {
  // each flow's turn (busyTurn wraps it: ask -> askTurn, askIdea -> ideaTurn, askScenario ->
  // scenarioCardTurn, askMarket -> marketTurn)
  for (const name of ["askTurn", "ideaTurn", "scenarioCardTurn", "marketTurn"]) {
    const o = order(fnSource(name));
    assert.ok(o.firstHeater >= 0 && o.firstHeater < o.ref && o.ref < o.stamp, `${name}: opener < Ref < stamp`);
    for (const [i, arg] of o.heaterAfter) assert.ok(i > o.stamp, `${name}: Heater's ${arg} is said only after the stamp`);
  }
  const ask = fnSource("askTurn");
  assert.equal(order(ask).firstHeaterArg, "a.take");
  assert.deepEqual(order(ask).heaterAfter.map(([, a]) => a), ["react"]);
  assert.ok(/const react = a\.lastWord \|\| /.test(ask), "Max's reaction is the last word, else reactFor");
  const answer = fnSource("answer");
  assert.ok(/dialogueLines\(forced \? null : api, \(\) => takeFor\(claimId, state\.personality, state\.turn\)\)/.test(answer));
  assert.ok(!/take = [^\n]*heater_text/.test(answer), "the API's text is used only through dialogueLines");
  const market = fnSource("marketTurn");
  assert.equal(order(market).firstHeaterArg, "take");
  assert.ok(/const take = split\.first \|\| MARKET_OPENER;/.test(market));
  assert.ok(/const reaction = marketReaction\(split, resp\);/.test(market));
  assert.deepEqual(order(market).heaterAfter.map(([, a]) => a), ["reaction"]);
  for (const name of ["askTurn", "marketTurn"]) {
    const src = fnSource(name);
    assert.ok(src.indexOf("ui.react.hidden = false") > order(src).stamp, `${name}: reaction shown after the stamp`);
  }
  assert.ok(/ui\.react\.hidden = true;/.test(fnSource("reset")));
});
