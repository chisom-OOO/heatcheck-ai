// Run from apps/web:  node --test tests/scenario.test.mjs
//
// The scenario view ("What if…?") on a game card, against a mock of GET /api/scenario.
// Max's server has no scenario endpoint yet, so the mock answers are hand-made in the proposed
// heatcheck-scenario/1 format (tests/fixtures/scenario_api.SAMPLE.json, labelled SAMPLE). The
// SAMPLE card is checked against Max's real captured investigate answer for the same game. A small
// DOM stand-in records what the page builds; no browser is used.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import { renderBoard } from "../web/market/board.js";
import { loadScenarios, renderScenarios } from "../web/market/scenario.js";
import * as S from "../web/market/scenario-model.js";
import * as W from "../web/whatif/whatif.js";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const FIX = JSON.parse(readFileSync(join(ROOT, "tests", "fixtures", "scenario_api.SAMPLE.json"), "utf8"));
const CAPS = JSON.parse(readFileSync(join(ROOT, "tests", "fixtures", "max_api", "captures.json"), "utf8")).exchanges;
const SAMPLE_RESP = CAPS.find((e) => e.path === "/api/investigate" && e.status === 200 && e.body?.game?.game_id === "nba:0022600190"
  && e.body.is_sample).body;
const copy = (x) => JSON.parse(JSON.stringify(x));
const ok = (body) => ({ status: 200, body: copy(body) });
const TEST = () => S.readScenarios(ok(FIX.test_card), { gameId: "nba:0099900001" });
const byId = (data, id) => data.scenarios.find((s) => s.scenario_id === id);

