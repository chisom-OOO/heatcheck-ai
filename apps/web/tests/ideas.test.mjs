// Run from apps/web:  node --test tests/ideas.test.mjs
//
// The idea board against a mock of GET /api/ideas. The mock's answer is the UI server's own
// output for Research's results (tests/fixtures/idea_family_api.json; test_ideas.py checks it
// equals the server's reader on the byte copies). Every URL must be relative. A small DOM
// stand-in records what renderIdeas builds; no browser is used.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import { loadIdeas, renderIdeas } from "../web/ideas/idea-board.js";
import * as I from "../web/ideas/idea-model.js";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const API = JSON.parse(readFileSync(join(ROOT, "tests", "fixtures", "idea_family_api.json"), "utf8"));
const DEV = API.families.find((f) => f.mode === "development");
const G030 = API.families.find((f) => f.name === "synthetic_gamma030");
const G0 = API.families.find((f) => f.name === "synthetic_gamma0");
const idea = (key, level) => DEV.results.find((r) => (r.params.feature || r.params.condition) === key && r.params.level === level);

class El {
  constructor(tag) { this.tag = tag; this.children = []; this.className = ""; this._text = ""; this.listeners = {}; this.type = ""; }
  set textContent(v) { this._text = String(v); this.children = []; }
  get textContent() { return this._text + this.children.map((c) => c.textContent).join(" "); }
  append(...xs) { this.children.push(...xs); }
  replaceChildren(...xs) { this.children = xs; this._text = ""; }
  addEventListener(t, fn) { this.listeners[t] = fn; }
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
    return { status, ok: status < 400, json: async () => JSON.parse(JSON.stringify(body)) };
  };
  try { return { out: await fn(), calls }; } finally { globalThis.fetch = old; }
}

test("loadIdeas asks the UI server with a relative URL only", async () => {
  const { out, calls } = await withFetch(() => ({ status: 200, body: API }), () => loadIdeas());
  assert.deepEqual(calls, ["/api/ideas"]);
  assert.equal(out.status, "OK");
  assert.equal(out.families.length, 3);
});

test("each idea reads as a plain sentence", () => {
  assert.equal(I.ideaTitle(idea("away_back_to_back", "yes")), "Home teams win more when the away team is on a back-to-back");
  assert.equal(I.ideaTitle(idea("home_back_to_back", "yes")), "Home teams win less when the home team is on a back-to-back");
  assert.equal(I.ideaTitle(idea("elo_gap", "home_fav_100+")), "Home teams win more when the home team is the Elo favourite by 100+ points");
  assert.equal(I.ideaTitle(idea("day_of_week", "Sun")), "Home teams win a different share of games when the game is on a Sunday");
  assert.equal(I.ideaTitle(idea("after_makes", "3")), "Shots go in more often after 3 makes in a row");
  assert.equal(I.ideaTitle(idea("after_makes", "1")), "Shots go in more often after a make");
  assert.equal(I.ideaTitle(idea("shot_value", "3")), "Shots go in less often on 3-pointers");
  assert.equal(I.ideaTitle(idea("period", "1")), "Shots go in at a different rate in the 1st quarter");
  for (const r of DEV.results) assert.ok(!/undefined|_/.test(I.ideaTitle(r)), I.ideaTitle(r));
});

test("numbers and the chance check are Research's, worded plainly", () => {
  const elo = idea("elo_gap", "home_fav_100+");
  assert.equal(I.numbersText(elo), "Home teams won 68.3% of 460 such games, 42.5% of the other 466");
  assert.equal(I.chanceText(elo, DEV.n_ideas), "p = 0.012 after allowing for the 12 ideas tested together (before: 0.001)");
  const q4 = idea("period", "4");
  assert.equal(I.numbersText(q4), "47.1% of 39,268 such shots went in, 47.6% of the other 126,442");
  const v = I.ideaCard(elo, DEV);
  assert.equal(v.verdict, "Worth a proper test");
  assert.equal(v.verdictKind, "candidate");
  assert.equal(v.note, I.CANDIDATE_NOTE);
  assert.equal(I.ideaCard(idea("away_back_to_back", "yes"), DEV).verdict, "No sign of it");
});

