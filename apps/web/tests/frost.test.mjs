// Frost, the second character (Experience, 8 Nov 2026). Mocks only, no browser.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { mock, test } from "node:test";
import { fileURLToPath } from "node:url";

import {
  FROST_STATES, FROST_VOICE, MAX_CHALLENGES, chipView, exchangeFromApi, exchangeSteps, frostEndState,
  frostPoseFile, isSkipKey, normalizeExchange, pickCastVoices, skippable,
} from "../web/frost/frost-model.js";
import { Frost } from "../web/frost/frost.js";
import { VOICE, fallbackSpeechMs, pickVoices } from "../web/heater/heater-model.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const WEB = join(HERE, "..", "web");
const JS = readFileSync(join(WEB, "demo.js"), "utf8");
const HTML = readFileSync(join(WEB, "demo.html"), "utf8");
const CSS = readFileSync(join(WEB, "demo.css"), "utf8");

const EX = {
  take: "Three straight? He's ON FIRE!",
  challenges: [
    { question: "On how many shots?", chip: { text: "219,274 shots", kind: "info" } },
    { question: "Did you shuffle within each game?", chip: { text: "Shuffle test: no streak beyond chance", kind: "fail" } },
  ],
  frostReaction: "As I suspected.",
  heaterReaction: "Fine. For now.",
};

// ---- the sequence
test("the sequence: take, question, chip, (repeat), Ref, stamp, Frost's reaction, Heater's reaction", () => {
  const steps = exchangeSteps(normalizeExchange(EX));
  assert.deepEqual(steps.map((s) => `${s.who}:${s.kind}`), [
    "heater:take", "frost:question", "frost:chip", "frost:question", "frost:chip",
    "ref:ruling", "ref:stamp", "frost:reaction", "heater:reaction",
  ]);
  assert.equal(steps[1].first, true);
  assert.equal(steps[3].first, false);
  assert.deepEqual(steps[2].chip, { text: "219,274 shots", kind: "info" });
});

test("at most three questions; empty questions dropped; a question without a chip has no chip step", () => {
  const many = { take: "x", challenges: [1, 2, 3, 4, 5].map((i) => ({ question: `Q${i}?` })) };
  const n = normalizeExchange(many);
  assert.equal(MAX_CHALLENGES, 3);
  assert.deepEqual(n.challenges.map((c) => c.question), ["Q1?", "Q2?", "Q3?"]);
  const steps = exchangeSteps(n);
  assert.equal(steps.filter((s) => s.kind === "chip").length, 0);
  assert.equal(normalizeExchange({ take: "x", challenges: [{ question: " " }, { question: "Q?" }] }).challenges.length, 1);
});

test("no exchange without a take or a question; reactions without text are left out", () => {
  assert.equal(normalizeExchange({ take: "", challenges: [{ question: "Q?" }] }), null);
  assert.equal(normalizeExchange({ take: "x", challenges: [] }), null);
  assert.equal(normalizeExchange(null), null);
  const steps = exchangeSteps(normalizeExchange({ take: "x", challenges: [{ question: "Q?" }] }));
  assert.deepEqual(steps.map((s) => s.kind), ["take", "question", "ruling", "stamp"]);
});

test("chips say the result in words; colour class is pass, fail or info", () => {
  assert.deepEqual(chipView({ text: "Holm p 0.0054", kind: "pass" }), { text: "Holm p 0.0054", kind: "pass" });
  assert.deepEqual(chipView({ label: "CI includes zero", status: "FAIL" }), { text: "CI includes zero", kind: "fail" });
  assert.deepEqual(chipView({ text: "n = 300 games" }), { text: "n = 300 games", kind: "info" });
  assert.equal(chipView({ text: "  " }), null);
});

test("Frost's end pose: satisfied only by a claim that survived", () => {
  assert.equal(frostEndState("SURVIVED_PROTOCOL"), "satisfied");
  for (const d of ["NOT_SUPPORTED", "INSUFFICIENT_EVIDENCE", "BLOCKED", null]) assert.equal(frostEndState(d), "unconvinced");
  assert.equal(frostPoseFile("asking"), "poses/asking.webp");
  assert.equal(frostPoseFile("nope"), "poses/idle.webp");
  assert.ok(FROST_STATES.includes("listening"));
});

test("exchangeFromApi: no Frost block in the answer means the Heater-only flow", () => {
  assert.equal(exchangeFromApi(null, { take: "x" }), null);
  assert.equal(exchangeFromApi({ heater_text: "x" }, { take: "x" }), null);
  const ex = exchangeFromApi({ frost: { challenges: [{ question: "Q?", chip: { text: "ok", kind: "pass" } }], reaction: "Hm." } }, { take: "T" });
  assert.deepEqual(ex, { take: "T", challenges: [{ question: "Q?", chip: { text: "ok", kind: "pass" } }], frostReaction: "Hm.", heaterReaction: "" });
});

