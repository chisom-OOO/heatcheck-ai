// Push-to-talk voice. Microphone opens only on an explicit press and is released on stop.
// Raw audio is never stored; server mode sends one WAV clip per command and keeps nothing.
export function createVoice({ onState, onTranscript, onStatus, onError, provider }) {
  let listening = false, rec = null, mediaRec = null, stream = null, chunks = [], tStop = 0, speaking = false;

  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;

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
      if (!SR) { onError("Browser speech recognition is not available here. Type the claim, or choose server transcription."); onState("ERROR"); return; }
      rec = new SR(); rec.lang = "en-US"; rec.interimResults = true; rec.maxAlternatives = 1; rec.continuous = false;
      let finalText = "";
      rec.onresult = (e) => {
        for (const r of e.results) if (r.isFinal) finalText = r[0].transcript;
        onStatus("Hearing: " + Array.from(e.results).map((r) => r[0].transcript).join(" "));
      };
      rec.onerror = (e) => { onError("Speech recognition error: " + e.error); onState("ERROR"); listening = false; setBtn(false); };
      rec.onend = () => {
        listening = false; setBtn(false);
        if (finalText) onTranscript(finalText.trim(), { provider: "browser", transcript_ms: Math.round(performance.now() - tStop) });
        else if (tStop) { onStatus("No speech captured. Microphone is off."); onState("IDLE"); }
      };
      try { rec.start(); } catch (e) { onError("Could not start speech recognition: " + e.message); onState("ERROR"); return; }
      listening = true; tStop = 0; setBtn(true); onState("LISTENING");
      onStatus("● Listening (browser speech service). Press again to stop.");
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

  return { toggle: () => (listening ? stop() : start()), speak, stopSpeaking, stopAll };
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
