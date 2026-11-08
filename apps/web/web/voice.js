// Push-to-talk voice. Microphone opens only on an explicit press and is released on stop.
// Raw audio is never stored; server mode sends one WAV clip per command and keeps nothing.

// ---- status lines shown under the input (pure; tested in tests/voice.test.mjs)
export const MIC = {
  LISTENING: "Listening…",
  NO_SPEECH: "Didn't catch that",
  BLOCKED: "Mic blocked: allow it in site settings",
  UNSUPPORTED: "Voice input not supported in this browser, use Edge or Chrome",
  NO_MIC: "No microphone found: plug one in or check your sound settings",
  NETWORK: "Voice service unreachable: check your connection, or type the question",
  NOT_RESPONDING: "Voice input isn't responding in this browser, use Edge or Chrome",
};

/** Whether this browser's speech recognition can be used. Opera and Brave expose the API but do not
 *  run it (no prompt, no events), and Firefox has none; those get the unsupported message. */
export function voiceSupport(win) {
  const SR = win?.SpeechRecognition || win?.webkitSpeechRecognition;
  const ua = String(win?.navigator?.userAgent || "");
  if (!SR) return { ok: false, reason: "no SpeechRecognition" };
  if (/\bOPR\/|\bOpera\b/.test(ua)) return { ok: false, reason: "Opera" };
  if (win?.navigator?.brave) return { ok: false, reason: "Brave" };
  return { ok: true, SR };
}

/** SpeechRecognition error code -> status line; null = say nothing (the user stopped it). */
export function micErrorMessage(code) {
  switch (code) {
    case "not-allowed": case "service-not-allowed": return MIC.BLOCKED;
    case "no-speech": return MIC.NO_SPEECH;
    case "audio-capture": return MIC.NO_MIC;
    case "network": return MIC.NETWORK;
    case "aborted": return null;
    default: return `Voice input failed (${code || "unknown"}): type the question instead`;
  }
}

/** After recognition ends: what to show. A transcript is sent as a question (null); after an error
 *  its message stays (undefined); an end with no result and no error says so. */
export function micEndMessage({ transcript, errored, started }) {
  if (transcript) return null;
  if (errored) return undefined;
  return started ? MIC.NO_SPEECH : MIC.NOT_RESPONDING;
}

