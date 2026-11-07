// Heater rig controller: mount the SVG, run the state machine, speak, drive the speech card.
// Exposes mount(el) -> Heater with setState(name) and speak(text, who), plus renderCard()
// and playSequence(). The pure model lives in heater-model.js.

import {
  STATES, TIMING, VOICE, CHECKING_CHIP, cardModel, fallbackSpeechMs, isEmphasis, pickVoices, wordAt,
} from "./heater-model.js";

export { STATES } from "./heater-model.js";

const SVG_URL = new URL("./heater.svg", import.meta.url);
let svgSource = null;
let instances = 0;

async function svgText() {
  if (svgSource === null) {
    const r = await fetch(SVG_URL);
    if (!r.ok) throw new Error(`heater.svg: HTTP ${r.status}`);
    svgSource = await r.text();
  }
  return svgSource;
}

const sleep = (ms) => new Promise((res) => setTimeout(res, ms));
const reducedMotion = () => globalThis.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

export class Heater extends EventTarget {
  constructor(root, n, { hold = false } = {}) {
    super();
    this.root = root;
    this.n = n;
    this.hold = hold;           // demo grid: one-shot states do not return to idle
    this.state = null;
    this.timers = [];
    this.speaking = null;
    for (const k of [1, 2, 3]) root.style.setProperty(`--hg${k}`, `url(#hg${n}-${k})`);
  }

  _clearTimers() { this.timers.forEach(clearTimeout); this.timers = []; }
  _after(ms, fn) { this.timers.push(setTimeout(fn, ms)); }

  /** Switch state. One-shot states fall back to idle on their own unless hold is set. */
  setState(name, { restart = false } = {}) {
    if (!STATES.includes(name)) throw new Error(`unknown Heater state ${name}`);
    this._clearTimers();
    const cls = this.root.classList;
    STATES.forEach((s) => cls.remove(`st-${s}`));
    cls.remove("reignite");
    if (restart) void this.root.getBoundingClientRect();   // restart CSS one-shots
    cls.add(`st-${name}`);
    const prev = this.state;
    this.state = name;
    this.dispatchEvent(new CustomEvent("state", { detail: { state: name, prev } }));
    if (this.hold) return this;
    if (name === "vindicated") this._after(TIMING.vindicated, () => this.setState("idle"));
    if (name === "cooled") {
      this._after(TIMING.cooled + 900, () => {
        this.setState("idle");
        cls.add("reignite");
        this._after(TIMING.reignite, () => cls.remove("reignite"));
      });
    }
    if (name === "unsure") this._after(TIMING.unsure, () => this.setState("idle"));
    if (name === "blocked") this._after(TIMING.blocked, () => this.setState("idle"));
    return this;
  }

  /** Resolve after a one-shot state's own duration (for scripted sequences). */
  async play(name, ms) {
    this.setState(name, { restart: true });
    await sleep(ms);
  }

  _flapMouth() {
    this.root.classList.add("mouth-open");
    setTimeout(() => this.root.classList.remove("mouth-open"), 120);
  }

  _shake() {
    if (reducedMotion()) return;
    this.root.classList.remove("shake");
    void this.root.getBoundingClientRect();
    this.root.classList.add("shake");
    setTimeout(() => this.root.classList.remove("shake"), 240);
  }

  /** Speak text as "heater" or "ref". Resolves when speech ends. Mouth and emphasis
   *  follow speechSynthesis boundary events; a timer stands in when they never arrive. */
  speak(text, who = "heater", { voiceOn = true } = {}) {
    const isHeater = who === "heater";
    const synth = globalThis.speechSynthesis;
    const settings = isHeater ? VOICE.heater : VOICE.ref;
    return new Promise((resolve) => {
      let boundaries = 0;
      let flap = null;
      const done = () => {
        clearInterval(flap);
        this.root.classList.remove("mouth-open");
        this.speaking = null;
        resolve();
      };
      const startFallbackFlap = () => {
        if (!isHeater || flap) return;
        flap = setInterval(() => { if (!boundaries) this._flapMouth(); }, 150);
      };
      if (!voiceOn || !synth || typeof SpeechSynthesisUtterance === "undefined") {
        startFallbackFlap();
        if (isHeater) text.split(/\s+/).filter(isEmphasis).forEach((_, i) => setTimeout(() => this._shake(), 300 + i * 500));
        setTimeout(done, fallbackSpeechMs(text, settings.rate));
        return;
      }
      const u = new SpeechSynthesisUtterance(text);
      const { heater, ref } = pickVoices(synth.getVoices());
      const v = isHeater ? heater : ref;
      if (v) u.voice = v;
      u.rate = settings.rate;
      u.pitch = settings.pitch;
      u.onboundary = (ev) => {
        if (!isHeater) return;
        boundaries += 1;
        this._flapMouth();
        if (isEmphasis(wordAt(text, ev.charIndex))) this._shake();
      };
      u.onstart = () => setTimeout(() => { if (!boundaries) startFallbackFlap(); }, 400);
      u.onend = done;
      u.onerror = done;
      this.speaking = u;
      synth.cancel();
      synth.speak(u);
    });
  }

  stopSpeaking() { globalThis.speechSynthesis?.cancel(); }