// ---- Space skips to the stamp
test("Space skips only while the exchange runs, and never takes over typing elsewhere", () => {
  const ev = (o) => ({ code: "Space", key: " ", target: { tagName: "BODY" }, ...o });
  assert.equal(isSkipKey(ev(), { running: false }), false);
  assert.equal(isSkipKey(ev(), { running: true }), true);
  assert.equal(isSkipKey(ev({ code: "", key: " " }), { running: true }), true);
  assert.equal(isSkipKey(ev({ target: { tagName: "INPUT", id: "q" } }), { running: true }), true, "the question box is idle meanwhile");
  assert.equal(isSkipKey(ev({ target: { tagName: "INPUT", id: "scen-own" } }), { running: true }), false);
  assert.equal(isSkipKey(ev({ target: { tagName: "TEXTAREA" } }), { running: true }), false);
  assert.equal(isSkipKey(ev({ target: { isContentEditable: true } }), { running: true }), false);
  assert.equal(isSkipKey(ev({ repeat: true }), { running: true }), false);
  assert.equal(isSkipKey(ev({ ctrlKey: true }), { running: true }), false);
  assert.equal(isSkipKey(ev({ code: "Enter", key: "Enter" }), { running: true }), false);
  assert.equal(skippable({ kind: "take" }), true);
  assert.equal(skippable({ kind: "stamp" }), false, "the stamp always lands");
  assert.equal(skippable({ kind: "reaction" }), false, "reactions after the stamp still play");
});

// ---- three distinct voices
const V = (name, lang) => ({ name, lang });
test("three voices: Heater's, a British one for Frost, and a Ref voice that is neither", () => {
  const voices = [V("Microsoft Guy Online", "en-US"), V("Microsoft Libby Online", "en-GB"),
    V("Microsoft Ryan Online", "en-GB"), V("Microsoft Davis Online", "en-US")];
  const { heater, frost, ref } = pickCastVoices(voices);
  assert.equal(heater.name, "Microsoft Guy Online");
  assert.equal(frost.lang, "en-GB");
  assert.notEqual(frost, heater);
  assert.notEqual(ref, frost);
  assert.notEqual(ref, heater);
  assert.equal(pickVoices(voices).ref.name, "Microsoft Libby Online", "without Frost, the Ref's choice is unchanged");
});

test("when Frost takes the Ref's only British voice, the Ref moves to another voice", () => {
  const voices = [V("Microsoft Guy Online", "en-US"), V("Microsoft Libby Online", "en-GB"), V("Microsoft Davis Online", "en-US")];
  const { heater, frost, ref } = pickCastVoices(voices);
  assert.equal(frost.name, "Microsoft Libby Online");
  assert.equal(ref.name, "Microsoft Davis Online");
  assert.notEqual(ref, heater);
  assert.deepEqual(pickCastVoices([]), { heater: null, frost: null, ref: null });
  assert.deepEqual(FROST_VOICE, { lang: "en-GB", rate: 0.95, pitch: 1.0 });
  assert.notDeepEqual({ rate: FROST_VOICE.rate, pitch: FROST_VOICE.pitch }, VOICE.ref, "the Ref keeps its own settings");
});

// ---- Frost speaks in his own voice
const fakeRoot = () => {
  const cls = new Set();
  return { classList: { add: (c) => cls.add(c), remove: (c) => cls.delete(c), contains: (c) => cls.has(c) }, querySelectorAll: () => [], querySelector: () => null, cls };
};

test("Frost.speak uses en-GB, rate 0.95 and a British voice, and resolves when speech ends", async () => {
  const spoken = [];
  const synth = {
    getVoices: () => [V("Microsoft Guy Online", "en-US"), V("Microsoft Ryan Online", "en-GB"), V("Microsoft Libby Online", "en-GB")],
    cancel() {}, speak(u) { spoken.push(u); setTimeout(() => u.onend?.(), 0); },
  };
  const old = { s: globalThis.speechSynthesis, U: globalThis.SpeechSynthesisUtterance };
  globalThis.speechSynthesis = synth;
  globalThis.SpeechSynthesisUtterance = class { constructor(t) { this.text = t; } };
  try {
    const root = fakeRoot();
    const f = new Frost(root);
    const p = f.speak("On how many shots?");
    assert.ok(root.cls.has("talking"));
    await p;
    assert.equal(spoken.length, 1);
    assert.equal(spoken[0].lang, "en-GB");
    assert.equal(spoken[0].rate, 0.95);
    assert.equal(spoken[0].voice.lang, "en-GB");
    assert.ok(!root.cls.has("talking"));
  } finally {
    globalThis.speechSynthesis = old.s;
    globalThis.SpeechSynthesisUtterance = old.U;
  }
});

