// Push-to-talk voice. Microphone opens only on an explicit press and is released on stop.
// Default path in every browser (Max, 8 Nov 2026): record with getUserMedia, encode 16 kHz mono
// 16-bit PCM WAV here in the browser, POST it to /api/transcribe (Meta Voice Transcribe, key on the
// server). Raw audio is never stored, here or on the server. The browser's own speech recognition
// is only a fallback after a transcription failure.

// ---- status lines shown under the input (pure; tested in tests/voice.test.mjs)
export const MIC = {
  LISTENING: "Listening… tap again to stop",
  TRANSCRIBING: "Transcribing…",
  HEARD: "Check the question, edit it if needed, then press Ask",
  NO_SPEECH: "Didn't catch that",
  BLOCKED: "Mic blocked: allow it in site settings",
  NO_MIC: "No microphone found: plug one in or check your sound settings",
  SERVICE: "Voice service unavailable: type the question",
  SERVICE_FALLBACK: "Voice service unavailable: tap the mic again to use the browser's own speech recognition",
  TOO_LONG: "That recording is too long. Keep it under 30 seconds",
  BUSY: "Too many recordings in a minute. Wait a moment and try again",
  UNSUPPORTED: "Voice input needs microphone access, which this page can't get here: type the question",
  NOT_RESPONDING: "The browser's speech recognition isn't responding: type the question",
};
export const MAX_RECORD_MS = 30000;
export const TRANSCRIBE_URL = "/api/transcribe";

/** What this browser can do. Recording (the default) needs getUserMedia, MediaRecorder and Web
 *  Audio, which every current browser has, Opera included. Speech recognition is the fallback only;
 *  Opera and Brave expose it without running it, so they get no fallback. */
export function voiceSupport(win) {
  const nav = win?.navigator || {};
  const record = !!(nav.mediaDevices?.getUserMedia && win?.MediaRecorder && (win?.AudioContext || win?.webkitAudioContext));
  const SR = win?.SpeechRecognition || win?.webkitSpeechRecognition;
  const ua = String(nav.userAgent || "");
  const speech = !!SR && !/\bOPR\/|\bOpera\b/.test(ua) && !nav.brave;
  return { ok: record || speech, record, speech, SR: speech ? SR : null };
}

/** getUserMedia failure -> status line. */
export function mediaErrorMessage(name) {
  if (name === "NotAllowedError" || name === "SecurityError" || name === "PermissionDeniedError") return MIC.BLOCKED;
  if (name === "NotFoundError" || name === "OverconstrainedError" || name === "DevicesNotFoundError") return MIC.NO_MIC;
  if (name === "NotReadableError") return "The microphone is in use by another app: close it and try again";
  return `Microphone failed (${name || "unknown"}): type the question`;
}

/** /api/transcribe failure -> status line. ``fallback``: the next tap can use browser speech. */
export function transcribeErrorMessage(status, body, { fallback = false } = {}) {
  const code = body?.error;
  if (code === "NOTHING_HEARD" || status === 422) return MIC.NO_SPEECH;
  if (code === "TOO_LARGE" || status === 413) return MIC.TOO_LONG;
  if (code === "RATE_LIMITED" || status === 429) return MIC.BUSY;
  return fallback ? MIC.SERVICE_FALLBACK : MIC.SERVICE;
}

/** Whether a failure should switch the next tap to the browser's speech recognition. */
export function isServiceFailure(status, body) {
  const code = body?.error;
  if (["NOTHING_HEARD", "TOO_LARGE", "RATE_LIMITED", "BAD_AUDIO", "NO_AUDIO"].includes(code)) return false;
  return status === 0 || status >= 500 || code === "SERVICE_UNAVAILABLE" || code === "UPSTREAM_UNAVAILABLE";
}

/** SpeechRecognition (fallback) error code -> status line; null = say nothing (user stopped it). */
export function micErrorMessage(code) {
  switch (code) {
    case "not-allowed": case "service-not-allowed": return MIC.BLOCKED;
    case "no-speech": return MIC.NO_SPEECH;
    case "audio-capture": return MIC.NO_MIC;
    case "network": return MIC.SERVICE;
    case "aborted": return null;
    default: return `Voice input failed (${code || "unknown"}): type the question`;
  }
}

