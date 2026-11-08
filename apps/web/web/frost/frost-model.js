// Frost: the second character, who questions Heater's take before the Ref rules. Pure model: no
// DOM, no fetch, no speech. Frost never decides anything: his questions and the result chips come
// from the server's answer; the verdict stays the Ref's.
//
// Sequence (Experience, 8 Nov 2026):
//   Heater's take -> Frost's question -> its result chip -> (repeat, at most 3) -> the Ref's ruling
//   -> the stamp -> Frost's reaction -> Heater's reaction.

import { pickVoices } from "../heater/heater-model.js";

/** At most this many Frost questions are shown; more are dropped (never merged or reworded). */
export const MAX_CHALLENGES = 3;

/** Frost's poses: web/frost/poses/<state>.webp (the user's files, 687x1024 like Heater's; they
 *  already face left). challenging: while he asks; evidence: while its result chip shows;
 *  unconvinced / satisfied: after the stamp. A missing file is labelled on the stage with this name,
 *  never replaced by another character's image. */
export const FROST_STATES = Object.freeze(["idle", "challenging", "evidence", "unconvinced", "satisfied"]);
export const frostPoseFile = (state) => `poses/${FROST_STATES.includes(state) ? state : "idle"}.webp`;

/** Frost's end pose: he accepts a claim that survived, and stays unconvinced by anything else. */
export const frostEndState = (decision) => (decision === "SURVIVED_PROTOCOL" ? "satisfied" : "unconvinced");

/** Frost's voice: British English, calm. The Ref keeps its own settings (heater-model VOICE.ref). */
export const FROST_VOICE = Object.freeze({ lang: "en-GB", rate: 0.95, pitch: 0.9 });

const isGB = (v) => /^en[-_]GB$/i.test(v?.lang || "");

/** Frost's voice preference (adviser, 8 Nov): Microsoft Ryan Online (Natural), then Google UK English
 *  Male, then other calm male British voices. */
const FROST_PREFS = [/Microsoft Ryan Online/i, /Google UK English Male/i, /Ryan|Thomas|Arthur|George|Daniel|Oliver/i];

/** The Ref's voice when Frost has taken its usual one: a British female voice, else a neutral US one. */
const REF_ALT = [/Libby|Sonia|Maisie|Hazel|Susan|Serena|Kate|Google UK English Female/i, /Andrew|Brian|Aria|Jenny|Google US English|Zira|Samantha/i];

/** Three different voices when the browser has them. Heater keeps pickVoices' choice (moved to a
 *  non-British match when that choice is Frost's Ryan); Frost then takes his preferred British voice;
 *  the Ref keeps pickVoices' choice unless that is Frost's, then moves to a British female or neutral
 *  US voice so the two never blur. With fewer voices, some repeat. */
export function pickCastVoices(voices) {
  const all = voices || [];
  const { heater: h0, ref: ref0 } = pickVoices(all);
  const en = all.filter((v) => /^en([-_]|$)/i.test(v.lang || ""));
  const pool = en.length ? en : all;
  const first = (cands, ok) => { for (const re of cands) { const v = cands.length && pool.find((x) => re.test(x.name) && ok(x)); if (v) return v; } return null; };
  const heater = h0 && FROST_PREFS[0].test(h0.name)
    ? pool.find((v) => v !== h0 && !isGB(v) && /Guy|Davis|Jason|Eric|Christopher|Aria|Jenny|Google US English|Alex|Samantha/i.test(v.name)) || h0
    : h0;
  const gb = pool.filter((v) => isGB(v) && v !== heater);
  const frost = first(FROST_PREFS, (v) => isGB(v) && v !== heater) || gb.find((v) => v !== ref0) || gb[0]
    || all.find((v) => v !== heater && v !== ref0) || ref0 || heater || null;
  let ref = ref0;
  if (!ref || ref === frost || ref === heater) {
    ref = first(REF_ALT, (v) => v !== heater && v !== frost)
      || pool.find((v) => v !== heater && v !== frost) || all.find((v) => v !== heater && v !== frost) || ref0;
  }
  return { heater, frost, ref };
}

