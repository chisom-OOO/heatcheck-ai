// Idea board: pure display logic for Research's idea-family results (heatcheck-idea-family/1).
// No DOM, no fetch. Every number is read from Research's results.json as served by
// GET /api/ideas; nothing here computes a statistic or a verdict, it only words Research's.
//
// Verdicts are exploratory: CANDIDATE means "worth its own pre-registered test", never a
// finding, and never SURVIVED_PROTOCOL.

const NTH = { 1: "1st", 2: "2nd", 3: "3rd", 4: "4th" };
const NTH_WORD = { 1: "first", 2: "second", 3: "third", 4: "fourth" };
const NUM_WORD = { 0: "no", 1: "one", 2: "two", 3: "three", 4: "four", "3+": "three or more" };
const MONTH = { "10": "October", "11": "November", "12": "December", "01": "January", "02": "February", "03": "March" };
const DAY = { Mon: "Monday", Tue: "Tuesday", Wed: "Wednesday", Thu: "Thursday", Fri: "Friday", Sat: "Saturday", Sun: "Sunday" };

const restDays = (lvl, words) => {
  if (lvl === "0") return "no days of rest";
  if (lvl === "1") return words ? "one day of rest" : "1 day of rest";
  return words ? `${NUM_WORD[lvl]} days of rest` : `${lvl} days of rest`;
};
const streak = (lvl, what, words) => {
  const n = Number(lvl);
  const count = words ? NUM_WORD[lvl] : lvl;
  return n === 1 ? `after a ${what}` : `after ${count} ${what}s in a row`;
};

/** The condition in plain words ("the away team is on a back-to-back"). ``words`` spells
 *  numbers out, for Heater's lines, which carry no digits. */
export function conditionText(template, params, { words = false } = {}) {
  const { level: l } = params;
  if (template === "GAME_HOME_WIN_SPLIT") {
    switch (params.feature) {
      case "home_rest_days": return `the home team has ${restDays(l, words)}`;
      case "away_rest_days": return `the away team has ${restDays(l, words)}`;
      case "rest_advantage": return { home_more: "the home team is more rested", equal: "both teams are equally rested",
        away_more: "the away team is more rested" }[l];
      case "home_back_to_back": return "the home team is on a back-to-back";
      case "away_back_to_back": return "the away team is on a back-to-back";
      case "elo_gap": return {
        "home_fav_100+": words ? "the home team is the Elo favourite by a hundred points or more" : "the home team is the Elo favourite by 100+ points",
        home_fav_0_100: words ? "the home team is a slight Elo favourite" : "the home team is the Elo favourite by under 100 points",
        away_fav_0_100: words ? "the away team is a slight Elo favourite" : "the away team is the Elo favourite by under 100 points",
        "away_fav_100+": words ? "the away team is the Elo favourite by a hundred points or more" : "the away team is the Elo favourite by 100+ points",
      }[l];
      case "month": return `the game is in ${MONTH[l] || l}`;
      case "day_of_week": return `the game is on a ${DAY[l] || l}`;
      default: return `${params.feature} is ${l}`;
    }
  }
  switch (params.condition) {
    case "after_makes": return streak(l, "make", words);
    case "after_misses": return streak(l, "miss", words);
    case "shot_value": return words ? "on three-pointers" : "on 3-pointers";
    case "period": return l === "OT" ? "in overtime" : `in the ${words ? NTH_WORD[l] : NTH[l]} quarter`;
    default: return `when ${params.condition} is ${l}`;
  }
}

const MORE = { greater: "more", less: "less", two_sided: "a different share of" };

/** The idea as a sentence: "Home teams win more when the away team is on a back-to-back". */
export function ideaTitle(r, { words = false } = {}) {
  const cond = conditionText(r.template, r.params, { words });
  const alt = r.params.alternative;
  if (r.template === "GAME_HOME_WIN_SPLIT") {
    return alt === "two_sided" ? `Home teams win a different share of games when ${cond}`
      : `Home teams win ${MORE[alt]} when ${cond}`;
  }
  const verb = alt === "two_sided" ? "go in at a different rate" : `go in ${MORE[alt]} often`;
  return `Shots ${verb} ${cond}`;
}

const pct = (x) => `${(Math.round(Number(x) * 1000) / 10).toFixed(1)}%`;
const count = (n) => (Number.isInteger(n) ? n.toLocaleString("en-US") : String(n));
/** Research's p-values are on a 1/1000 grid (B = 999): three decimals, never rounded away. */
export const fmtP3 = (p) => Number(p).toFixed(3);

