// Run from apps/web:  node --test tests/speech.test.mjs
//
// Heater.speak() with voice on must not wait forever. Headless Chromium (Max's demo.cmd run on
// 2026-11-07, reports/max/2026-11-07-demo-e2e) showed the Ref's line but never the stamp: the stamp
// is set after `await speak(refLine)`, and that browser's speech never reported an end. These tests
// use a fake speechSynthesis that never fires onend or onerror, and mocked timers; no browser.
import assert from "node:assert/strict";
import { mock, test } from "node:test";

import { Heater } from "../web/heater/heater.js";
import { SPEECH_GRACE_MS, VOICE, fallbackSpeechMs, speechGuardMs } from "../web/heater/heater-model.js";

const fakeRoot = () => ({
  classList: { add() {}, remove() {}, toggle() {} },
  querySelectorAll: () => [],
  querySelector: () => null,
});

function silentSynth() {
  const spoken = [];
  return { spoken, speak: (u) => spoken.push(u), cancel() {}, getVoices: () => [] };
}

function withSpeech(synth, fn) {
  const old = { s: globalThis.speechSynthesis, u: globalThis.SpeechSynthesisUtterance };
  globalThis.speechSynthesis = synth;
  globalThis.SpeechSynthesisUtterance = class { constructor(text) { this.text = text; } };
  mock.timers.enable({ apis: ["setTimeout", "setInterval"] });
  return Promise.resolve(fn()).finally(() => {
    mock.timers.reset();
    globalThis.speechSynthesis = old.s;
    globalThis.SpeechSynthesisUtterance = old.u;
  });
}

const REF_LINE = "Can't compare: the forecast is a SAMPLE with made-up numbers.";

test("the guard is the fallback duration plus a fixed grace", () => {
  assert.equal(speechGuardMs(REF_LINE, VOICE.ref.rate), fallbackSpeechMs(REF_LINE, VOICE.ref.rate) + SPEECH_GRACE_MS);
  assert.equal(SPEECH_GRACE_MS, 2500);
});

test("voice on, speech never ends: speak() still resolves at the guard, not before", () => withSpeech(silentSynth(), async () => {
  const h = new Heater(fakeRoot());
  let resolved = false;
  const p = h.speak(REF_LINE, "ref", { voiceOn: true }).then(() => { resolved = true; });
  const guard = speechGuardMs(REF_LINE, VOICE.ref.rate);
  mock.timers.tick(guard - 1);
  await Promise.resolve();
  assert.equal(resolved, false, "resolved before the guard");
  mock.timers.tick(1);
  await p;
  assert.equal(resolved, true);
  assert.equal(h.speaking, null);
}));

test("voice on, speech ends normally: speak() resolves at onend and the guard does nothing later", () => withSpeech(silentSynth(), async () => {
  const synth = globalThis.speechSynthesis;
  const h = new Heater(fakeRoot());
  let count = 0;
  const p = h.speak(REF_LINE, "ref", { voiceOn: true }).then(() => { count += 1; });
  assert.equal(synth.spoken.length, 1);
  synth.spoken[0].onend();
  await p;
  assert.equal(count, 1);
  h.speaking = "next line";  // a later line has started
  mock.timers.tick(speechGuardMs(REF_LINE, VOICE.ref.rate) + 10);
  await Promise.resolve();
  assert.equal(h.speaking, "next line", "the old guard must not clear a later line");
}));

test("a market answer's stamp is set after the Ref's line, so it shows even when speech never ends", () => withSpeech(silentSynth(), async () => {
  // The order demo.js askMarket uses: speak the Ref line, then show the stamp.
  const h = new Heater(fakeRoot());
  const stamp = { hidden: true, textContent: "" };
  const run = (async () => {
    await h.speak(REF_LINE, "ref", { voiceOn: true });
    stamp.textContent = "SAMPLE";
    stamp.hidden = false;
  })();
  mock.timers.tick(speechGuardMs(REF_LINE, VOICE.ref.rate));
  await run;
  assert.deepEqual(stamp, { hidden: false, textContent: "SAMPLE" });
}));
