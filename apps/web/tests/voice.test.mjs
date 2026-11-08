// Voice input: status lines, browser support, and that recognition starts inside the click.
// (Max, 8 Nov 2026, rehearsal bug: clicking the mic showed no prompt and nothing happened.)
import assert from "node:assert/strict";
import { test } from "node:test";

import { MIC, createVoice, micEndMessage, micErrorMessage, voiceSupport } from "../web/voice.js";

const CHROME = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36";
const EDGE = CHROME + " Edg/130.0.0.0";
const OPERA = CHROME + " OPR/115.0.0.0";
const FIREFOX = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0";
function SR() {}

test("the four requested status lines are exact", () => {
  assert.equal(MIC.LISTENING, "Listening…");
  assert.equal(MIC.NO_SPEECH, "Didn't catch that");
  assert.equal(MIC.BLOCKED, "Mic blocked: allow it in site settings");
  assert.equal(MIC.UNSUPPORTED, "Voice input not supported in this browser, use Edge or Chrome");
});

test("support: Edge and Chrome yes; Firefox (no API), Opera and Brave (API that never runs) no", () => {
  assert.equal(voiceSupport({ webkitSpeechRecognition: SR, navigator: { userAgent: EDGE } }).ok, true);
  assert.equal(voiceSupport({ SpeechRecognition: SR, navigator: { userAgent: CHROME } }).ok, true);
  assert.equal(voiceSupport({ navigator: { userAgent: FIREFOX } }).ok, false);
  assert.equal(voiceSupport({ webkitSpeechRecognition: SR, navigator: { userAgent: OPERA } }).ok, false);
  assert.equal(voiceSupport({ webkitSpeechRecognition: SR, navigator: { userAgent: CHROME, brave: {} } }).ok, false);
});

test("every error code becomes a visible line; only a user abort is silent", () => {
  assert.equal(micErrorMessage("not-allowed"), MIC.BLOCKED);
  assert.equal(micErrorMessage("service-not-allowed"), MIC.BLOCKED);
  assert.equal(micErrorMessage("no-speech"), MIC.NO_SPEECH);
  assert.equal(micErrorMessage("audio-capture"), MIC.NO_MIC);
  assert.equal(micErrorMessage("network"), MIC.NETWORK);
  assert.equal(micErrorMessage("aborted"), null);
  assert.match(micErrorMessage("language-not-supported"), /language-not-supported/);
});

test("ending with no result and no error is never silent", () => {
  assert.equal(micEndMessage({ transcript: "", errored: false, started: true }), MIC.NO_SPEECH);
  assert.equal(micEndMessage({ transcript: "", errored: false, started: false }), MIC.NOT_RESPONDING);
  assert.equal(micEndMessage({ transcript: "", errored: true, started: true }), undefined);
  assert.equal(micEndMessage({ transcript: "spurs vs blazers", errored: false, started: true }), null);
});

// ---- createVoice with a fake recognizer
function harness(userAgent = EDGE) {
  const made = [];
  class FakeSR {
    constructor() { this.started = false; made.push(this); }
    start() { this.started = true; }
    stop() { this.onend?.(); }
    abort() { this.aborted = true; }
  }
  const btn = { attrs: {}, textContent: "", setAttribute(k, v) { this.attrs[k] = v; } };
  globalThis.window = { webkitSpeechRecognition: FakeSR, navigator: { userAgent } };
  globalThis.document = { getElementById: () => btn };
  const out = { status: [], errors: [], transcripts: [], states: [] };
  const v = createVoice({
    provider: () => "browser",
    onState: (s) => out.states.push(s),
    onStatus: (s) => out.status.push(s),
    onError: (e) => out.errors.push(e),
    onTranscript: (t) => out.transcripts.push(t),
  });
  return { v, made, out, btn };
}

test("start() is called before the click handler returns (no await drops the gesture)", () => {
  const { v, made, out } = harness();
  v.toggle();                         // synchronous part of the click handler
  assert.equal(made.length, 1);
  assert.equal(made[0].started, true);
  assert.deepEqual(out.status, [MIC.LISTENING]);
});

test("blocked mic, silence, and a transcript each give the right result", () => {
  let h = harness();
  h.v.toggle(); const r = h.made[0];
  r.onstart(); r.onerror({ error: "not-allowed" }); r.onend();
  assert.deepEqual(h.out.errors, [MIC.BLOCKED]);

  h = harness();
  h.v.toggle(); h.made[0].onstart(); h.made[0].onend();
  assert.deepEqual(h.out.errors, [MIC.NO_SPEECH]);

  h = harness();
  h.v.toggle(); const r2 = h.made[0];
  r2.onstart();
  r2.onresult({ results: [Object.assign([{ transcript: "spurs vs trailblazers?" }], { isFinal: true })] });
  r2.onend();
  assert.deepEqual(h.out.transcripts, ["spurs vs trailblazers?"]);
  assert.deepEqual(h.out.errors, []);
});

test("a browser that never starts listening is told so, not left silent", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const h = harness();
  h.v.toggle();
  t.mock.timers.tick(4001);
  assert.equal(h.made[0].aborted, true);
  assert.deepEqual(h.out.errors, [MIC.NOT_RESPONDING]);
  assert.equal(h.btn.attrs["aria-pressed"], "false");
});

test("unsupported browser: toggle shows the unsupported line and creates no recognizer", () => {
  const h = harness(OPERA);
  assert.equal(h.v.support.ok, false);
  h.v.toggle();
  assert.equal(h.made.length, 0);
  assert.deepEqual(h.out.errors, [MIC.UNSUPPORTED]);
});