/** The numbers line: both groups' rates with their sizes, read from the result. */
export function numbersText(r) {
  if (r.rate_condition == null || r.rate_rest == null) {
    return r.n_condition != null ? `${count(r.n_condition)} vs ${count(r.n_rest)} ${r.template === "GAME_HOME_WIN_SPLIT" ? "games" : "shots"}` : "No numbers: the test did not run";
  }
  if (r.template === "GAME_HOME_WIN_SPLIT") {
    return `Home teams won ${pct(r.rate_condition)} of ${count(r.n_condition)} such games, ${pct(r.rate_rest)} of the other ${count(r.n_rest)}`;
  }
  return `${pct(r.rate_condition)} of ${count(r.n_condition)} such shots went in, ${pct(r.rate_rest)} of the other ${count(r.n_rest)}`;
}

/** Multiplicity in plain words, with Research's Holm p. */
export const chanceText = (r, n) => (r.p_holm == null ? "No p-value: too little data"
  : `p = ${fmtP3(r.p_holm)} after allowing for the ${n} ideas tested together (before: ${fmtP3(r.p_raw)})`);

export const VERDICT_WORDS = Object.freeze({
  CANDIDATE: "Worth a proper test",
  NOT_A_CANDIDATE: "No sign of it",
  INSUFFICIENT_EVIDENCE: "Too little data",
});
const VERDICT_KIND = { CANDIDATE: "candidate", NOT_A_CANDIDATE: "none", INSUFFICIENT_EVIDENCE: "thin" };
export const CANDIDATE_NOTE = "A lead, not a finding: it needs its own pre-registered test on games nobody has looked at.";

/** Everything one idea card shows. */
export function ideaCard(r, family) {
  return {
    title: ideaTitle(r),
    kind: r.template === "GAME_HOME_WIN_SPLIT" ? "Game result" : "Shot",
    numbers: numbersText(r),
    chance: chanceText(r, family.n_ideas),
    verdict: VERDICT_WORDS[r.verdict] || r.verdict,
    verdictKind: VERDICT_KIND[r.verdict] || "thin",
    note: r.verdict === "CANDIDATE" ? CANDIDATE_NOTE : "",
    canAsk: family.mode === "development",
  };
}

/** Heater pitches the idea (a fan's hot take, no digits). */
export function heaterIdeaLine(r) {
  const t = ideaTitle(r, { words: true });
  return `${t.replace(/\b(more|less)\b/, (m) => m.toUpperCase())}. I'm CALLING it!`;
}

/** The Ref's plain words: verdict first, then Research's numbers. */
export function refIdeaText(r, family) {
  const n = family.n_ideas;
  if (r.verdict === "INSUFFICIENT_EVIDENCE") {
    return `Too little data to tell. ${numbersText(r)}; the test needs at least 30 games or 200 shots on each side.`;
  }
  const head = r.verdict === "CANDIDATE" ? "Worth a proper test." : "No sign of it.";
  const tail = r.verdict === "CANDIDATE" ? ` ${CANDIDATE_NOTE}` : "";
  return `${head} ${numbersText(r)}. ${chanceText(r, n)}.${tail}`;
}

/** Stamp text and colour class. */
export function ideaStamp(r) {
  return { CANDIDATE: { text: "WORTH A TEST", kind: "insufficient" },
    NOT_A_CANDIDATE: { text: "NO SIGN", kind: "not-supported" },
    INSUFFICIENT_EVIDENCE: { text: "TOO LITTLE DATA", kind: "blocked" } }[r.verdict]
    || { text: "NO RULING", kind: "untested" };
}

/** Heater's end pose: intrigued by a lead (never vindicated: it is not a finding). */
export const ideaEndState = (r) => ({ CANDIDATE: "thinking", NOT_A_CANDIDATE: "cooled" }[r.verdict] || "unsure");

/** The development family's header line. */
export function familyHeadline(f) {
  const cands = f.results.filter((r) => r.verdict === "CANDIDATE").length;
  const scope = f.data?.season ? `${f.data.season} development games` : "development data";
  return `${f.n_ideas} ideas tested together on ${scope}: ${cands} worth a proper test`;
}

/** The planted-truth check for a synthetic family, in plain words. */
export function scoreboardText(f) {
  const t = f.scoreboard?.tally;
  if (!t) return { title: "Made-up league", lines: ["The answer key has not been revealed for this league."] };
  const planted = t.planted_effects_found + t.planted_effects_missed;
  const nulls = t.nulls_correctly_not_flagged + t.false_candidates;
  const g = f.truth?.gamma_logodds;
  return {
    title: g === 0 ? "Made-up league with no streak effect (control)" : `Made-up league with a planted streak effect (strength ${g})`,
    lines: [
      `Found ${t.planted_effects_found} of ${planted} planted effect${planted === 1 ? "" : "s"}; missed ${t.planted_effects_missed}`,
      `Correctly ignored ${t.nulls_correctly_not_flagged} of ${nulls} ideas with nothing there`,
      `False alarms: ${t.false_candidates}`,
    ],
  };
}