/** After browser recognition ends: null = transcript sent; undefined = error already shown. */
export function micEndMessage({ transcript, errored, started }) {
  if (transcript) return null;
  if (errored) return undefined;
  return started ? MIC.NO_SPEECH : MIC.NOT_RESPONDING;
}

/** 16-bit PCM mono WAV bytes from float samples in [-1, 1] at ``rate`` Hz. Pure. */
export function encodeWav(samples, rate = 16000) {
  const n = samples.length;
  const buf = new ArrayBuffer(44 + n * 2), v = new DataView(buf);
  const w = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
  w(0, "RIFF"); v.setUint32(4, 36 + n * 2, true); w(8, "WAVE"); w(12, "fmt ");
  v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true); v.setUint32(24, rate, true);
  v.setUint32(28, rate * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true);
  w(36, "data"); v.setUint32(40, n * 2, true);
  for (let i = 0; i < n; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    v.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return new Uint8Array(buf);
}

const START_TIMEOUT_MS = 4000;  // fallback speech: no "start" event by then means it isn't listening

export function createVoice({ onState, onTranscript, onStatus, onError, provider, fetchImpl, win = globalThis.window, maxRecordMs = MAX_RECORD_MS } = {}) {
  let listening = false, rec = null, mediaRec = null, stream = null, chunks = [], tStop = 0, speaking = false;
  let useSpeechNext = false, autoStop = 0;
  const support = voiceSupport(win);
  const doFetch = fetchImpl || ((...a) => fetch(...a));

  function stopSpeaking() {
    if (win?.speechSynthesis) win.speechSynthesis.cancel();
    if (speaking) { speaking = false; onState("IDLE"); }
  }

  function speak(text) {
    if (!win?.speechSynthesis || listening) return;
    win.speechSynthesis.cancel();
    const u = new win.SpeechSynthesisUtterance(text);
    u.rate = 1.03;
    u.onstart = () => { speaking = true; onState("SPEAKING"); };
    u.onend = u.onerror = () => { if (speaking) { speaking = false; onState("IDLE"); } };
    win.speechSynthesis.speak(u);
  }

  function releaseMic() {
    if (stream) stream.getTracks().forEach((t) => t.stop());
    stream = null;
  }

  // Which path this press uses. app.js may still pass provider() ("browser" | "server").
  function mode() {
    const asked = provider?.();
    if (asked === "browser" && support.speech) return "browser";
    if (useSpeechNext && support.speech) return "browser";
    if (support.record) return "server";
    return support.speech ? "browser" : "none";
  }

  function start() {
    stopSpeaking();                                       // barge-in: talking interrupts speech
    const m = mode();
    if (m === "none") { onError(MIC.UNSUPPORTED); onState("ERROR"); return; }
    if (m === "browser") return startBrowser();
    return startServer();
  }

  // ---- default: record, encode WAV, server transcription
  async function startServer() {
    listening = true; setBtn(true); onState("LISTENING"); onStatus(MIC.LISTENING);
    try {
      stream = await win.navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
    } catch (e) {
      listening = false; setBtn(false); onError(mediaErrorMessage(e?.name)); onState("ERROR"); return;
    }
    if (!listening) { releaseMic(); return; }               // stopped while the permission prompt was open
    chunks = [];
    mediaRec = new win.MediaRecorder(stream);
    mediaRec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
    mediaRec.onstop = () => { clearTimeout(autoStop); releaseMic(); finishServer(); };
    mediaRec.start();
    tStop = 0;
    autoStop = setTimeout(() => { if (listening) stop(); }, maxRecordMs);
  }

  async function finishServer() {
    const blob = new Blob(chunks); chunks = [];
    if (!blob.size) { onError(MIC.NO_SPEECH); onState("IDLE"); return; }
    onState("TRANSCRIBING"); onStatus(MIC.TRANSCRIBING);
    let wav;
    try {
      wav = await toWav16k(blob, win);
    } catch {
      onError(MIC.NO_SPEECH); onState("IDLE"); return;      // nothing decodable was recorded
    }
    let status = 0, body = null;
    try {
      const r = await doFetch(TRANSCRIBE_URL, { method: "POST", headers: { "Content-Type": "audio/wav" }, body: wav });
      status = r.status;
      try { body = await r.json(); } catch { body = null; }
    } catch { status = 0; }
    if (status === 200 && typeof body?.transcript === "string" && body.transcript.trim()) {
      useSpeechNext = false;
      onTranscript(body.transcript.trim(), { provider: body.provider || "server", transcript_ms: Math.round(performance.now() - tStop), provider_ms: body.provider_ms });
      return;
    }
    const fallback = isServiceFailure(status, body) && support.speech;
    if (fallback) useSpeechNext = true;
    onError(transcribeErrorMessage(status, body, { fallback })); onState("IDLE");
  }

  // ---- fallback: the browser's own speech recognition
  function startBrowser() {
    useSpeechNext = false;
    const r0 = new support.SR(); rec = r0; r0.lang = "en-US"; r0.interimResults = true; r0.maxAlternatives = 1; r0.continuous = false;
    let finalText = "", started = false, errored = false, watchdog = 0;
    r0.onstart = r0.onaudiostart = () => { started = true; };
    r0.onresult = (e) => {
      for (const r of e.results) if (r.isFinal) finalText = r[0].transcript;
      onStatus("Hearing: " + Array.from(e.results).map((r) => r[0].transcript).join(" "));
    };
    r0.onerror = (e) => {
      errored = true;
      const m = micErrorMessage(e.error);
      if (m) { onError(m); onState("ERROR"); } else onState("IDLE");
      listening = false; setBtn(false);
    };
    r0.onend = () => {
      clearTimeout(watchdog);
      if (rec === r0) rec = null;
      listening = false; setBtn(false);
      const text = finalText.trim();
      const m = micEndMessage({ transcript: text, errored, started });
      if (text) onTranscript(text, { provider: "browser", transcript_ms: Math.round(performance.now() - tStop) });
      else if (m) { onError(m); onState("IDLE"); }
    };
    // start() runs synchronously inside the press handler, so the browser keeps the user gesture.
    try { r0.start(); } catch (e) { onError(`Voice input failed (${e.name}): type the question`); onState("ERROR"); return; }
    watchdog = setTimeout(() => {
      if (started || rec !== r0) return;
      try { r0.abort(); } catch {}
      rec = null; listening = false; setBtn(false); onError(MIC.NOT_RESPONDING); onState("ERROR");
    }, START_TIMEOUT_MS);
    listening = true; tStop = 0; setBtn(true); onState("LISTENING");
    onStatus(MIC.LISTENING);
  }

  function stop() {
    tStop = performance.now();
    clearTimeout(autoStop);
    if (rec) { try { rec.stop(); } catch {} rec = null; }
    if (mediaRec && mediaRec.state !== "inactive") mediaRec.stop();
    mediaRec = null;
    listening = false; setBtn(false);
  }

  function stopAll() {
    clearTimeout(autoStop);
    if (rec) { try { rec.abort(); } catch {} rec = null; }
    if (mediaRec && mediaRec.state !== "inactive") { mediaRec.onstop = null; mediaRec.stop(); }
    mediaRec = null; chunks = []; releaseMic(); stopSpeaking();
    listening = false; setBtn(false); onStatus(""); onState("STOPPED");
  }

  function setBtn(on) {
    const b = win?.document?.getElementById("btn-mic");
    if (!b) return;
    b.setAttribute("aria-pressed", String(on));
    b.textContent = on ? "■ Stop listening" : "🎙 Push to talk";
  }

  return {
    toggle: () => (listening ? stop() : start()),
    start: () => { if (!listening) start(); },
    stop: () => { if (listening) stop(); },
    isListening: () => listening,
    speak, stopSpeaking, stopAll, support,
  };
}

/** Recorded clip (any format the browser recorded) -> 16 kHz mono 16-bit PCM WAV blob. */
async function toWav16k(blob, win) {
  const AC = win.AudioContext || win.webkitAudioContext;
  const ac = new AC();
  const decoded = await ac.decodeAudioData(await blob.arrayBuffer());
  await ac.close();
  const rate = 16000;
  const off = new win.OfflineAudioContext(1, Math.max(1, Math.ceil(decoded.duration * rate)), rate);
  const src = off.createBufferSource(); src.buffer = decoded; src.connect(off.destination); src.start();
  const pcm = (await off.startRendering()).getChannelData(0);
  return new Blob([encodeWav(pcm, rate)], { type: "audio/wav" });
}