test("a CANDIDATE is a lead, never a finding: no SURVIVED, no vindicated pose", () => {
  for (const r of DEV.results) {
    const ref = I.refIdeaText(r, DEV);
    const stamp = I.ideaStamp(r);
    assert.ok(!/SURVIVED|survived|proven|holds up/.test(ref + stamp.text), ref);
    assert.notEqual(I.ideaEndState(r), "vindicated");
    if (r.verdict === "CANDIDATE") {
      assert.equal(stamp.text, "WORTH A TEST");
      assert.equal(I.ideaEndState(r), "thinking");
      assert.ok(ref.startsWith("Worth a proper test.") && ref.endsWith(I.CANDIDATE_NOTE), ref);
    } else {
      assert.equal(stamp.text, "NO SIGN");
      assert.equal(I.ideaEndState(r), "cooled");
    }
  }
});

test("Heater pitches each idea with no digits", () => {
  for (const r of DEV.results) {
    const line = I.heaterIdeaLine(r);
    assert.ok(!/\d/.test(line), line);
    assert.ok(line.endsWith("I'm CALLING it!"));
  }
  assert.equal(I.heaterIdeaLine(idea("after_makes", "3")), "Shots go in MORE often after three makes in a row. I'm CALLING it!");
});

test("synthetic leagues report the planted-truth check as counts", () => {
  assert.deepEqual(I.scoreboardText(G030), {
    title: "Made-up league with a planted streak effect (strength 0.3)",
    lines: ["Found 1 of 9 planted effects; missed 8", "Correctly ignored 4 of 4 ideas with nothing there", "False alarms: 0"],
  });
  assert.equal(I.scoreboardText(G0).title, "Made-up league with no streak effect (control)");
  assert.deepEqual(I.scoreboardText(G0).lines, ["Found 1 of 1 planted effect; missed 0",
    "Correctly ignored 12 of 12 ideas with nothing there", "False alarms: 0"]);
});

test("renderIdeas: twelve idea cards with Ask Heater, two SYNTHETIC league cards without", async () => {
  const root = new El("section");
  const asked = [];
  renderIdeas(root, { status: "OK", families: API.families, refused: [] }, { onAsk: (r) => asked.push(r.idea_hash) });
  assert.match(root.textContent, /12 ideas tested together on 2023-24 development games: 4 worth a proper test/);
  const cards = byClass(root, "icard");
  assert.equal(cards.length, 14);
  const ideaCards = cards.filter((c) => !c.className.includes("synthetic"));
  assert.equal(ideaCards.length, 12);
  assert.equal(ideaCards.filter((c) => c.className.includes("candidate")).length, 4);
  for (const c of ideaCards) assert.equal(byClass(c, "mcard-ask").length, 1);
  const synth = cards.filter((c) => c.className.includes("synthetic"));
  for (const c of synth) {
    assert.equal(byClass(c, "mcard-ask").length, 0);
    assert.match(c.textContent, /SYNTHETIC/);
  }
  byClass(ideaCards[3], "mcard-ask")[0].listeners.click();
  assert.deepEqual(asked, [DEV.results[3].idea_hash]);
});

test("no results, or a refused family, is said plainly", async () => {
  const { out } = await withFetch(() => ({ status: 404, body: { error: "NOT_FOUND",
    message: "no idea-family results in this checkout (Research's research/idea-family is not merged here)" } }), () => loadIdeas());
  const root = new El("section");
  renderIdeas(root, out);
  assert.match(root.textContent, /No idea results: no idea-family results in this checkout/);
  const root2 = new El("section");
  renderIdeas(root2, { status: "OK", families: [DEV], refused: [{ name: "x", reason: "results.json does not cite this registration.json" }] });
  assert.match(root2.textContent, /Not shown x: results.json does not cite this registration.json/);
});