test("Frost.speak with the voice off waits the usual reading time, then resolves", async () => {
  mock.timers.enable({ apis: ["setTimeout"] });
  try {
    const f = new Frost(fakeRoot());
    let done = false;
    const p = f.speak("Did you shuffle within each game?", { voiceOn: false }).then(() => { done = true; });
    const ms = fallbackSpeechMs("Did you shuffle within each game?", FROST_VOICE.rate);
    mock.timers.tick(ms - 1);
    await Promise.resolve();
    assert.equal(done, false);
    mock.timers.tick(1);
    await p;
    assert.equal(done, true);
  } finally {
    mock.timers.reset();
  }
});

// ---- page wiring (source checks; the browser run is Max's, with demo.cmd)
const fnBody = (name) => {
  const i = JS.indexOf(`async function ${name}(`);
  assert.ok(i >= 0, name);
  const rest = JS.slice(i + 10);
  const next = rest.search(/\n(?:async function|function|const|let|\/\/ -{10}) /);
  return JS.slice(i, next < 0 ? undefined : i + 10 + next);
};

test("runExchange handles every step kind, in the sequence's order, and Frost slides in on his first question", () => {
  const src = fnBody("runExchange");
  const at = (s) => { const i = src.indexOf(s); assert.ok(i >= 0, s); return i; };
  const order = ['st.kind === "take"', 'st.kind === "question"', 'st.kind === "chip"', 'st.kind === "ruling"', 'st.kind === "stamp"', 'st.kind === "reaction"'];
  order.reduce((prev, s) => { const i = at(s); assert.ok(i > prev, `${s} after the previous step`); return i; }, -1);
  assert.ok(at("if (st.first) { f.enter();") < at('lastFrost = convoBubble("frost", st.text)'));
  assert.ok(at("convoChip(lastFrost, st.chip)") > 0);
  assert.ok(at("state.exchangeRunning = false;") > at('st.kind === "stamp"'), "Space stops working once the stamp lands");
  assert.ok(at("f.setState(frostEndState(decision))") > at('st.kind === "stamp"'));
});

test("ask() runs the Frost exchange only when the answer has one; otherwise the Heater-only flow is unchanged", () => {
  const src = fnBody("ask");
  assert.ok(src.indexOf("if (a.exchange) {") < src.indexOf("// 1. Heater's hot take"));
  assert.match(src, /if \(a\.exchange\) \{\s*await runExchange\(a, turn\);[\s\S]*?return;\s*\}/);
});

test("bubbles carry no name tag: one text paragraph, side and colour only", () => {
  const i = JS.indexOf("function convoBubble(");
  const src = JS.slice(i, JS.indexOf("\n}\n", i));
  assert.match(src, /li\.className = `cv cv-\$\{who\}/);
  assert.equal((src.match(/createElement\(/g) || []).length, 2, "an <li> and one <p>, nothing else");
  assert.ok(!/HEATER|FROST|Heater:|Frost:/.test(src));
});

test("Space is wired to skip, and the Ref's voice avoids Frost's while he is on stage", () => {
  assert.match(JS, /document\.addEventListener\("keydown", \(e\) => \{\s*if \(!isSkipKey\(e, \{ running: state\.exchangeRunning \}\)\) return;\s*e\.preventDefault\(\);\s*skipToStamp\(\);/);
  assert.match(JS, /state\.heater\.voicePicker = frost \? pickCastVoices : null;/);
  const heaterJs = readFileSync(join(WEB, "heater", "heater.js"), "utf8");
  assert.match(heaterJs, /\(this\.voicePicker \|\| pickVoices\)\(synth\.getVoices\(\)\)/);
});

test("layout: Heater left, conversation middle, Frost right; small portraits on top when narrow", () => {
  assert.ok(HTML.indexOf('class="hero"') < HTML.indexOf('class="talk"') && HTML.indexOf('class="talk"') < HTML.indexOf('class="frost-side"'));
  assert.ok(HTML.indexOf('id="convo"') < HTML.indexOf('id="ref"'), "the Ref's card comes after the conversation");
  assert.match(CSS, /body\[data-cast="frost"\] \.stage \{\s*grid-template-columns: [^;]+;\s*grid-template-areas: "hero talk frost" "ask ask ask";/);
  assert.match(CSS, /grid-template-areas: "hero frost" "talk talk" "ask ask";/);
  assert.match(CSS, /\.cv-heater::before \{ left: -24px;/, "Heater's tail points left");
  assert.match(CSS, /\.cv-frost::before \{ right: -24px;/, "Frost's tail points right");
  assert.match(CSS, /\.cv-frost \{[^}]*border: 3px solid var\(--ice\)/);
  assert.match(CSS, /\.f-root \{[^}]*transform: translateX\(110%\)/, "Frost waits off stage");
  assert.match(CSS, /\.f-root\.entered \{ transform: none; opacity: 1; \}/);
  assert.match(CSS, /body\[data-cast="frost"\] \.ref \{ margin: 18px auto 0;/, "the Ref's card is centred");
});
