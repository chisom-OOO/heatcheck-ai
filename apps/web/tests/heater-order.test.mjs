// Run from apps/web:  node --test tests/heater-order.test.mjs
//
// Rehearsal check (8 Nov 2026): Heater's first line never pre-empts the Ref. Before the Ref speaks,
// Heater may not mention the Ref or say or hint at a verdict; anything written with the verdict in
// hand is said only after the stamp lands.
//
// What was wrong: the dialogue answer's heater_text is written by Max's server *after* the ruling
// (heatcheck/agents/dialogue.py: _heater(question, claim_id, facts["decision"], facts); its fallbacks
// say "The Ref says it SURVIVED the checks"), and the page said it as Heater's opening line. The
// market card's heater_text can carry "the Ref's calibration note says…" and the model writing it is
// given refs_verdict. Now the dialogue opener is the personality's line for the claim and Max's text
// is Heater's last word; the market line keeps only its sentences that do not pre-empt the Ref.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import * as H from "../web/heater/heater-model.js";
import { heaterIdeaLine } from "../web/ideas/idea-model.js";
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

/** Python string constants read from Max's source (implicitly concatenated literals joined). */
function pyStrings(src, name) {
  const m = new RegExp(`^${name} = \\(?([\\s\\S]*?)\\)?\\n(?=\\S)`, "m").exec(src);
  assert.ok(m, `${name} not found`);
  return m[1];
}
const joinLiterals = (block) => [...block.matchAll(/"((?:[^"\\]|\\.)*)"/g)].map((x) => x[1]).join("");
function heaterFallbacks() {
  const block = /^HEATER_FALLBACK = \{([\s\S]*?)^\}/m.exec(DIALOGUE_PY)[1];
  const out = {};
  for (const entry of block.split(/,\n(?=\s+(?:None|"[A-Z_]+"):)/)) {
    const k = /^\s*(None|"([A-Z_]+)"):/.exec(entry);
    out[k[2] || "None"] = joinLiterals(entry.slice(k[0].length));
  }
  return out;
}
const FALLBACK = heaterFallbacks();
const HOME_BIAS_HEATER = joinLiterals(pyStrings(MARKET_PY, "HOME_BIAS_HEATER"));
const SAMPLE_HEATER = joinLiterals(pyStrings(MARKET_PY, "SAMPLE_HEATER"));

/** The source of one top-level function in demo.js. */
function fnSource(name) {
  const start = DEMO.search(new RegExp(`^(async )?function ${name}\\(`, "m"));
  assert.ok(start >= 0, `demo.js has no function ${name}`);
  const rest = DEMO.slice(start + 1);
  const end = rest.search(/^(async function |function |const |let |\/\/ -{10})/m);
  return DEMO.slice(start, end < 0 ? undefined : start + 1 + end);
}

test("Max's dialogue lines are written after the ruling, so they would pre-empt the Ref", () => {
  assert.ok(Object.keys(FALLBACK).length >= 7, `read ${Object.keys(FALLBACK).length} fallbacks`);
  for (const k of ["SURVIVED_PROTOCOL", "NOT_SUPPORTED", "INSUFFICIENT_EVIDENCE", "DATA_INVALID", "BLOCKED", "None"]) {
    assert.ok(H.preemptsRef(FALLBACK[k]), `${k}: ${FALLBACK[k]}`);
  }
  // Max's prompt asks the model not to pre-empt, but the model is given the verdict; the page enforces it by order.
  assert.ok(joinLiterals(pyStrings(DIALOGUE_PY, "HEATER_SYSTEM")).includes("pre-empt the Ref"));
  assert.ok(H.preemptsRef(HOME_BIAS_HEATER), HOME_BIAS_HEATER);
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

test("splitTake keeps every sentence, in order, and puts only the pre-empting ones after the stamp", () => {
  const template = "The model has Atlanta Hawks at 62.0% to win. That is above the market's ask of 55.0%. It only uses "
    + "elo_rating_home, elo_rating_away, home_court. Could rest, injuries or lineup news explain the gap? Those are "
    + "questions to investigate, because the model can't see them.";
  const cases = [template, `${template} ${HOME_BIAS_HEATER}`, SAMPLE_HEATER, ...Object.values(FALLBACK),
    ...CAP.exchanges.filter((x) => x.path === "/api/investigate" && x.body?.heater_text).map((x) => x.body.heater_text)];
  for (const text of cases) {
    const { first, later } = H.splitTake(text);
    assert.ok(!H.preemptsRef(first), `first pre-empts: ${first}`);
    const words = (s) => s.split(/\s+/).filter(Boolean);
    assert.equal(words(first).length + words(later).length, words(text).length, `nothing dropped: ${text}`);
  }
  const s = H.splitTake(`${template} ${HOME_BIAS_HEATER}`);
  assert.equal(s.first, template);
  assert.equal(s.later, HOME_BIAS_HEATER);
  assert.deepEqual(H.splitTake(template), { first: template, later: "" });
  assert.equal(H.splitTake(FALLBACK.SURVIVED_PROTOCOL).first, "Heater here!");
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

test("demo.js, every Ref flow: Heater's opener, then the Ref, then the stamp, then any verdict-aware line", () => {
  for (const name of ["ask", "askIdea", "askScenario", "askMarket"]) {
    const o = order(fnSource(name));
    assert.ok(o.firstHeater >= 0 && o.firstHeater < o.ref && o.ref < o.stamp, `${name}: opener < Ref < stamp`);
    for (const [i, arg] of o.heaterAfter) assert.ok(i > o.stamp, `${name}: Heater's ${arg} is said only after the stamp`);
  }
  const ask = fnSource("ask");
  assert.equal(order(ask).firstHeaterArg, "a.take");
  assert.deepEqual(order(ask).heaterAfter.map(([, a]) => a), ["react"]);
  assert.ok(/const react = a\.lastWord \|\| /.test(ask), "Max's line is the last word");
  const answer = fnSource("answer");
  assert.ok(/const take = takeFor\(claimId, state\.personality, state\.turn\);/.test(answer), "the opener is the claim's own line");
  assert.ok(!/take = [^\n]*heater_text/.test(answer), "the dialogue API's text never opens");
  assert.ok(/const lastWord = \(!forced && api\?\.heater_text\) \|\| "";/.test(answer));
  const market = fnSource("askMarket");
  assert.equal(order(market).firstHeaterArg, "take");
  assert.ok(/const take = split\.first \|\| MARKET_OPENER;/.test(market));
  assert.deepEqual(order(market).heaterAfter.map(([, a]) => a), ["split.later"]);
  // The take and the reaction share the bubble but are separate elements; the reaction is shown only
  // after the stamp (it is hidden by reset() at the start of every turn).
  for (const name of ["ask", "askMarket"]) {
    const src = fnSource(name);
    const shown = src.indexOf("ui.react.hidden = false");
    assert.ok(shown > order(src).stamp, `${name}: reaction shown after the stamp`);
  }
  assert.ok(/ui\.react\.hidden = true;/.test(fnSource("reset")));
});
