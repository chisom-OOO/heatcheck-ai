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
import { VOICE, dialogueLines, fallbackSpeechMs, pickVoices } from "../web/heater/heater-model.js";

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
  assert.deepEqual(chipView("Couldn't find one.", "decision rule"), { text: "Couldn't find one.", kind: "info", source: "decision rule" });
  assert.equal(chipView(""), null);
});

test("Frost's poses are the user's five files, 687x1024 like Heater's", () => {
  assert.deepEqual([...FROST_STATES], ["idle", "challenging", "evidence", "unconvinced", "satisfied"]);
  assert.equal(frostEndState("SURVIVED_PROTOCOL"), "satisfied");
  for (const d of ["NOT_SUPPORTED", "INSUFFICIENT_EVIDENCE", "BLOCKED", null]) assert.equal(frostEndState(d), "unconvinced");
  assert.equal(frostPoseFile("challenging"), "poses/challenging.webp");
  assert.equal(frostPoseFile("nope"), "poses/idle.webp");
  const size = (p) => { const b = readFileSync(p); assert.equal(b.toString("latin1", 8, 12), "WEBP", p); return webpSize(b); };
  const heater = size(join(WEB, "heater", "poses", "idle.webp"));
  for (const s of FROST_STATES) assert.deepEqual(size(join(WEB, "frost", frostPoseFile(s))), heater, s);
});

/** Width and height from a WebP header (VP8, VP8L or VP8X). */
function webpSize(b) {
  const c = b.toString("latin1", 12, 16);
  if (c === "VP8X") return [1 + b.readUIntLE(24, 3), 1 + b.readUIntLE(27, 3)];
  if (c === "VP8L") { const v = b.readUInt32LE(21); return [(v & 0x3FFF) + 1, ((v >> 14) & 0x3FFF) + 1]; }
  return [b.readUInt16LE(26) & 0x3FFF, b.readUInt16LE(28) & 0x3FFF];
}

test("exchangeFromApi: no Frost list in the answer means the Heater-only flow", () => {
  assert.equal(exchangeFromApi(null, { take: "x" }), null);
  assert.equal(exchangeFromApi({ heater_text: "x" }, { take: "x" }), null);
  assert.equal(exchangeFromApi({ frost: [] }, { take: "x" }), null);
  assert.equal(exchangeFromApi({ frost: { challenges: [{ question: "Q?" }] } }, { take: "x" }), null, "only the sample's list shape");
});

// ---- the user's sample response (8 Nov), until Max's API returns frost
const SAMPLE = JSON.parse(readFileSync(join(WEB, "frost", "fixtures", "sample-dialogue.json"), "utf8"));

test("the sample response maps to take, three questions with chips, Frost's and Heater's reactions", () => {
  const lines = dialogueLines(SAMPLE, () => "fallback");
  assert.equal(lines.take, "Three straight makes? He's ON FIRE. Give him the ball!");
  assert.equal(lines.takeFromApi, true);
  assert.equal(lines.lastWord, "The data is WRONG. I watched the games!");
  const ex = exchangeFromApi(SAMPLE, { take: lines.take });
  assert.equal(ex.challenges.length, 3);
  assert.deepEqual(ex.challenges.map((c) => c.question), SAMPLE.frost.map((c) => c.question));
  assert.deepEqual(ex.challenges.map((c) => c.chip.text), SAMPLE.frost.map((c) => c.chip));
  assert.deepEqual(ex.challenges.map((c) => c.chip.source), ["custodian seal", "result.p_holm", "decision rule"]);
  assert.equal(ex.frostReaction, "Not shown. That's not the same as wrong, Heater.");
  const steps = exchangeSteps({ ...ex, heaterReaction: lines.lastWord });
  assert.deepEqual(steps.map((s) => `${s.who}:${s.kind}`), [
    "heater:take", "frost:question", "frost:chip", "frost:question", "frost:chip", "frost:question", "frost:chip",
    "ref:ruling", "ref:stamp", "frost:reaction", "heater:reaction",
  ]);
  assert.equal(frostEndState(SAMPLE.verdict), "unconvinced");
  const shown = JSON.stringify(steps);
  for (const c of SAMPLE.frost) assert.ok(!shown.includes(`"${c.check}"`), `check name ${c.check} is never shown`);
});

