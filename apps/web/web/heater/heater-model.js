// Heater's pure model: evidence-ledger entry -> what Heater says, which state he ends in,
// and the speech card's chip and footer. No DOM, no network, no clock.
//
// Every number shown comes from the record itself. Integers are only given thousands
// separators. The one derived count, the number of attack_results entries, is a count of
// records in the entry, never a computed statistic.

export const STATES = Object.freeze([
  "idle", "listening", "thinking", "hot_take", "vindicated",
  "cooled", "unsure", "blocked", "heat_check",
]);

export const DECISION_STATE = Object.freeze({
  SURVIVED_PROTOCOL: "vindicated",
  NOT_SUPPORTED: "cooled",
  INSUFFICIENT_EVIDENCE: "unsure",
  BLOCKED: "blocked",
  DATA_INVALID: "blocked",
});

const CHIP = Object.freeze({
  SURVIVED_PROTOCOL: ["SURVIVED", "survived"],
  NOT_SUPPORTED: ["NOT SUPPORTED", "not-supported"],
  INSUFFICIENT_EVIDENCE: ["INSUFFICIENT", "insufficient"],
  BLOCKED: ["BLOCKED", "blocked"],
  DATA_INVALID: ["DATA INVALID", "blocked"],
});

export const CHECKING_CHIP = Object.freeze({ text: "CHECKING…", kind: "checking" });

const isObj = (v) => v !== null && typeof v === "object" && !Array.isArray(v);
const isStr = (v) => typeof v === "string" && v.length > 0;

export function isLedgerEntry(e) {
  return isObj(e) && isStr(e.evidence_id) && isObj(e.identity) && isObj(e.identity.claim)
    && isStr(e.identity.decision) && Array.isArray(e.identity.attack_results);
}

/** Parse a ledger JSONL file's text into entries (blank lines skipped, bad lines refused). */
export function parseJsonl(text) {
  if (typeof text !== "string") throw new TypeError("ledger text must be a string");
  const out = [];
  text.split("\n").forEach((line, i) => {
    if (!line.trim()) return;
    let e;
    try { e = JSON.parse(line); } catch { throw new Error(`ledger line ${i + 1} is not JSON`); }
    if (!isLedgerEntry(e)) throw new Error(`ledger line ${i + 1} is not an evidence-ledger entry`);
    out.push(e);
  });
  return out;
}

export function chipFor(decision) {
  if (decision == null) return { ...CHECKING_CHIP };
  const hit = CHIP[decision];
  return hit ? { text: hit[0], kind: hit[1] } : { text: `UNKNOWN ${decision}`, kind: "unknown" };
}

/** The state Heater ends in for a verdict. Unknown verdicts are shown as unsure, never vindicated. */
export function stateForDecision(decision) {
  return DECISION_STATE[decision] || "unsure";
}

const fmtCount = (n) => (Number.isInteger(n) ? n.toLocaleString("en-US") : String(n));
const plural = (n, one, many) => `${fmtCount(n)} ${n === 1 ? one : many}`;

/** Facts for the card footer, read only from fields present in the entry. */
export function factsFor(entry, { verified = false } = {}) {
  const facts = [];
  const id = entry.identity;
  facts.push(plural(id.attack_results.length, "attack", "attacks"));
  const d = isObj(id.data) ? id.data : {};
  if (typeof d.n_attempts === "number") facts.push(plural(d.n_attempts, "attempt", "attempts"));
  if (typeof d.n_games === "number") facts.push(plural(d.n_games, "game", "games"));
  if (isStr(d.data_mode)) facts.push(d.data_mode.toLowerCase().replaceAll("_", " "));
  facts.push(`evidence ${entry.evidence_id.slice(0, 8)}`);
  facts.push(verified ? "hashes verified by server" : "hashes not verified here");
  return facts;
}

/** Everything the speech card and the sequence need, from one ledger entry. */
export function cardModel(entry, { verified = false } = {}) {
  if (!isLedgerEntry(entry)) {
    return { ok: false, problems: ["not an evidence-ledger entry"], chip: chipFor("NOT_A_RECORD") };
  }
  const id = entry.identity;
  const plan = isObj(id.claim.plan) ? id.claim.plan : {};
  const problems = [];
  const statement = isStr(plan.statement) ? plan.statement : null;
  if (!statement) problems.push("claim statement missing");
  const reason = isStr(id.reason) ? id.reason : null;
  if (!reason) problems.push("verdict reason missing");
  if (!CHIP[id.decision]) problems.push(`unrecognised verdict ${id.decision}`);
  const verdictWords = (CHIP[id.decision] ? CHIP[id.decision][0] : id.decision).toLowerCase();
  return {
    ok: true,
    claimId: isStr(id.claim.claim_id) ? id.claim.claim_id : "(no claim id)",
    title: statement || "(claim statement missing)",
    heaterLine: statement ? `HOT take: ${statement}` : "No take on record.",
    refLine: `${verdictWords}. ${reason || "No reason on record."}`,
    decision: id.decision,
    chip: chipFor(id.decision),
    endState: stateForDecision(id.decision),
    facts: factsFor(entry, { verified }),
    problems,
  };
}

/** True for a word Heater should hit hard: two or more capitals, e.g. "HOT", "HH-K3". */
export function isEmphasis(word) {
  return /^[A-Z][A-Z0-9-]*[A-Z0-9][!?.,:;]*$/.test(word);
}

/** The word starting at (or containing) charIndex, as a speechSynthesis boundary reports it. */
export function wordAt(text, charIndex) {
  if (typeof text !== "string" || !(charIndex >= 0) || charIndex >= text.length) return "";
  let s = charIndex;
  while (s > 0 && !/\s/.test(text[s - 1])) s--;
  let e = charIndex;
  while (e < text.length && !/\s/.test(text[e])) e++;
  return text.slice(s, e);
}

/** Pick two different English voices: an energetic one for Heater, a calm one for the Ref.
 *  "Energetic" and "calm" are name heuristics; no speech rate is measured. */
export function pickVoices(voices) {
  const en = (voices || []).filter((v) => /^en([-_]|$)/i.test(v.lang || ""));
  const pool = en.length ? en : (voices || []);
  const find = (re, not) => pool.find((v) => re.test(v.name) && v !== not);
  const heater = find(/Guy|Davis|Jason|Ryan|Eric|Christopher|Aria|Jenny|Google US English|Alex|Samantha/i)
    || pool[0] || null;
  const ref = find(/Natural.*(Andrew|Brian|Libby|Sonia|Thomas)|Daniel|Libby|Sonia|George|Google UK English Male|Fred|Mark|David/i, heater)
    || pool.find((v) => v !== heater) || heater;
  return { heater, ref };
}

export const VOICE = Object.freeze({
  heater: { rate: 1.15, pitch: 1.1 },
  ref: { rate: 0.95, pitch: 0.9 },
});

/** Milliseconds each scripted step lasts when it is not waiting on speech. */
export const TIMING = Object.freeze({
  listening: 900, thinkingMin: 700, heat_check: 600,
  vindicated: 1200, cooled: 1500, reignite: 1000, unsure: 1600, blocked: 1800,
});

/** Speech fallback duration when speechSynthesis is unavailable: about 13 characters a second. */
export function fallbackSpeechMs(text, rate = 1) {
  return Math.max(600, Math.round((String(text).length * 75) / rate));
}
