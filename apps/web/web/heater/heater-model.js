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

/** The seven pose images (apps/web/web/heater/poses/<name>.webp, 687x1024). */
export const POSES = Object.freeze([
  "idle", "listening", "thinking", "hot_take", "heat_check", "vindicated", "cooled",
]);

/** The single pose map: state -> pose image. unsure and blocked borrow thinking and
 *  listening until their own images exist. */
export const POSE_FOR_STATE = Object.freeze({
  idle: "idle", listening: "listening", thinking: "thinking", hot_take: "hot_take",
  heat_check: "heat_check", vindicated: "vindicated", cooled: "cooled",
  unsure: "thinking", blocked: "listening",
});

export const poseFile = (state) => `poses/${POSE_FOR_STATE[state] || "idle"}.webp`;

/** Placeholder hot takes, used only while web/heater_personality.json is absent.
 *  The HH-K2 line is the user's own example; the others are placeholders, not the
 *  user's file. Heater lines carry no digits: numbers belong to the Ref. */
export const PLACEHOLDER_LINES = Object.freeze({
  "HH-K2": ["Two in a row? He's HEATING UP! Give him the ball!"],
  "HH-K3": ["Three straight? He's ON FIRE! Nobody can guard him now!"],
  "GP-REST": ["Fresh legs WIN games. The rested team takes it, every time!"],
  "*": ["I've seen enough. I KNOW I'm right about this one!"],
});

/** Pull a {claim_id: [lines]} table out of a personality file. Accepts
 *  {"lines": {...}}, {"claims": {...}} or the table itself; "*" or "default" is the fallback. */
export function linesTable(doc) {
  const t = isObj(doc?.lines) ? doc.lines : isObj(doc?.claims) ? doc.claims : doc;
  if (!isObj(t)) return null;
  const out = {};
  for (const [k, v] of Object.entries(t)) {
    const arr = (Array.isArray(v) ? v : [v]).filter(isStr);
    if (arr.length) out[k === "default" ? "*" : k] = arr;
  }
  return Object.keys(out).length ? out : null;
}

/** Heater's line for a claim: a hot take from the table, never the claim description. */
export function heaterLineFor(claimId, table = PLACEHOLDER_LINES, turn = 0) {
  const pool = (table && (table[claimId] || table["*"])) || PLACEHOLDER_LINES["*"];
  return pool[Math.abs(turn) % pool.length];
}

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
  // Agent-loop entries carry attack_results; recorded Research finals (lane DEVELOPMENT or
  // CONFIRMATORY, copied by Max's recorder) carry a lane and a result instead.
  return isObj(e) && isStr(e.evidence_id) && isObj(e.identity) && isObj(e.identity.claim)
    && isStr(e.identity.decision)
    && (Array.isArray(e.identity.attack_results) || (isStr(e.identity.lane) && isObj(e.identity.result)));
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
export function cardModel(entry, { verified = false, lines = PLACEHOLDER_LINES, turn = 0 } = {}) {
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
  const claimId = isStr(id.claim.claim_id) ? id.claim.claim_id : "(no claim id)";
  return {
    ok: true,
    claimId,
    title: statement || "(claim statement missing)",
    heaterLine: heaterLineFor(claimId, lines, turn),
    refLine: `${verdictWords}. ${reason || "No reason on record."}`,
    decision: id.decision,
    chip: chipFor(id.decision),
    endState: stateForDecision(id.decision),
    facts: factsFor(entry, { verified }),
    problems,
  };
}

// ------------------------------------------------------------------ demo page: plain English

/** Display titles for registered claims (shown instead of registry text). */
export const CLAIM_TITLES = Object.freeze({
  "HH-K2": "Hot hand: two makes in a row",
  "HH-K3": "Hot hand: three makes in a row",
  "CONF-HH": "Hot hand: three makes in a row (final test)",
  "CONF-MOM": "Momentum: one make in a row",
  "CONF-HA": "Home-court advantage",
  "GP-REST": "Rest days and back-to-backs",
  "GP-ELO": "The better team wins",
  NONE: "Not a registered claim",
});

