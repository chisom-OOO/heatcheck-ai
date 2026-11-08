// Voice input (Max, 8 Nov 2026): server transcription by default in every browser, browser speech
// only as a fallback; WAV encoding; every failure gives a visible line.
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  MAX_RECORD_MS, MIC, TRANSCRIBE_URL, createVoice, encodeWav, isServiceFailure, mediaErrorMessage,
  micEndMessage, micErrorMessage, transcribeErrorMessage, voiceSupport,
} from "../web/voice.js";

const CHROME = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36";
const OPERA = CHROME + " OPR/115.0.0.0";
const FIREFOX = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0";
function SR() {}
const media = { getUserMedia() {} };

test("support: recording works in Opera, Firefox and Chrome; speech is only a fallback where it runs", () => {
  const rec = { MediaRecorder: function () {}, AudioContext: function () {} };
  const opera = voiceSupport({ ...rec, webkitSpeechRecognition: SR, navigator: { userAgent: OPERA, mediaDevices: media } });
  assert.deepEqual([opera.ok, opera.record, opera.speech], [true, true, false]);
  const ff = voiceSupport({ ...rec, navigator: { userAgent: FIREFOX, mediaDevices: media } });
  assert.deepEqual([ff.ok, ff.record, ff.speech], [true, true, false]);
  const chrome = voiceSupport({ ...rec, SpeechRecognition: SR, navigator: { userAgent: CHROME, mediaDevices: media } });
  assert.deepEqual([chrome.ok, chrome.record, chrome.speech], [true, true, true]);
  assert.equal(voiceSupport({ navigator: { userAgent: FIREFOX } }).ok, false);   // no mic API at all
});

test("no 'not supported in this browser' line for Opera any more", () => {
  assert.doesNotMatch(MIC.UNSUPPORTED, /browser, use Edge or Chrome/);
});

test("encodeWav: 16 kHz mono 16-bit PCM header and samples, clamped", () => {
  const b = encodeWav(new Float32Array([0, 1, -1, 2, -2]), 16000);
  const v = new DataView(b.buffer);
  const str = (o, n) => String.fromCharCode(...b.slice(o, o + n));
  assert.equal(b.length, 44 + 5 * 2);
  assert.deepEqual([str(0, 4), str(8, 4), str(12, 4), str(36, 4)], ["RIFF", "WAVE", "fmt ", "data"]);
  assert.equal(v.getUint16(20, true), 1);       // PCM
  assert.equal(v.getUint16(22, true), 1);       // mono
  assert.equal(v.getUint32(24, true), 16000);   // sample rate
  assert.equal(v.getUint32(28, true), 32000);   // byte rate
  assert.equal(v.getUint16(34, true), 16);      // bits per sample
  assert.equal(v.getUint32(40, true), 10);      // data bytes
  assert.deepEqual([0, 1, 2, 3, 4].map((i) => v.getInt16(44 + i * 2, true)), [0, 32767, -32768, 32767, -32768]);
});

test("every failure has a clear line", () => {
  assert.equal(mediaErrorMessage("NotAllowedError"), MIC.BLOCKED);
  assert.equal(MIC.BLOCKED, "Mic blocked: allow it in site settings");
  assert.equal(mediaErrorMessage("NotFoundError"), MIC.NO_MIC);
  assert.equal(transcribeErrorMessage(422, { error: "NOTHING_HEARD" }), MIC.NO_SPEECH);
  assert.equal(MIC.NO_SPEECH, "Didn't catch that");
  assert.equal(transcribeErrorMessage(413, { error: "TOO_LARGE" }), MIC.TOO_LONG);
  assert.equal(transcribeErrorMessage(429, { error: "RATE_LIMITED" }), MIC.BUSY);
  assert.equal(transcribeErrorMessage(502, { error: "SERVICE_UNAVAILABLE" }), MIC.SERVICE);
  assert.equal(transcribeErrorMessage(0, null, { fallback: true }), MIC.SERVICE_FALLBACK);
  assert.equal(isServiceFailure(503, { error: "SERVICE_UNAVAILABLE" }), true);
  assert.equal(isServiceFailure(0, null), true);
  assert.equal(isServiceFailure(422, { error: "NOTHING_HEARD" }), false);
  assert.equal(micErrorMessage("not-allowed"), MIC.BLOCKED);
  assert.equal(micErrorMessage("aborted"), null);
  assert.equal(micEndMessage({ transcript: "", errored: false, started: true }), MIC.NO_SPEECH);
});

