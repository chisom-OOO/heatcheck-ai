// Heater controller: mount the pose images, run the state machine, speak, drive the speech card.
// Exposes mount(el) -> Heater with setState(name) and speak(text, who), plus renderCard(),
// loadLines() and playSequence(). The pure model (pose map, verdicts, lines) is heater-model.js.

import {
  STATES, TIMING, VOICE, CHECKING_CHIP, PLACEHOLDER_LINES, cardModel, fallbackSpeechMs, isEmphasis,
  linesTable, pickVoices, poseFile, wordAt,
} from "./heater-model.js";

export { STATES } from "./heater-model.js";

const sleep = (ms) => new Promise((res) => setTimeout(res, ms));
const reducedMotion = () => globalThis.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
const poseUrl = (state) => new URL(poseFile(state), import.meta.url).href;

export class Heater extends EventTarget {
  constructor(root, { hold = false } = {}) {
    super();
    this.root = root;
    this.hold = hold;           // demo grid: one-shot states do not return to idle
    this.state = null;
    this.timers = [];
    this.speaking = null;
    this.layers = [...root.querySelectorAll(".h-pose")];
    this.slices = [...root.querySelectorAll(".h-slice")];
    this.missing = root.querySelector(".h-missing");
    this.front = 0;
  }

  _clearTimers() { this.timers.forEach(clearTimeout); this.timers = []; }
  _after(ms, fn) { this.timers.push(setTimeout(fn, ms)); }

  /** Crossfade to the state's pose image (200 ms, in CSS). A missing image is labelled on
   *  the stage instead of silently showing the previous pose. */
  _showPose(state) {
    const url = poseUrl(state);
    const front = this.layers[this.front];
    if (front.dataset.src === url) return;
    const back = this.layers[1 - this.front];
    const swap = () => {
      back.classList.add("on");
      front.classList.remove("on");
      this.front = 1 - this.front;
    };
    back.onload = () => { this.missing.textContent = ""; this.root.classList.remove("h-nopose"); swap(); };
    back.onerror = () => {
      this.missing.textContent = `pose image missing: ${poseFile(state)}`;
      this.root.classList.add("h-nopose");
      swap();
    };
    back.dataset.src = url;
    back.src = url;
    for (const s of this.slices) s.src = url;   // the glitch slices copy the current pose
  }