/** Offline question -> claim routing, used only when the dialogue API is unavailable. */
export function routeQuestion(q) {
  const s = String(q || "").toLowerCase();
  const streak = /hot hand|in a row|straight|streak|heating up|on fire|consecutive/.test(s);
  if (streak && /\b(three|3)\b/.test(s)) return "HH-K3";
  if (streak) return "HH-K2";
  if (/momentum/.test(s)) return "CONF-MOM";
  if (/\bhome\b|home[- ]court|crowd/.test(s)) return "CONF-HA";
  if (/\brest\b|rested|back[- ]to[- ]back|tired|fatigue|days off/.test(s)) return "GP-REST";
  if (/\belo\b|better team|favou?rites?\b|underdog/.test(s)) return "GP-ELO";
  return "NONE";
}

/** The newest ledger entry for a claim (entries are in append order). */
export function latestFor(entries, claimId) {
  for (let i = (entries || []).length - 1; i >= 0; i--) {
    if (entries[i]?.identity?.claim?.claim_id === claimId) return entries[i];
  }
  return null;
}

const WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"];
const word = (n) => (Number.isInteger(n) && n >= 0 && n <= 10 ? WORDS[n] : String(n));
/** p-values to two decimals (0.239 -> "0.24"), three below 0.01 (0.0054 -> "0.005"), and
 *  tiny ones as "< 0.001". */
export const fmtP = (p) => (p < 0.001 ? "< 0.001"
  : p < 0.01 ? (Math.round(p * 1000) / 1000).toFixed(3)
    : (Math.round(p * 100) / 100).toFixed(2));
/** A probability as a percentage with one decimal (0.5449 -> "54.5%"). */
export const fmtPct = (x) => `${(Math.round(Number(x) * 1000) / 10).toFixed(1)}%`;
/** Said of every result from the sealed confirmatory season. */
export const NEVER_SEEN = "tested on a season the system had never seen";
const attack = (entry, id) => entry.identity.attack_results.find((a) => String(a.test_id_version || "").startsWith(`${id}@`));
const DATA_PLAIN = {
  GAME_SEASON_VIEW: "season-long game results",
  SHOT_VIEW: "shot-by-shot data",
};

export const DEFAULT_PERSONALITY = Object.freeze({
  verdict_stamps: {
    SURVIVED_PROTOCOL: "SURVIVED", NOT_SUPPORTED: "NOT SUPPORTED", INSUFFICIENT_EVIDENCE: "NOT ENOUGH EVIDENCE",
    DATA_INVALID: "DATA INVALID", BLOCKED: "NO RULING",
  },
  ref_templates: {
    SURVIVED_PROTOCOL: "It holds up. {plain_finding} ({stat_summary}). That passes our pre-registered tests; it is not a guarantee.",
    NOT_SUPPORTED: "The data says no. {plain_finding} ({stat_summary}).",
    INSUFFICIENT_EVIDENCE: "Can't tell yet. {plain_finding} ({stat_summary}). Not enough evidence either way.",
    DATA_INVALID: "No ruling. The data failed its checks: {reason}.",
    BLOCKED: "No ruling. {reason}.",
  },
});

const fill = (tpl, vals) => tpl.replace(/\{(\w+)\}/g, (_, k) => (k in vals ? vals[k] : `{${k}}`));
const stripDot = (s) => String(s).replace(/[.\s]+$/, "");

/** The Ref's plain-English line for a ledger entry: plain words first, numbers second, every
 *  number read from the record (p-values rounded to two decimals, small counts as words).
 *  Returns {text, plain: boolean}; plain is false when only the raw reason could be used. */