// ---- createVoice with a fake browser
function harness({ fetchResponses = [], speech = true, gum = null, maxRecordMs } = {}) {
  const made = { sr: [], recorders: [], fetches: [], tracksStopped: 0 };
  class FakeSR { constructor() { made.sr.push(this); } start() { this.started = true; } stop() { this.onend?.(); } abort() { this.aborted = true; } }
  class FakeRecorder {
    constructor(stream) { this.stream = stream; this.state = "inactive"; made.recorders.push(this); }
    start() { this.state = "recording"; }
    stop() { this.state = "inactive"; this.ondataavailable?.({ data: new Blob([new Uint8Array(64)]) }); this.onstop?.(); }
  }
  const stream = { getTracks: () => [{ stop: () => made.tracksStopped++ }] };
  class FakeAC { decodeAudioData() { return Promise.resolve({ duration: 1.5 }); } close() { return Promise.resolve(); } }
  class FakeOffline {
    constructor(ch, len, rate) { this.len = len; this.rate = rate; }
    createBufferSource() { return { connect() {}, start() {} }; }
    startRendering() { return Promise.resolve({ getChannelData: () => new Float32Array(this.len) }); }
  }
  const win = {
    navigator: { userAgent: CHROME, mediaDevices: { getUserMedia: () => (gum ? Promise.reject(gum) : Promise.resolve(stream)) } },
    MediaRecorder: FakeRecorder, AudioContext: FakeAC, OfflineAudioContext: FakeOffline,
    ...(speech ? { webkitSpeechRecognition: FakeSR } : {}),
  };
  const out = { status: [], errors: [], transcripts: [] };
  const fetchImpl = async (url, init) => {
    made.fetches.push({ url, init });
    const [status, body] = fetchResponses.shift() || [200, { transcript: "spurs vs blazers" }];
    if (status === "throw") throw new TypeError("Failed to fetch");
    return { status, json: async () => body };
  };
  const v = createVoice({ win, fetchImpl, maxRecordMs, onState: () => {}, onStatus: (s) => out.status.push(s),
    onError: (e) => out.errors.push(e), onTranscript: (t) => out.transcripts.push(t) });
  return { v, made, out };
}
const settle = () => new Promise((r) => setTimeout(r, 0));
async function speakOnce(h) { h.v.start(); await settle(); h.v.stop(); for (let i = 0; i < 6; i++) await settle(); }

test("default path: record, encode WAV, POST to /api/transcribe, transcript back (not asked)", async () => {
  const h = harness();
  await speakOnce(h);
  assert.equal(h.made.sr.length, 0);                          // browser speech not used
  assert.equal(h.made.fetches.length, 1);
  const { url, init } = h.made.fetches[0];
  assert.equal(url, TRANSCRIBE_URL);
  assert.equal(init.headers["Content-Type"], "audio/wav");
  const bytes = new Uint8Array(await init.body.arrayBuffer());
  assert.equal(String.fromCharCode(...bytes.slice(0, 4)), "RIFF");
  assert.equal(new DataView(bytes.buffer).getUint32(24, true), 16000);
  assert.deepEqual(h.out.transcripts, ["spurs vs blazers"]);
  assert.ok(h.made.tracksStopped >= 1);                        // the mic is released
  assert.deepEqual(h.out.status.slice(0, 2), [MIC.LISTENING, MIC.TRANSCRIBING]);
});

test("service failure: clear line, and the next tap falls back to browser speech", async () => {
  const h = harness({ fetchResponses: [[502, { error: "SERVICE_UNAVAILABLE" }]] });
  await speakOnce(h);
  assert.deepEqual(h.out.errors, [MIC.SERVICE_FALLBACK]);
  h.v.start();
  assert.equal(h.made.sr.length, 1);                          // fallback used on the next press
  assert.equal(h.made.sr[0].started, true);
});

test("network failure with no browser speech: says type the question", async () => {
  const h = harness({ fetchResponses: [["throw"]], speech: false });
  await speakOnce(h);
  assert.deepEqual(h.out.errors, [MIC.SERVICE]);
});

test("nothing heard does not switch to the fallback", async () => {
  const h = harness({ fetchResponses: [[422, { error: "NOTHING_HEARD" }]] });
  await speakOnce(h);
  assert.deepEqual(h.out.errors, [MIC.NO_SPEECH]);
  h.v.start(); await settle();
  assert.equal(h.made.sr.length, 0);
  assert.equal(h.made.recorders.length, 2);                   // recorded again, server path
});

test("mic blocked shows the blocked line and records nothing", async () => {
  const h = harness({ gum: Object.assign(new Error("denied"), { name: "NotAllowedError" }) });
  h.v.start(); await settle(); await settle();
  assert.deepEqual(h.out.errors, [MIC.BLOCKED]);
  assert.equal(h.made.recorders.length, 0);
  assert.equal(h.v.isListening(), false);
});

test("recording stops by itself at the limit (30 s by default)", async () => {
  assert.equal(MAX_RECORD_MS, 30000);
  const h = harness({ maxRecordMs: 20 });
  h.v.start(); await settle();
  assert.equal(h.made.recorders[0].state, "recording");
  await new Promise((r) => setTimeout(r, 60));
  for (let i = 0; i < 6; i++) await settle();
  assert.equal(h.made.recorders[0].state, "inactive");
  assert.deepEqual(h.out.transcripts, ["spurs vs blazers"]);   // what was said is still transcribed
});