const str = (x) => (typeof x === "string" ? x.trim() : "");

/** A result chip's text and colour class. ``kind`` is one of pass | fail | info; the text always
 *  says the result in words, so colour never carries it alone. */
export function chipView(chip, source = "") {
  const text = typeof chip === "string" ? str(chip) : str(chip?.text ?? chip?.label);
  if (!text) return null;
  const k = String((typeof chip === "object" && (chip?.kind || chip?.status)) || "").toLowerCase();
  const kind = ["pass", "ok", "passed"].includes(k) ? "pass" : ["fail", "failed", "warn"].includes(k) ? "fail" : "info";
  const src = str(source) || (typeof chip === "object" ? str(chip?.source) : "");
  return src ? { text, kind, source: src } : { text, kind };
}

/** Normalise one exchange: {take, challenges: [{question, chip}], frostReaction, heaterReaction}.
 *  Returns null when there is no take or no question (the page then runs the Heater-only flow).
 *  Questions without text are dropped; only the first MAX_CHALLENGES are kept. */
export function normalizeExchange(x) {
  const take = str(x?.take);
  const challenges = (Array.isArray(x?.challenges) ? x.challenges : [])
    .map((c) => ({ question: str(c?.question), chip: chipView(c?.chip, c?.source) }))
    .filter((c) => c.question)
    .slice(0, MAX_CHALLENGES);
  if (!take || !challenges.length) return null;
  return { take, challenges, frostReaction: str(x?.frostReaction), heaterReaction: str(x?.heaterReaction) };
}

/** The exchange from Max's dialogue answer, or null (Heater-only flow). Shape of the sample response
 *  (user, 8 Nov; Max's API to match): ``frost`` = [{check, question, chip (text), source}] and
 *  ``frost_reaction``. ``check`` is never shown (no type tags); ``source`` goes on the chip's tooltip.
 *  ``take`` is the page's checked take (dialogueLines); Heater's reaction comes via its lastWord. */
export function exchangeFromApi(api, { take } = {}) {
  if (!Array.isArray(api?.frost)) return null;
  return normalizeExchange({ take, challenges: api.frost, frostReaction: api.frost_reaction });
}

/** The ordered steps of one exchange. Reactions with no text are left out. */
export function exchangeSteps(ex) {
  const steps = [{ who: "heater", kind: "take", text: ex.take }];
  ex.challenges.forEach((c, i) => {
    steps.push({ who: "frost", kind: "question", text: c.question, index: i, first: i === 0 });
    if (c.chip) steps.push({ who: "frost", kind: "chip", chip: c.chip, index: i });
  });
  steps.push({ who: "ref", kind: "ruling" }, { who: "ref", kind: "stamp" });
  if (ex.frostReaction) steps.push({ who: "frost", kind: "reaction", text: ex.frostReaction });
  if (ex.heaterReaction) steps.push({ who: "heater", kind: "reaction", text: ex.heaterReaction });
  return steps;
}

/** Space skips to the stamp: every step before it is drawn at once without speech or pauses. */
export const skippable = (step) => step.kind !== "stamp" && step.kind !== "reaction";

/** Whether a key press is the "skip to the stamp" Space. Typing in a text field other than the
 *  question box is never taken over (the question box is idle while an exchange runs). */
export function isSkipKey(ev, { running }) {
  if (!running || ev?.code !== "Space" && ev?.key !== " ") return false;
  if (ev.repeat || ev.ctrlKey || ev.metaKey || ev.altKey) return false;
  const t = ev.target;
  const tag = String(t?.tagName || "").toUpperCase();
  if (t?.isContentEditable || tag === "TEXTAREA" || tag === "SELECT") return false;
  if (tag === "INPUT" && t.id !== "q") return false;
  return true;
}