export function refPlain(entry, personality = DEFAULT_PERSONALITY) {
  const id = entry.identity;
  const d = id.decision;
  const tpl = (personality?.ref_templates || {})[d] || DEFAULT_PERSONALITY.ref_templates[d];
  const plan = isObj(id.claim.plan) ? id.claim.plan : {};
  const params = isObj(plan.params) ? plan.params : {};
  const data = isObj(id.data) ? id.data : {};
  if (d === "BLOCKED" || d === "DATA_INVALID") {
    const m = /^no (\w+) implemented/.exec(id.reason || "");
    const reason = m && DATA_PLAIN[m[1]]
      ? `This test needs ${DATA_PLAIN[m[1]]}, and those aren't loaded yet`
      : stripDot(id.reason || "no reason on record");
    return { text: fill(tpl || "No ruling. {reason}.", { reason }), plain: Boolean(m && DATA_PLAIN[m[1]]) };
  }
  const confirmatory = confirmatoryPlain(id);
  if (confirmatory && tpl) return { text: fill(tpl, confirmatory), plain: true };
  if (plan.kind === "SHOT_ASSOCIATION" && Number.isInteger(params.k) && tpl) {
    const kw = word(params.k);
    const games = data.n_games === 1 ? "one game" : `${fmtCount(data.n_games)} games`;
    const perm = attack(entry, "A-PERMUTATION-NULL");
    const size = attack(entry, "A-SAMPLE-SIZE");
    if (d === "INSUFFICIENT_EVIDENCE" && size && isObj(size.details)) {
      const sd = size.details;
      return {
        text: fill(tpl, {
          plain_finding: `Too few shots came right after ${kw} makes in a row to compare`,
          stat_summary: `${fmtCount(sd.n_after_makes)} after ${kw} makes, ${fmtCount(sd.n_after_misses)} after ${kw} misses; ${fmtCount(params.min_n_each_side)} of each needed`,
        }),
        plain: true,
      };
    }
    if ((d === "NOT_SUPPORTED" || d === "SURVIVED_PROTOCOL") && perm && typeof perm.p_value === "number") {
      return {
        text: fill(tpl, {
          plain_finding: d === "NOT_SUPPORTED"
            ? `Making ${kw} in a row didn't make the next shot more likely`
            : `Making ${kw} in a row did make the next shot more likely`,
          stat_summary: `p = ${fmtP(perm.p_value)}, ${fmtCount(data.n_attempts)} shots, ${games}`,
        }),
        plain: true,
      };
    }
  }
  const verdict = (CHIP[d] ? CHIP[d][0] : d).toLowerCase();
  return { text: `${verdict[0].toUpperCase()}${verdict.slice(1)}. ${stripDot(id.reason || "No reason on record")}.`, plain: false };
}

/** Plain words for a recorded result from the sealed confirmatory season (lane CONFIRMATORY,
 *  written by Max's recorder from Research's final_result.json). Every number is read from the
 *  record's ``result``: ``p_holm`` (Holm-adjusted across the family) and ``detail``. Returns
 *  {plain_finding, stat_summary} or null when the record lacks the fields. */
export function confirmatoryPlain(id) {
  if (id?.lane !== "CONFIRMATORY" || !isObj(id.result)) return null;
  const r = id.result;
  const det = isObj(r.detail) ? r.detail : {};
  const p = typeof r.p_holm === "number" ? r.p_holm : null;
  const season = isStr(id.data?.season) ? id.data.season : null;
  if (p === null || !season) return null;
  const pText = `p = ${fmtP(p)}`;
  const cid = id.claim?.claim_id;
  if (cid === "CONF-HA" && typeof det.home_win_rate === "number" && Number.isInteger(det.n_games)) {
    return {
      plain_finding: `Home teams won ${fmtPct(det.home_win_rate)} of their games, ${NEVER_SEEN}`,
      stat_summary: `${fmtCount(det.n_games)} games in ${season}, ${pText}`,
    };
  }
  const k = { "CONF-MOM": 1, "CONF-HH": 3 }[cid];
  if (k && typeof det.p_make_after_makes === "number" && typeof det.p_make_after_misses === "number"
      && Number.isInteger(det.n_fga)) {
    const runs = k === 1 ? ["a make", "a miss"] : [`${word(k)} makes in a row`, `${word(k)} misses in a row`];
    return {
      plain_finding: `After ${runs[0]} the next shot went in ${fmtPct(det.p_make_after_makes)} of the time, `
        + `and ${fmtPct(det.p_make_after_misses)} after ${runs[1]}, ${NEVER_SEEN}`,
      stat_summary: `${fmtCount(det.n_fga)} shots in ${season}, ${pText}`,
    };
  }
  return null;
}