class El {
  constructor(tag) {
    this.tag = tag; this.children = []; this.className = ""; this._text = ""; this.listeners = {};
    this.type = ""; this.hidden = false; this.disabled = false; this.style = {}; this.attrs = {};
  }
  set textContent(v) { this._text = String(v); this.children = []; }
  get textContent() { return [this._text, ...this.children.map((c) => c.textContent)].filter(Boolean).join(" "); }
  append(...xs) { this.children.push(...xs); }
  replaceChildren(...xs) { this.children = xs; this._text = ""; }
  addEventListener(t, fn) { this.listeners[t] = fn; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  all(pred, out = []) { if (pred(this)) out.push(this); this.children.forEach((c) => c.all(pred, out)); return out; }
}
globalThis.document = { createElement: (t) => new El(t) };
const byClass = (root, c) => root.all((e) => e.className.split(" ").includes(c));

async function withFetch(answer, fn) {
  const old = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    calls.push(url);
    assert.match(url, /^\/api\//, `non-relative URL: ${url}`);
    const { status, body } = answer(url, init);
    return { status, ok: status < 400, json: async () => copy(body) };
  };
  try { return { out: await fn(), calls }; } finally { globalThis.fetch = old; }
}

test("loadScenarios asks one relative URL, with the game id encoded", async () => {
  const { out, calls } = await withFetch(() => ok(FIX.sample_card), () => loadScenarios("nba:0022600190", { resp: SAMPLE_RESP }));
  assert.deepEqual(calls, ["/api/scenario?game_id=nba%3A0022600190"]);
  assert.equal(out.status, "OK");
  assert.equal(out.isSample, true);
});

test("no endpoint, Max down, or no answer is said plainly", async () => {
  const notFound = await withFetch(() => ({ status: 404, body: { error: "not found" } }), () => loadScenarios("nba:1"));
  assert.equal(notFound.out.reason, "Max's server has no scenario endpoint yet");
  const down = await withFetch(() => ({ status: 502, body: { error: "UPSTREAM_UNAVAILABLE" } }), () => loadScenarios("nba:1"));
  assert.equal(down.out.reason, "Max's server is not answering");
  const thrown = await withFetch(() => { throw new Error("refused"); }, () => loadScenarios("nba:1"));
  assert.match(thrown.out.reason, /not answering \(refused\)/);
  const slot = new El("div");
  renderScenarios(slot, notFound.out);
  assert.equal(slot.textContent, "No scenarios: Max's server has no scenario endpoint yet.");
});

test("a scenario must be an ESTIMATE with its point inside its range, n and caveats", () => {
  const d = TEST();
  assert.deepEqual(d.scenarios.map((s) => s.scenario_id), ["test-up", "test-down", "test-flat"]);
  assert.deepEqual(d.refused.map((r) => r.reason), [
    'label is "FINDING", not "ESTIMATE"',
    "no caveats (an estimate must say what it leaves out)",
    "p_team_win is outside its range",
  ]);
  const s = copy(byId(d, "test-up"));
  assert.equal(S.scenarioProblem({ ...s, n: 12.5 }), "n is not a positive whole number");
  assert.equal(S.scenarioProblem({ ...s, p_team_win: 0.652 }), "p_team_win is not a decimal string between 0 and 1");
  assert.equal(S.scenarioProblem({ ...s, range: { ...s.range, level: "1" } }), "range level is not a decimal between 0 and 1");
});

test("the whole answer is refused when it does not belong to this card", () => {
  const resp = copy(SAMPLE_RESP);
  const r = (body, o = {}) => S.readScenarios(ok(body), { gameId: "nba:0022600190", resp, ...o }).reason;
  assert.equal(r(FIX.sample_card), undefined);
  assert.equal(r({ ...FIX.sample_card, game_id: "nba:0022600191" }), "the answer is for a different game");
  assert.equal(r({ ...FIX.sample_card, baseline: { p_team_win: "0.55" } }), "the scenario's baseline is not the card's forecast");
  assert.equal(r({ ...FIX.sample_card, team: "Brooklyn Nets" }), "the scenario is for Brooklyn Nets, the card for Atlanta Hawks");
  assert.equal(r({ ...FIX.sample_card, is_sample: false }), "the scenario and the card disagree on SAMPLE");
  assert.equal(r({ ...FIX.sample_card, format: "other/1" }), 'unknown format "other/1"');
});

test("baseline and scenario side by side, with change, range, n and caveats", () => {
  const d = TEST();
  const v = S.scenarioView(byId(d, "test-up"), d);
  assert.deepEqual([v.baseline, v.scenario], [
    { head: "Forecast now", value: "Test Home Team 60.0%" },
    { head: "In this scenario", value: "Test Home Team 65.2%" },
  ]);
  assert.equal(v.label, "ESTIMATE");
  assert.equal(v.change, "+5.2 pts");
  assert.equal(v.range, "Range 61.8% to 69.0% (90%)");
  assert.equal(v.n, "Based on 1,224 games");
  assert.deepEqual(v.caveats, ["Rest effect is averaged over all teams", "Does not see who actually plays."]);
  assert.equal(v.coversBaseline, false);
  assert.deepEqual(v.bar, { base: 0.6, p: 0.652, low: 0.618, high: 0.69 });
  const down = S.scenarioView(byId(d, "test-down"), d);
  assert.equal(down.change, "−5.9 pts");
  assert.equal(down.coversBaseline, true);
  assert.equal(S.scenarioView(byId(d, "test-flat"), d).change, "No real change");
});

test("Heater reacts to the direction of the change, with no digits", () => {
  const d = TEST();
  assert.equal(S.heaterScenarioLine(byId(d, "test-up"), d), "That pushes Test Home Team UP! I can FEEL it heating up!");
  assert.equal(S.heaterScenarioLine(byId(d, "test-down"), d), "Whoa, that knocks Test Home Team DOWN! Somebody turn the heat back on!");
  assert.equal(S.heaterScenarioLine(byId(d, "test-flat"), d), "That barely moves Test Home Team. I'm not buying the hype on this one.");
  for (const s of d.scenarios) assert.ok(!/\d/.test(S.heaterScenarioLine(s, d)));
  const sd = S.readScenarios(ok(FIX.sample_card), { gameId: "nba:0022600190", resp: SAMPLE_RESP });
  const line = S.heaterScenarioLine(sd.scenarios[0], sd);
  assert.ok(/SAMPLE/.test(line) && !/\d/.test(line), line);
});

test("the Ref words the estimate and always keeps 'Edge unverified'", () => {
  const d = TEST();
  assert.equal(S.refScenarioText(byId(d, "test-up"), d),
    "ESTIMATE, not a finding. If the away team is on the second night of a back-to-back: Test Home Team 65.2%, against 60.0% now (+5.2 pts)."
    + " Range 61.8% to 69.0% (90%), based on 1,224 games."
    + " Caveats: Rest effect is averaged over all teams; Does not see who actually plays. Edge unverified: nothing shows this model beats the market.");
  const down = S.refScenarioText(byId(d, "test-down"), d);
  assert.match(down, /The range still includes the current forecast, so the change may be noise\./);
  for (const s of d.scenarios) assert.match(S.refScenarioText(s, d), /Edge unverified/);
  const sd = S.readScenarios(ok(FIX.sample_card), { gameId: "nba:0022600190", resp: SAMPLE_RESP });
  const ref = S.refScenarioText(sd.scenarios[0], sd);
  assert.match(ref, /^SAMPLE scenario: .*Edge unverified/);
  assert.ok(!/\d/.test(ref), "a SAMPLE value must never be worded as real");
});

test("stamp is ESTIMATE (or SAMPLE); Heater never ends vindicated", () => {
  const d = TEST();
  assert.deepEqual(S.scenarioStamp(d, byId(d, "test-up")), { text: "ESTIMATE", kind: "insufficient" });
  assert.equal(S.scenarioEndState(byId(d, "test-up"), d), "thinking");
  assert.equal(S.scenarioEndState(byId(d, "test-down"), d), "unsure");   // range covers the forecast
  assert.equal(S.scenarioEndState(byId(d, "test-flat"), d), "unsure");
  const sd = S.readScenarios(ok(FIX.sample_card), { gameId: "nba:0022600190", resp: SAMPLE_RESP });
  assert.deepEqual(S.scenarioStamp(sd, sd.scenarios[0]), { text: "SAMPLE", kind: "blocked" });
  assert.equal(S.scenarioEndState(sd.scenarios[0], sd), "blocked");
});

test("renderScenarios: ESTIMATE label, two cells, a range bar, n and caveats under it", () => {
  const d = TEST();
  const slot = new El("div");
  const asked = [];
  renderScenarios(slot, d, { onAsk: (s) => asked.push(s.scenario_id) });
  const boxes = byClass(slot, "scen");
  assert.equal(boxes.length, 3);
  const up = boxes[0];
  assert.equal(byClass(up, "scen-label")[0].textContent, "ESTIMATE");
  assert.deepEqual(byClass(up, "scen-cell-value").map((e) => e.textContent), ["Test Home Team 60.0%", "Test Home Team 65.2%"]);
  assert.deepEqual(byClass(up, "scen-range")[0].style, { left: "61.80%", width: "7.20%" });
  assert.equal(byClass(up, "scen-base")[0].style.left, "60.00%");
  assert.equal(byClass(up, "scen-point")[0].style.left, "65.20%");
  assert.equal(byClass(up, "scen-bar")[0].attrs["aria-label"], "Range 61.8% to 69.0%, scenario 65.2%, forecast now 60.0%");
  assert.equal(byClass(up, "scen-meta")[0].textContent, "Range 61.8% to 69.0% (90%) · Based on 1,224 games");
  assert.equal(byClass(up, "scen-caveats")[0].children.length, 2);
  assert.equal(byClass(up, "mcard-sample").length, 0);
  byClass(boxes[1], "scen-ask")[0].listeners.click();
  assert.deepEqual(asked, ["test-down"]);
  assert.match(slot.textContent, /Not shown "Labelled as a finding": label is "FINDING", not "ESTIMATE"\./);
  assert.match(slot.textContent, /Source: SAMPLE: hand-made test fixture/);
});

test("on the board: 'What if…?' loads once, shows SAMPLE scenarios as SAMPLE, and hands Ask to the demo", async () => {
  const root = new El("section");
  const loads = [];
  const asked = [];
  const board = {
    status: "OK", isSample: true, forecast: { model: "SAMPLE", data_cutoff_utc: "2026-11-07T22:00:00Z", inputs_used: [] },
    games: [{ row: { game_id: "nba:0022600190", home_team: "Atlanta Hawks", away_team: "Brooklyn Nets", tip_utc: "2026-11-08T00:30:00Z", p_home_win: "0.5" },
      mapping: null, resp: copy(SAMPLE_RESP), error: null }],
  };
  const load = async (gameId, { resp }) => {
    loads.push(gameId);
    return S.readScenarios(ok(FIX.sample_card), { gameId, resp });
  };
  renderBoard(root, board, { onAsk: () => {}, onScenario: (g, s, data) => asked.push([g.row.game_id, s.scenario_id, data.isSample]), loadScenarios: load });
  const btn = byClass(root, "mcard-whatif")[0];
  const slot = byClass(root, "scen-slot")[0];
  assert.equal(slot.hidden, true);
  await btn.listeners.click();
  assert.equal(slot.hidden, false);
  assert.equal(btn.attrs["aria-expanded"], "true");
  const box = byClass(slot, "scen")[0];
  assert.match(box.textContent, /SAMPLE/);
  assert.match(box.textContent, /SAMPLE: invented values, not a real estimate/);
  byClass(box, "scen-ask")[0].listeners.click();
  assert.deepEqual(asked, [["nba:0022600190", "sample-rest", true]]);
  await btn.listeners.click();  // close
  await btn.listeners.click();  // reopen: no second request
  assert.deepEqual(loads, ["nba:0022600190"]);
});

function sampleBoard() {
  return {
    status: "OK", isSample: true, forecast: { model: "SAMPLE", data_cutoff_utc: "2026-11-07T22:00:00Z", inputs_used: [] },
    games: [{ row: { game_id: "nba:0022600190", home_team: "Atlanta Hawks", away_team: "Brooklyn Nets", tip_utc: "2026-11-08T00:30:00Z", p_home_win: "0.5" },
      mapping: null, resp: copy(SAMPLE_RESP), error: null }],
  };
}
const sampleLoad = async (gameId, { resp }) => S.readScenarios(ok(FIX.sample_card), { gameId, resp });

test("'Your own scenario' box: under the presets, sends the typed text with this card's game, and fetches nothing itself", async () => {
  const root = new El("section");
  const own = [];
  renderBoard(root, sampleBoard(), { onScenario: () => {}, onOwnScenario: (g, text) => own.push([g.row.game_id, text]), loadScenarios: sampleLoad });
  await byClass(root, "mcard-whatif")[0].listeners.click();
  const slot = byClass(root, "scen-slot")[0];
  const form = byClass(slot, "scen-own")[0];
  assert.ok(form, "box missing");
  assert.equal(slot.children.at(-1), form, "the box comes after the preset scenarios");
  const label = byClass(form, "scen-own-label")[0];
  const input = byClass(form, "scen-own-input")[0];
  assert.equal(label.textContent, "Your own scenario");
  assert.equal(label.attrs.for, input.id);
  assert.equal(input.maxLength, 200);
  assert.equal(input.placeholder, "e.g. What if Atlanta Hawks were without their top scorer?");
  assert.equal(byClass(form, "scen-own-go")[0].type, "submit");
  const { calls } = await withFetch(() => { throw new Error("the box must not fetch"); }, async () => {
    let prevented = 0;
    input.value = "   ";
    form.listeners.submit({ preventDefault: () => { prevented += 1; } });
    input.value = "  What if Trae Young sits?  ";
    form.listeners.submit({ preventDefault: () => { prevented += 1; } });
    assert.equal(prevented, 2, "the form never reloads the page");
  });
  assert.deepEqual(calls, []);
  assert.deepEqual(own, [["nba:0022600190", "What if Trae Young sits?"]]);
});

test("no box without onOwnScenario; and demo.js hands the box to Max's free-text flow with the card's game id", async () => {
  const root = new El("section");
  renderBoard(root, sampleBoard(), { onScenario: () => {}, loadScenarios: sampleLoad });
  await byClass(root, "mcard-whatif")[0].listeners.click();
  assert.equal(byClass(root, "scen-own").length, 0);
  const demo = readFileSync(join(ROOT, "web", "demo.js"), "utf8");
  assert.match(demo, /onOwnScenario: \(g, text\) => \{ if \(!state\.busy\) runScenario\(text, g\.row\.game_id\); \}/);
  assert.match(demo, /postJson\(SCENARIO_URL, gameId \? \{ message: question, game_id: gameId \}/);  // Max's flow sends both
});

// Stamp rule: ESTIMATE whenever the number comes from data (preset or typed); YOUR ASSUMPTION when
// the user supplied the number. Typed what-ifs show the server's stamp through Max's whatifStamp
// (tests/whatif.test.mjs covers it on his code-generated cases); presets use their own label.
test("a preset ESTIMATE looks exactly like a typed ESTIMATE from Max's server", () => {
  const d = TEST();
  for (const s of d.scenarios) assert.deepEqual(S.scenarioStamp(d, s), W.whatifStamp({ stamp: "ESTIMATE" }));
  assert.equal(W.whatifStamp({ stamp: "YOUR ASSUMPTION" }).text, "YOUR ASSUMPTION");
});

test("demo.js: typed what-ifs show the server's stamp, presets their label; one whatifStamp only", () => {
  const demo = readFileSync(join(ROOT, "web", "demo.js"), "utf8");
  assert.match(demo, /const wst = whatifStamp\(est\);/);
  assert.match(demo, /const stamp = scenarioStamp\(data, s\);/);
  assert.doesNotMatch(demo, /ui\.stamp\.textContent = "HYPOTHETICAL"/);
  const imports = demo.match(/import \{[^}]*\} from "[^"]+";/g) || [];
  assert.deepEqual(imports.filter((i) => /\bwhatifStamp\b/.test(i)).map((i) => i.match(/from "([^"]+)"/)[1]), ["./whatif/whatif.js"]);
});

test("without onScenario the board has no What if button (Max's existing board unchanged)", () => {
  const root = new El("section");
  renderBoard(root, { status: "OK", isSample: false, forecast: {}, games: [{ row: { game_id: "g", home_team: "H", away_team: "A", tip_utc: "", p_home_win: "0.5" }, resp: null, error: "x" }] });
  assert.equal(byClass(root, "mcard-whatif").length, 0);
});