  /** Switch state. One-shot states fall back to idle on their own unless hold is set. */
  setState(name, { restart = false } = {}) {
    if (!STATES.includes(name)) throw new Error(`unknown Heater state ${name}`);
    this._clearTimers();
    const cls = this.root.classList;
    STATES.forEach((s) => cls.remove(`st-${s}`));
    cls.remove("reignite");
    if (restart) void this.root.getBoundingClientRect();   // restart CSS one-shots
    cls.add(`st-${name}`);
    this._showPose(name);
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

  _pulse(cls, ms) {
    if (reducedMotion()) return;
    this.root.classList.remove(cls);
    void this.root.getBoundingClientRect();   // restart the CSS animation
    this.root.classList.add(cls);
    setTimeout(() => this.root.classList.remove(cls), ms);
  }

  /** One squash-bounce per spoken word (speechSynthesis boundary event). */
  _bounce() { this._pulse("bounce", 200); }

  /** ±3 px shake on an emphasised (CAPS) word. */
  _shake() { this._pulse("shake", 240); }

  /** Speak text as "heater" or "ref". Resolves when speech ends. The bounce and the CAPS
   *  shake follow speechSynthesis boundary events; a timer stands in when they never arrive. */
  speak(text, who = "heater", { voiceOn = true } = {}) {
    const isHeater = who === "heater";
    const synth = globalThis.speechSynthesis;
    const settings = isHeater ? VOICE.heater : VOICE.ref;
    return new Promise((resolve) => {
      let boundaries = 0;
      let beat = null;
      const done = () => {
        clearInterval(beat);
        this.root.classList.remove("bounce");
        this.speaking = null;
        resolve();
      };
      const startFallbackBeat = () => {
        if (!isHeater || beat) return;
        beat = setInterval(() => { if (!boundaries) this._bounce(); }, 260);
      };
      if (!voiceOn || !synth || typeof SpeechSynthesisUtterance === "undefined") {
        startFallbackBeat();
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
        this._bounce();
        if (isEmphasis(wordAt(text, ev.charIndex))) this._shake();
      };
      u.onstart = () => setTimeout(() => { if (!boundaries) startFallbackBeat(); }, 400);
      u.onend = done;
      u.onerror = done;
      this.speaking = u;
      synth.cancel();
      synth.speak(u);
    });
  }

  stopSpeaking() { globalThis.speechSynthesis?.cancel(); }

  /** Feed the listening glow from the microphone level (0..1). Returns a stop function.
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

const SPARKS = 8;

function el(tag, cls) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  return e;
}

/** Mount Heater into a container: two stacked pose images for the crossfade, four slices
 *  for the heat_check glitch, sparks rising from the head, and a label for a missing image. */
export async function mount(root, { state = "idle", hold = false } = {}) {
  root.classList.add("h-root");
  root.replaceChildren();
  const fig = el("div", "h-fig");
  const body = el("div", "h-body");
  for (let i = 0; i < 2; i++) {
    const img = el("img", "h-pose");
    img.alt = "";
    img.decoding = "async";
    body.append(img);
  }
  const glitch = el("div", "h-glitch");
  glitch.setAttribute("aria-hidden", "true");
  for (let i = 1; i <= 4; i++) {
    const s = el("img", `h-slice h-slice-${i}`);
    s.alt = "";
    glitch.append(s);
  }
  body.append(glitch);
  fig.append(body);
  const sparks = el("div", "h-sparks");
  sparks.setAttribute("aria-hidden", "true");
  for (let i = 1; i <= SPARKS; i++) sparks.append(el("i", `h-spark h-spark-${i}`));
  root.append(fig, sparks, el("p", "h-missing"));
  root.setAttribute("role", "img");
  root.setAttribute("aria-label", "Heater, the HeatCheck pundit");
  const h = new Heater(root, { hold });
  h.setState(state);
  return h;
}

/** Heater's hot-take lines from web/heater_personality.json, or the labelled placeholder
 *  lines while that file is absent. Returns {table, source}. */
export async function loadLines() {
  try {
    const r = await fetch(new URL("../heater_personality.json", import.meta.url));
    if (r.ok) {
      const table = linesTable(await r.json());
      if (table) return { table, source: "heater_personality.json" };
    }
  } catch { /* fall through to placeholders */ }
  return { table: PLACEHOLDER_LINES, source: "placeholder lines (heater_personality.json not present yet)" };
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
      <div class="h-card-claim"></div>
      <blockquote class="h-card-ref"></blockquote>
      <div class="h-card-foot"></div>
      <div class="h-card-note"></div>`;
    card.dataset.built = "1";
    if (avatar) {
      const img = document.createElement("img");
      img.alt = "";
      img.src = poseUrl("idle");
      img.onerror = () => img.remove();
      card.querySelector(".h-card-avatar").append(img);
    }
  }
  const chip = card.querySelector(".h-chip");
  const take = card.querySelector(".h-card-take");
  const claim = card.querySelector(".h-card-claim");
  const ref = card.querySelector(".h-card-ref");
  const foot = card.querySelector(".h-card-foot");
  const note = card.querySelector(".h-card-note");
  if (!model || !model.ok) {
    chip.className = "h-chip idle";
    chip.textContent = "WAITING";
    take.textContent = "Waiting on the take";
    claim.textContent = "";
    ref.textContent = "";
    foot.textContent = "";
    note.textContent = model?.problems?.join("; ") || "";
    return;
  }
  const verdictShown = phase === "verdict";
  const c = verdictShown ? model.chip : CHECKING_CHIP;
  chip.className = `h-chip ${phase === "take" ? "idle" : c.kind}`;
  chip.textContent = phase === "take" ? model.claimId : c.text;
  take.textContent = `“${model.heaterLine}”`;
  claim.textContent = `Claim ${model.claimId}: ${model.title}`;
  ref.textContent = "";
  if (phase === "ref" || verdictShown) {
    const b = document.createElement("b");
    b.textContent = "REF:";
    ref.append(b, document.createTextNode(model.refLine));
  }
  foot.textContent = `◆ ${model.facts.join(" · ")}`;
  const notes = [];
  if (model.linesSource) notes.push(`line: ${model.linesSource}`);
  if (model.problems.length) notes.push(`record problems: ${model.problems.join("; ")}`);
  note.textContent = notes.join(" · ");
}

/** The per-question sequence:
 *  listening -> thinking (while the record loads) -> hot_take (Heater speaks) -> heat_check
 *  -> thinking while the Ref reads the verdict (chip CHECKING…) -> chip updates
 *  -> vindicated / cooled / unsure / blocked -> idle.
 *  loadRecord() resolves to {entry, verified, lines?: {table, source}}. */
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
  const model = cardModel(loaded.entry, { verified: loaded.verified, lines: loaded.lines?.table, turn: loaded.turn || 0 });
  if (model.ok) model.linesSource = loaded.lines?.source || "placeholder lines";
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