/** The verdict stamp's text and colour class. */
export function stampFor(decision, personality = DEFAULT_PERSONALITY) {
  const text = (personality?.verdict_stamps || {})[decision] || DEFAULT_PERSONALITY.verdict_stamps[decision];
  const kind = { SURVIVED_PROTOCOL: "survived", NOT_SUPPORTED: "not-supported", INSUFFICIENT_EVIDENCE: "insufficient",
    BLOCKED: "blocked", DATA_INVALID: "blocked" }[decision];
  return text && kind ? { text, kind } : { text: "NOT TESTED YET", kind: "untested" };
}

/** Heater's take for a claim from the personality file ("claims": id -> line or [lines]). */
export function takeFor(claimId, personality, turn = 0) {
  const t = linesTable({ claims: personality?.claims }) || PLACEHOLDER_LINES;
  return heaterLineFor(claimId in t ? claimId : "NONE", { ...t, "*": t.NONE || PLACEHOLDER_LINES["*"] }, turn);
}

// Heater never pre-empts the Ref (rehearsal fix, 8 Nov 2026): before the stamp, Heater may not
// mention the Ref or say or hint at any verdict. These are the words that would.
const PREEMPT = new RegExp([
  "\\bref(eree)?\\b", "\\bref's\\b", "\\bverdicts?\\b", "\\bruled\\b", "\\bruling\\b",
  "\\bsurviv", "\\bnot supported\\b", "\\binsufficient\\b", "\\bdata (is |was )?(invalid|broken)\\b",
  "\\bblocked\\b", "\\bcan'?t run\\b", "\\bworth investigating\\b", "\\bcan'?t compare\\b",
  "\\bedge unverified\\b", "\\bcandidate\\b", "\\bno sign of\\b", "\\bthrew out\\b", "\\bcalled it\\b",
].join("|"), "i");

/** True when ``text`` mentions the Ref or a verdict, so it may be said only after the stamp. */
export const preemptsRef = (text) => PREEMPT.test(String(text || ""));

/** Split a Heater line by sentence: ``first`` keeps, in order, the sentences that do not pre-empt
 *  the Ref; ``later`` the ones that do, for after the stamp. Nothing is dropped or reworded. */
export function splitTake(text) {
  const sentences = String(text || "").trim().split(/(?<=[.!?…])\s+(?=["'(A-Z])/).filter(Boolean);
  return {
    first: sentences.filter((s) => !preemptsRef(s)).join(" "),
    later: sentences.filter((s) => preemptsRef(s)).join(" "),
  };
}

/** Heater's two lines for a dialogue answer. ``take`` is said before the Ref: the API's heater_text
 *  (since Max's 8 Nov fix, the hot take only) when it does not pre-empt the Ref, else ``fallbackTake()``.
 *  ``lastWord`` is said after the stamp: the API's heater_reaction, else a take that was held back,
 *  else "" (the page then uses reactFor). ``api`` is null offline or for a forced record. */
export function dialogueLines(api, fallbackTake) {
  const str = (x) => (typeof x === "string" ? x.trim() : "");
  const apiTake = str(api?.heater_text);
  const takeOk = Boolean(apiTake) && !preemptsRef(apiTake);
  return {
    take: takeOk ? apiTake : fallbackTake(),
    takeFromApi: takeOk,
    lastWord: str(api?.heater_reaction) || (apiTake && !takeOk ? apiTake : ""),
  };
}

/** Heater's reaction to a verdict ("react": decision -> [lines]). */
export function reactFor(decision, personality, turn = 0) {
  const r = personality?.react?.[decision];
  const arr = (Array.isArray(r) ? r : [r]).filter(isStr);
  return arr.length ? arr[Math.abs(turn) % arr.length] : "";
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
  ref: { rate: 1.0, pitch: 1.05 },   // user, 8 Nov: never the same as Frost (0.95 / 0.9)
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

/** Extra time a voiced line may take beyond fallbackSpeechMs before speak() stops waiting. */
export const SPEECH_GRACE_MS = 2500;

/** The longest speak() waits for the browser's speech to report its end. Some browsers (headless
 *  Chromium, a hidden tab, no installed voice) never fire onend or onerror; without this limit the
 *  sequence would stop after the Ref's line and the stamp and end pose would never show. */
export function speechGuardMs(text, rate = 1) {
  return fallbackSpeechMs(text, rate) + SPEECH_GRACE_MS;
}