test("sample mode only with ?frost=sample, and the page always labels it", () => {
  assert.match(JS, /const FROST_SAMPLE = params\.get\("frost"\) === "sample" \?/);
  assert.match(JS, /return \{ \.\.\.\(await r\.json\(\)\), is_sample: true \};/);
  assert.match(JS, /ui\.sampleFlag\.hidden = !show\.sample;/);
  assert.match(JS, /sample: a\.sample,/);
  assert.ok(!/"47\.27/.test(readFileSync(join(WEB, "frost", "fixtures", "sample-dialogue.json"), "utf8")), "no number that is not in the record");
  assert.match(HTML, /id="sample-flag" hidden>SAMPLE RESPONSE[^<]*not a live answer</);
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
  assert.equal(frost.name, "Microsoft Ryan Online", "the adviser's first choice for Frost");
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
  // Frost keeps the adviser's settings; the Ref's differ (user, 8 Nov: rate 1.0, pitch 1.05), so the two
  // never sound the same even on a machine with a single British voice
  assert.deepEqual(FROST_VOICE, { lang: "en-GB", rate: 0.95, pitch: 0.9 });
  assert.deepEqual(VOICE.ref, { rate: 1.0, pitch: 1.05 });
  assert.notDeepEqual([VOICE.ref.rate, VOICE.ref.pitch], [FROST_VOICE.rate, FROST_VOICE.pitch]);
});

test("Chrome: Frost takes Google UK English Male, which pickVoices gives the Ref, so the Ref moves to UK Female", () => {
  const voices = [V("Google US English", "en-US"), V("Google UK English Female", "en-GB"), V("Google UK English Male", "en-GB")];
  assert.equal(pickVoices(voices).ref.name, "Google UK English Male");
  const { heater, frost, ref } = pickCastVoices(voices);
  assert.equal(heater.name, "Google US English");
  assert.equal(frost.name, "Google UK English Male");
  assert.equal(ref.name, "Google UK English Female");
});

test("Edge listing en-GB first: Heater would match Ryan, so he moves to Guy and Frost gets Ryan", () => {
  const voices = [V("Microsoft Libby Online (Natural)", "en-GB"), V("Microsoft Ryan Online (Natural)", "en-GB"),
    V("Microsoft Sonia Online (Natural)", "en-GB"), V("Microsoft Guy Online (Natural)", "en-US")];
  assert.equal(pickVoices(voices).heater.name, "Microsoft Ryan Online (Natural)", "the existing picker's choice");
  const { heater, frost, ref } = pickCastVoices(voices);
  assert.equal(heater.name, "Microsoft Guy Online (Natural)");
  assert.equal(frost.name, "Microsoft Ryan Online (Natural)");
  assert.equal(ref.name, "Microsoft Libby Online (Natural)");
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
  assert.ok(at("if (st.first) { f.enter();") < at('convoBubble("frost", st.text)'));
  // poses: challenging while he asks (Heater listens), evidence with the chip, unconvinced into the
  // Ref, his verdict pose at the stamp, then both idle at the end
  assert.ok(at('f.setState("challenging")') < at('h.setState("listening")'));
  assert.ok(at('f.setState("evidence")') < at("convoChip(st.chip)"));
  assert.ok(at("sleep(CHIP_PAUSE_MS)") > at("convoChip(st.chip)"));
  assert.match(JS, /const CHIP_PAUSE_MS = 1200;/);
  assert.ok(at('f.setState("unconvinced")') > at('st.kind === "ruling"'));
  assert.ok(at("state.exchangeRunning = false;") > at('st.kind === "stamp"'), "Space stops working once the stamp lands");
  assert.ok(at("f.setState(show.frostEnd)") > at('st.kind === "stamp"'));
  assert.ok(at('f.setState("idle");\n    h.setState("idle");') > at('st.kind === "reaction"'));
});

test("rehearsal fix 2: the thread follows each line, chips fold at the ruling, and the Ref card and stamp are scrolled into view", () => {
  const src = fnBody("runExchange");
  const at = (s) => { const i = src.indexOf(s); assert.ok(i >= 0, s); return i; };
  assert.ok(at('keepInView(convoBubble("frost", st.text))') > at('st.kind === "question"'));
  assert.ok(at("keepInView(convoChip(st.chip))") > at('st.kind === "chip"'));
  const ruling = at('st.kind === "ruling"');
  const stamp = at('st.kind === "stamp"');
  const reaction = at('st.kind === "reaction"');
  assert.ok(at('ui.convo.classList.add("settled")') > ruling);
  const views = [...src.matchAll(/keepInView\(ui\.ref, "end"\)/g)].map((m) => m.index);
  assert.ok(views.some((i) => i > ruling && i < stamp), "when the card lands");
  assert.ok(views.some((i) => i > stamp && i < reaction), "when the stamp lands");
  assert.ok(views.some((i) => i > reaction), "after each reaction (it lands above the card)");
  assert.match(JS, /el\?\.scrollIntoView\?\.\(\{ block, behavior: reduce \? "auto" : "smooth" \}\)/);
  assert.match(CSS, /body\[data-cast="frost"\] \.ref \{ scroll-margin-bottom: calc\(var\(--ru-h\) \+ 64px\);/, "clear of the fixed footer");
  assert.match(CSS, /body\[data-cast="frost"\] \.ref\.slammed \{ margin-bottom: 56px; \}/, "room under the card for the hanging stamp");
  assert.match(CSS, /\.convo\.settled \.cv-chip \{ white-space: nowrap; overflow: hidden; text-overflow: ellipsis;/);
  assert.match(JS, /ui\.convo\.classList\.remove\("settled"\);/, "reset unfolds them");
});

test("a chip is its own item on Frost's side, with no voice; the tooltip holds its full text and source", () => {
  const i = JS.indexOf("function convoChip(");
  const src = JS.slice(i, JS.indexOf("\n}\n", i));
  assert.match(src, /li\.className = `cv-chip \$\{chip\.kind\}`/);
  assert.match(src, /li\.title = chip\.source \? `\$\{chip\.text\} \(source: \$\{chip\.source\}\)` : chip\.text;/);
  assert.match(src, /li\.tabIndex = 0;/);
  assert.ok(!/speak/.test(src));
});

test("a result chip reads as a fact, not a speaker: centred, grey, no tail, smaller, ice border only", () => {
  const i = CSS.indexOf(".cv-chip {");
  const rule = CSS.slice(i, CSS.indexOf("}", i));
  assert.match(rule, /align-self: center;/, "centred in the thread");
  assert.match(rule, /color: #9B97AD;/, "grey text");
  assert.match(rule, /background: rgba\(255, 255, 255, \.045\);/, "subtle dark background");
  assert.match(rule, /border-left: 3px solid var\(--ice\);/, "ice-blue left border");
  const size = Number(rule.match(/font-size: (\d+)px/)[1]);
  const bubble = Number(CSS.match(/\.cv-text \{[^}]*font-size: (\d+)px/)[1]);
  assert.ok(size < bubble && size >= bubble - 3, `slightly smaller than the bubbles (${size} vs ${bubble})`);
  assert.ok(!/\.cv-chip::(before|after)/.test(CSS), "no bubble tail");
  assert.ok(!/\.cv-chip\.(pass|fail|info)\s*\{/.test(CSS), "the border is the only colour: no pass/fail colours");
  assert.ok(!/class(Name)? = [^;]*\bcv\b[^-]/.test(JS.slice(JS.indexOf("function convoChip("), JS.indexOf("\n}\n", JS.indexOf("function convoChip(")))), "not a .cv bubble");
});

test("ask() runs the Frost exchange only when the answer has one; otherwise the Heater-only flow is unchanged", () => {
  const src = fnBody("ask");
  assert.ok(src.indexOf("if (a.exchange) {") < src.indexOf("// 1. Heater's hot take"));
  assert.match(src, /if \(a\.exchange\) \{[\s\S]*?await runExchange\(\{ \.\.\.a\.exchange, heaterReaction \}, \{[\s\S]*?frostEnd: frostEndState\(decision\),[\s\S]*?return;\s*\}/);
});

test("rehearsal fix 3: a market card with Frost's challenges runs the same sequence; without them, the old card flow", () => {
  const src = fnBody("askMarket");
  const at = (s) => { const i = src.indexOf(s); assert.ok(i >= 0, s); return i; };
  assert.ok(at("const exchange = exchangeFromApi(resp, { take });") < at("ui.take.textContent = take;"));
  assert.match(src, /if \(exchange\) \{\s*await runExchange\(\{ \.\.\.exchange, heaterReaction: marketReaction\(split, resp\) \}, \{/);
  for (const s of ["refLine: () => marketRefPlain(resp)", "stamp: marketStamp(resp)", "heaterEnd: marketEndState(resp)",
    "frostEnd: frostEndState(resp.verdict)", "evidence: () => marketDetails(resp)"]) assert.ok(at(s) < at("ui.take.textContent = take;"), s);
  assert.ok(at("return;") < at("ui.take.textContent = take;"), "the old flow does not run after the exchange");
  // Max's /api/investigate answer shape (docs/DIALOGUE_API.md): the same list and reaction as the dialogue
  const card = { frost: [{ check: "model_bias", question: "Q?", chip: "The calibration note says so.", source: "calibration" }],
    frost_reaction: "Worth a look. Not proof." };
  const ex = exchangeFromApi(card, { take: "Bulls at 36.4%." });
  assert.deepEqual(exchangeSteps({ ...ex, heaterReaction: "Fair call." }).map((s) => s.kind),
    ["take", "question", "chip", "ruling", "stamp", "reaction", "reaction"]);
  assert.equal(frostEndState("Worth investigating · Edge unverified"), "unconvinced");
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
  // big figures (8 Nov): both characters span both rows (the ask box sits under the conversation)
  assert.match(CSS, /body\[data-cast="frost"\] \.stage \{\s*grid-template-columns: [^;]+;\s*grid-template-areas: "hero talk frost" "hero ask frost";/);
  assert.match(CSS, /grid-template-areas: "hero frost" "talk talk" "ask ask";/);
  assert.match(CSS, /\.cv-heater::before \{ left: -24px;/, "Heater's tail points left");
  assert.match(CSS, /\.cv-frost::before \{ right: -24px;/, "Frost's tail points right");
  // the middle column keeps at least 560 px (640 on wide screens); each side column is a size container
  // that clips, and a figure is at most 88% of the viewport height and 165% of its column width
  assert.match(CSS, /grid-template-columns: minmax\(0, 1fr\) minmax\(560px, clamp\(560px, 100vw - 1280px, 640px\)\) minmax\(0, 1fr\);/);
  assert.match(CSS, /body\[data-cast="frost"\] \.hero, \.frost-side \{\s*--fig-h: min\(88vh, calc\(100vh - var\(--ru-h\) - 96px\), 165cqw\);\s*container-type: inline-size;[^}]*overflow: clip;/);
  assert.match(CSS, /body\[data-cast="frost"\] #heater, body\[data-cast="frost"\] #frost \{ position: sticky; bottom: var\(--ru-h\); \}/, "figures stand above the footer");
  assert.match(CSS, /body\[data-cast="frost"\] \.hero \.h-root \{ height: var\(--fig-h\);/);
  assert.match(CSS, /\.f-root \{[^}]*height: var\(--fig-h, /);
  assert.match(CSS, /@media \(max-width: 900px\) \{\s*\/\* small portraits/);
  assert.match(CSS, /\.cv-heater \{[^}]*border: 3px solid #FF7A1A/);
  assert.match(CSS, /\.cv-frost \{[^}]*border: 2px solid var\(--ice\)/);
  assert.match(CSS, /\.f-root \{[^}]*transform: translateX\(40px\); opacity: 0;/, "Frost waits to slide in");
  assert.match(CSS, /\.f-root\.entered \{ transform: none; opacity: 1; \}/);
  assert.match(CSS, /body\[data-cast="frost"\] \.ref \{ margin: 18px auto 0;/, "the Ref's card is centred");
});

test("name labels: HEATER in Oswald orange, FROST in Nunito ice blue, 44 px, glow; fonts from Google Fonts", () => {
  assert.match(HTML, /<section class="hero" aria-label="Heater">\s*<p class="cast-name heater-name" aria-hidden="true">Heater<\/p>/);
  assert.match(HTML, /<section class="frost-side"[^>]*>\s*<p class="cast-name frost-name" aria-hidden="true">Frost<\/p>/);
  assert.match(HTML, /<link rel="stylesheet" href="https:\/\/fonts\.googleapis\.com\/css2\?family=Nunito:wght@700&family=Oswald:wght@700&display=swap">/);
  assert.match(CSS, /\.cast-name \{ display: none; \}/, "only with both characters on stage");
  assert.match(CSS, /body\[data-cast="frost"\] \.cast-name \{[^}]*font-size: 44px;[^}]*text-transform: uppercase;/);
  assert.match(CSS, /\.heater-name \{[^}]*font-family: "Oswald"[^}]*font-weight: 700; letter-spacing: 4px;[^}]*color: #FF7A1A; text-shadow: 0 0 16px rgba\(255, 122, 26/);
  assert.match(CSS, /\.frost-name \{[^}]*font-family: "Nunito"[^}]*font-weight: 700;[^}]*color: #8FD3FF; text-shadow: 0 0 16px rgba\(143, 211, 255/);
});

test("the question as asked replaces the wordmark during an exchange; the wordmark is back on the home view", () => {
  assert.match(HTML, /<p class="brand">HEAT<span>CHECK<\/span><\/p>\s*<p class="asked" id="asked" hidden><\/p>/);
  assert.match(CSS, /\.asked \{[^}]*text-align: center;[^}]*font: 700 26px\/1\.25 system-ui[^}]*color: #ECEAF4;/);
  const fn = JS.slice(JS.indexOf("function showAsked("), JS.indexOf("\n}\n", JS.indexOf("function showAsked(")));
  assert.match(fn, /ui\.asked\.hidden = !text;\s*ui\.brand\.hidden = Boolean\(text\);/);
  const resetFn = JS.slice(JS.indexOf("function reset() {"), JS.indexOf("\n}\n", JS.indexOf("function reset() {")));
  assert.match(resetFn, /showAsked\(""\);/, "each exchange starts from the wordmark");
  assert.match(JS, /reset\(\);\s*showAsked\(question\);\s*voice\.stopSpeaking\(\);\s*log\(`question: \$\{question\}`\);/, "typed, chip or voice question");
  assert.match(JS, /reset\(\);\s*showAsked\(ASK_MESSAGE\);/, "a market card's Ask");
  assert.match(JS, /if \(view !== "talk"\) \{[^}]*showAsked\(""\);/, "board and idea views show the wordmark");
  assert.ok(HTML.indexOf('id="btn-board"') > HTML.indexOf('id="asked"'), "view buttons stay on the right of the top bar");
});

test("Ref card: double-size badge, headline (ref_headline or verdict + title), explanation at 70%", async () => {
  const { refHeadline } = await import("../web/frost/frost-model.js");
  assert.equal(refHeadline("X FROM MAX", { verdict: "NOT_SUPPORTED", claimId: "CONF-HH" }), "X FROM MAX", "Max's field wins");
  // Max's patterns (heatcheck/api/display_titles.py, e031a91), for answers without the field
  assert.equal(refHeadline(undefined, { verdict: "INSUFFICIENT_EVIDENCE", claimId: "CONF-HH", title: "x" }), "NOT ENOUGH EVIDENCE: HOT HAND NOT SHOWN");
  assert.equal(refHeadline(null, { verdict: "SURVIVED_PROTOCOL", claimId: "CONF-HA" }), "SURVIVED: HOME ADVANTAGE HOLDS UP");
  assert.equal(refHeadline(null, { verdict: "NOT_SUPPORTED", claimId: "GP-REST" }), "NOT SUPPORTED: REST AND BACK-TO-BACKS DOESN'T SHOW");
  assert.equal(refHeadline(null, { verdict: "DATA_INVALID", claimId: "CONF-HH" }), "DATA INVALID: NO RULING");
  assert.equal(refHeadline(null, { verdict: null, claimId: "NONE" }), "NO TEST: NO RULING");
  // market cards (no pattern from Max) and other cards: stamp words and title
  assert.equal(refHeadline(null, { title: "Nets at Hawks · forecast vs. market", stampText: "Sample" }), "Sample — Nets at Hawks · forecast vs. market");
  assert.equal(refHeadline("  ", { title: "Tamper test" }), "Tamper test");
  assert.match(HTML, /<header><span class="ref-badge">THE REF<\/span><\/header>\s*<p class="ref-title ref-headline" id="ref-title"><\/p>\s*<p class="ref-text" id="ref-text"><\/p>/);
  assert.match(CSS, /\.ref-badge \{ font: 700 1\.56rem\/1 var\(--mono\);/, "double the old .78rem");
  assert.match(CSS, /\.ref-headline \{[^}]*font: 700 30px\/1\.15 var\(--cond\); text-transform: uppercase; color: #2EC4B6;/);
  assert.match(CSS, /\.ref-text \{[^}]*font: 500 22px\/1\.4 [^}]*opacity: \.7;/);
  assert.match(JS, /refHeadline: forced \? null : api\?\.ref_headline \?\? null,/);
  assert.match(JS, /ui\.refTitle\.textContent = refHeadline\(show\.headline, \{ verdict: show\.verdict, claimId: show\.claimId, title: show\.title, stampText: show\.stamp\.text \}\);/);
  assert.match(JS, /headline: a\.refHeadline, verdict: decision, claimId: a\.claimId,/);
  assert.match(JS, /headline: resp\.ref_headline,/);
});