const START_TIMEOUT_MS = 4000;              // no "start" event by then: the browser is not listening
export function createVoice({ onState, onTranscript, onStatus, onError, provider }) {
  let listening = false, rec = null, mediaRec = null, stream = null, chunks = [], tStop = 0, speaking = false;

  const support = voiceSupport(window);
  const SR = support.ok ? support.SR : null;

  function stopSpeaking() {
    if (window.speechSynthesis) speechSynthesis.cancel();
    if (speaking) { speaking = false; onState("IDLE"); }
  }

  function speak(text) {
    if (!window.speechSynthesis || listening) return;
    speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.rate = 1.03;
    u.onstart = () => { speaking = true; onState("SPEAKING"); };
    u.onend = u.onerror = () => { if (speaking) { speaking = false; onState("IDLE"); } };
    speechSynthesis.speak(u);
  }

  function releaseMic() {
    if (stream) stream.getTracks().forEach((t) => t.stop());
    stream = null;
  }

  async function start() {
    stopSpeaking();                                       // barge-in: talking interrupts speech
    const mode = provider();
    if (mode === "browser") {
      if (!SR) { onError(MIC.UNSUPPORTED); onState("ERROR"); return; }
      const r0 = new SR(); rec = r0; r0.lang = "en-US"; r0.interimResults = true; r0.maxAlternatives = 1; r0.continuous = false;
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
      // start() runs synchronously inside the click handler (no await before it), so the
      // browser keeps the user gesture and can show its microphone prompt.
      try { r0.start(); } catch (e) { onError(`Voice input failed (${e.name}): type the question instead`); onState("ERROR"); return; }
      watchdog = setTimeout(() => {
        if (started || rec !== r0) return;
        try { r0.abort(); } catch {}
        rec = null; listening = false; setBtn(false); onError(MIC.NOT_RESPONDING); onState("ERROR");
      }, START_TIMEOUT_MS);
      listening = true; tStop = 0; setBtn(true); onState("LISTENING");
      onStatus(MIC.LISTENING);
      return;
    }
    try { stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true } }); }
    catch (e) { onError("Microphone permission was not granted (" + e.name + ")."); onState("ERROR"); return; }
    chunks = [];
    mediaRec = new MediaRecorder(stream);
    mediaRec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
    mediaRec.onstop = async () => {
      releaseMic();
      onState("TRANSCRIBING"); onStatus("Transcribing on the server… microphone is off.");
      try {
        const wav = await toWav16k(new Blob(chunks));
        chunks = [];
        const r = await fetch("/api/transcribe", { method: "POST", headers: { "Content-Type": "audio/wav" }, body: wav });
        const d = await r.json();
        if (!r.ok) throw new Error(d.message || r.statusText);
        onTranscript(d.transcript.trim(), { provider: d.provider, transcript_ms: Math.round(performance.now() - tStop), provider_ms: d.provider_ms });
      } catch (e) { onError("Transcription unavailable: " + e.message); onState("ERROR"); }
    };
    mediaRec.start();
    listening = true; tStop = 0; setBtn(true); onState("LISTENING");
    onStatus("● Recording one command for server transcription. Press again to stop.");
  }

  function stop() {
    tStop = performance.now();
    if (rec) { try { rec.stop(); } catch {} rec = null; }
    if (mediaRec && mediaRec.state !== "inactive") mediaRec.stop();
    mediaRec = null;
    listening = false; setBtn(false);
  }

  function stopAll() {
    if (rec) { try { rec.abort(); } catch {} rec = null; }
    if (mediaRec && mediaRec.state !== "inactive") { mediaRec.onstop = null; mediaRec.stop(); }
    mediaRec = null; chunks = []; releaseMic(); stopSpeaking();
    listening = false; setBtn(false); onStatus("Stopped. Microphone is off; nothing is being recorded."); onState("STOPPED");
  }

  function setBtn(on) {
    const b = document.getElementById("btn-mic");
    b.setAttribute("aria-pressed", String(on));
    b.textContent = on ? "■ Stop listening" : "🎙 Push to talk";
  }

  return { toggle: () => (listening ? stop() : start()), speak, stopSpeaking, stopAll, support };
}

// Decode the recorded clip and re-encode as 16 kHz mono 16-bit PCM WAV (what the Meta file endpoint accepts).
async function toWav16k(blob) {
  const ac = new AudioContext();
  const decoded = await ac.decodeAudioData(await blob.arrayBuffer());
  await ac.close();
  const rate = 16000;
  const off = new OfflineAudioContext(1, Math.ceil(decoded.duration * rate), rate);
  const src = off.createBufferSource(); src.buffer = decoded; src.connect(off.destination); src.start();
  const pcm = (await off.startRendering()).getChannelData(0);
  const buf = new ArrayBuffer(44 + pcm.length * 2), v = new DataView(buf);
  const w = (o, s) => [...s].forEach((c, i) => v.setUint8(o + i, c.charCodeAt(0)));
  w(0, "RIFF"); v.setUint32(4, 36 + pcm.length * 2, true); w(8, "WAVE"); w(12, "fmt ");
  v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true); v.setUint32(24, rate, true);
  v.setUint32(28, rate * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true); w(36, "data"); v.setUint32(40, pcm.length * 2, true);
  for (let i = 0; i < pcm.length; i++) v.setInt16(44 + i * 2, Math.max(-1, Math.min(1, pcm[i])) * 0x7fff, true);
  return new Blob([buf], { type: "audio/wav" });
}
