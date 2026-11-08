// Frost controller: mount the pose images, switch poses, slide in, speak in his own voice.
// The pure model (states, voice, sequence) is frost-model.js.

import { fallbackSpeechMs, speechGuardMs } from "../heater/heater-model.js";
import { FROST_STATES, FROST_VOICE, frostPoseFile, pickCastVoices } from "./frost-model.js";

const poseUrl = (state) => new URL(frostPoseFile(state), import.meta.url).href;

export class Frost {
  constructor(root) {
    this.root = root;
    this.state = null;
    this.speaking = null;
    this.layers = [...root.querySelectorAll(".f-pose")];
    this.missing = root.querySelector(".f-missing");
    this.front = 0;
  }

  /** Crossfade to the state's pose. A missing image is labelled with the expected file name. */
  _showPose(state) {
    if (this.layers.length < 2) return;
    const url = poseUrl(state);
    const front = this.layers[this.front];
    if (front.dataset.src === url) return;
    const back = this.layers[1 - this.front];
    const swap = () => {
      back.classList.add("on");
      front.classList.remove("on");
      this.front = 1 - this.front;
    };
    back.onload = () => { if (this.missing) this.missing.textContent = ""; this.root.classList.remove("f-nopose"); swap(); };
    back.onerror = () => {
      if (this.missing) this.missing.textContent = `pose image missing: frost/${frostPoseFile(state)}`;
      this.root.classList.add("f-nopose");
      swap();
    };
    back.dataset.src = url;
    back.src = url;
  }

  setState(name) {
    if (!FROST_STATES.includes(name)) throw new Error(`unknown Frost state ${name}`);
    const cls = this.root.classList;
    FROST_STATES.forEach((s) => cls.remove(`fs-${s}`));
    cls.add(`fs-${name}`);
    this._showPose(name);
    this.state = name;
    return this;
  }

  /** Slide in from the right (his first question). */
  enter() { this.root.classList.add("entered"); }
  leave() { this.root.classList.remove("entered"); }
  get entered() { return this.root.classList.contains("entered"); }

  /** Speak in Frost's voice (en-GB, calm, rate 0.95). Resolves when speech ends, or after the same
   *  guard Heater uses when the browser never reports an end. */
  speak(text, { voiceOn = true } = {}) {
    const synth = globalThis.speechSynthesis;
    return new Promise((resolve) => {
      let finished = false;
      let guard = null;
      let u = null;
      const done = () => {
        if (finished) return;
        finished = true;
        clearTimeout(guard);
        if (this.speaking === u) this.speaking = null;
        this.root.classList.remove("talking");
        resolve();
      };
      this.root.classList.add("talking");
      if (!voiceOn || !synth || typeof SpeechSynthesisUtterance === "undefined") {
        setTimeout(done, fallbackSpeechMs(text, FROST_VOICE.rate));
        return;
      }
      u = new SpeechSynthesisUtterance(text);
      const { frost } = pickCastVoices(synth.getVoices());
      if (frost) u.voice = frost;
      u.lang = FROST_VOICE.lang;
      u.rate = FROST_VOICE.rate;
      u.pitch = FROST_VOICE.pitch;
      u.onend = done;
      u.onerror = done;
      this.speaking = u;
      synth.cancel();
      guard = setTimeout(done, speechGuardMs(text, FROST_VOICE.rate));
      synth.speak(u);
    });
  }

  stopSpeaking() { globalThis.speechSynthesis?.cancel(); }
}

function el(tag, cls) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  return e;
}

/** Mount Frost into a container: two stacked pose images for the crossfade and a label for a
 *  missing image. He starts off stage; enter() slides him in. */
export function mount(root, { state = "idle" } = {}) {
  root.classList.add("f-root");
  root.replaceChildren();
  const body = el("div", "f-body");
  body.append(el("div", "f-spot"));
  for (let i = 0; i < 2; i++) {
    const img = el("img", "f-pose");
    img.alt = "";
    img.decoding = "async";
    body.append(img);
  }
  root.append(body, el("p", "f-missing"));
  root.setAttribute("role", "img");
  root.setAttribute("aria-label", "Frost, who questions Heater's takes");
  const f = new Frost(root);
  f.setState(state);
  return f;
}