  /** Feed the listening flames from the microphone level (0..1). Returns a stop function.
   *  Audio stays in the page: nothing is recorded or sent. */
  async listenLevel() {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const ctx = new AudioContext();
    const an = ctx.createAnalyser();
    an.fftSize = 512;
    ctx.createMediaStreamSource(stream).connect(an);
    const buf = new Uint8Array(an.fftSize);
    let raf = 0;
    const tick = () => {
      an.getByteTimeDomainData(buf);
      let peak = 0;
      for (const b of buf) peak = Math.max(peak, Math.abs(b - 128));
      this.root.style.setProperty("--mic", Math.min(1, peak / 64).toFixed(3));
      raf = requestAnimationFrame(tick);
    };
    tick();
    return () => {
      cancelAnimationFrame(raf);
      stream.getTracks().forEach((t) => t.stop());
      ctx.close();
      this.root.style.setProperty("--mic", "0");
    };
  }
}

/** Mount a Heater rig into el. Filter ids are suffixed so several rigs can share a page. */
export async function mount(el, { state = "idle", hold = false } = {}) {
  const n = ++instances;
  el.classList.add("h-root");
  el.innerHTML = (await svgText()).replace(/id="hg(\d)"/g, (_, k) => `id="hg${n}-${k}"`);
  const h = new Heater(el, n, { hold });
  h.setState(state);
  return h;
}

/** Build (once) and update a speech card element from a card model and phase. */
export function renderCard(card, model, { phase = "take", avatar = true } = {}) {
  if (!card.dataset.built) {
    card.classList.add("h-card");
    card.innerHTML = `
      <div class="h-card-head">
        <div class="h-card-avatar" aria-hidden="true"></div>
        <span class="h-card-name">HEATER</span><span class="h-card-sub">/ hot take</span>
        <span class="h-chip idle" role="status" aria-live="polite"></span>
      </div>
      <div class="h-card-take"></div>
      <blockquote class="h-card-ref"></blockquote>
      <div class="h-card-foot"></div>
      <div class="h-card-note"></div>`;
    card.dataset.built = "1";
    if (avatar) {
      const a = card.querySelector(".h-card-avatar");
      const holder = document.createElement("div");
      a.append(holder);
      mount(holder, { state: "idle" }).then(() => {
        holder.querySelector("svg").setAttribute("viewBox", "80 22 96 96");
      });
    }
  }
  const chip = card.querySelector(".h-chip");
  const take = card.querySelector(".h-card-take");
  const ref = card.querySelector(".h-card-ref");
  const foot = card.querySelector(".h-card-foot");
  const note = card.querySelector(".h-card-note");
  if (!model || !model.ok) {
    chip.className = "h-chip idle";
    chip.textContent = "WAITING";
    take.textContent = "Waiting on the take";
    ref.textContent = "";
    foot.textContent = "";
    note.textContent = model?.problems?.join("; ") || "";
    return;
  }
  const verdictShown = phase === "verdict";
  const c = verdictShown ? model.chip : CHECKING_CHIP;
  chip.className = `h-chip ${phase === "take" ? "idle" : c.kind}`;
  chip.textContent = phase === "take" ? model.claimId : c.text;
  take.textContent = model.title;
  ref.textContent = "";
  if (phase === "ref" || verdictShown) {
    const b = document.createElement("b");
    b.textContent = "REF:";
    ref.append(b, document.createTextNode(model.refLine));
  }
  foot.textContent = `◆ ${model.facts.join(" · ")}`;
  note.textContent = model.problems.length ? `record problems: ${model.problems.join("; ")}` : "";
}

/** The per-question sequence:
 *  listening -> thinking (while the record loads) -> hot_take (Heater speaks) -> heat_check
 *  -> thinking while the Ref reads the verdict (chip CHECKING…) -> chip updates
 *  -> vindicated / cooled / unsure / blocked -> idle. */
export async function playSequence(heater, card, loadRecord, { voiceOn = true, mic = false, onPhase } = {}) {
  const phase = (p) => onPhase?.(p);
  heater.hold = false;
  phase("listening");
  heater.setState("listening");
  let stopMic = null;
  if (mic) { try { stopMic = await heater.listenLevel(); } catch { stopMic = null; } }
  await sleep(TIMING.listening);
  stopMic?.();

  phase("thinking");
  heater.setState("thinking");
  const [loaded] = await Promise.all([loadRecord(), sleep(TIMING.thinkingMin)]);
  const model = cardModel(loaded.entry, { verified: loaded.verified });
  if (!model.ok) {
    renderCard(card, model);
    heater.setState("blocked");
    phase("blocked");
    return model;
  }

  phase("hot_take");
  renderCard(card, model, { phase: "take" });
  heater.setState("hot_take");
  await heater.speak(model.heaterLine, "heater", { voiceOn });

  phase("heat_check");
  renderCard(card, model, { phase: "ref" });
  await heater.play("heat_check", TIMING.heat_check);

  phase("ref");
  heater.setState("thinking");
  await heater.speak(model.refLine, "ref", { voiceOn });

  phase("verdict");
  renderCard(card, model, { phase: "verdict" });
  heater.setState(model.endState, { restart: true });
  return model;
}
