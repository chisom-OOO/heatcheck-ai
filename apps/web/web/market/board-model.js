// Market board: pure display logic for one game card. No DOM, no fetch.
//
// Every number shown comes from Max's API: the forecast row from GET /api/live-forecast and,
// for the comparison, the response of POST /api/investigate (forecast p_team_win, quote bid/ask,
// received time, Challenger checks, verdict). Nothing here computes a verdict: the board only
// words Max's. Probabilities and prices arrive as decimal strings.

export const VERDICT_WORTH = "Worth investigating · Edge unverified";
export const VERDICT_CANT = "Can't compare";

const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2026-11-07T22:29:52.672912Z" -> "Nov 7, 22:29:52 UTC" (seconds only when asked). */
export function fmtUtc(ts, { seconds = false } = {}) {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})/.exec(String(ts || ""));
  if (!m) return "unknown time";
  const hm = seconds ? `${m[4]}:${m[5]}:${m[6]}` : `${m[4]}:${m[5]}`;
  return `${MON[Number(m[2]) - 1]} ${Number(m[3])}, ${hm} UTC`;
}

/** A decimal-string probability as a percentage with one decimal ("0.71" -> "71.0%"). */
export const pct = (x) => `${(Math.round(Number(x) * 1000) / 10).toFixed(1)}%`;

const INPUT_WORDS = {
  elo_rating_home: "Elo rating (home)", elo_rating_away: "Elo rating (away)", home_court: "home court",
};
/** Model input names in plain words, in the file's order. */
export const inputsPlain = (inputs) => (inputs || []).map((n) => INPUT_WORDS[n] || String(n).replaceAll("_", " "));

/** Heater's line with the model's input identifiers in plain words (display only). */
export function heaterPlain(text, inputs) {
  let out = String(text || "");
  const names = inputs || [];
  const words = inputsPlain(names);
  names.forEach((n, i) => { out = out.split(n).join(words[i]); });
  return out;
}

/** Choose the mapping to investigate for a game: a two-sided quote first (a bids-only book can
 *  never be compared), VERIFIED before PROPOSED, then Polymarket before Kalshi. */
export function pickMapping(mappings, gameId) {
  const mine = (mappings || []).filter((m) => m.game_id === gameId);
  if (!mine.length) return { mapping: null, note: "No market price was captured for this game" };
  const rank = (m) => [m.two_sided ? 0 : 1, m.status === "VERIFIED" ? 0 : 1, m.venue === "POLYMARKET" ? 0 : 1];
  const sorted = [...mine].sort((a, b) => {
    const ra = rank(a), rb = rank(b);
    return ra[0] - rb[0] || ra[1] - rb[1] || ra[2] - rb[2];
  });
  const best = sorted[0];
  if (!best.two_sided) return { mapping: null, note: `Only ${venueName(best.venue)} bids were captured, no ask, so there is no price to compare` };
  return { mapping: best, note: null };
}

export const venueName = (v) => ({ POLYMARKET: "Polymarket", KALSHI: "Kalshi" }[v] || String(v));

const CHECK_WORDS = {
  GAME_MATCH: () => "the game details differ between the forecast and the market",
  OUTCOME_MATCH: (d) => (/PROPOSED/.test(d) ? "the contract's rules haven't been verified yet"
    : "the contract isn't certainly a bet on this team winning"),
  QUOTE_FRESH: (d) => (/tipped/.test(d) ? "the game has already started" : "the price is too old"),
  QUOTE_SIDE: () => "the market shows only one side, so there's no price you could actually get",
  FORECAST_CUTOFF: () => "the forecast's data cutoff isn't before tip",
  FORECAST_SAMPLE: () => "the forecast is a SAMPLE with made-up numbers",
};

/** Plain reasons for every gating check that failed, in Max's order. */
export function failedReasons(resp) {
  return (resp?.challenger_checks || [])
    .filter((c) => c.status === "FAIL" && CHECK_WORDS[c.check_id])
    .map((c) => CHECK_WORDS[c.check_id](String(c.detail || "")));
}

/** The difference cell: SAMPLE or Can't compare when that is the answer, otherwise where the
 *  forecast sits against the quoted bid and ask (never against a midpoint). */
export function diffText(resp) {
  if (!resp) return VERDICT_CANT;
  if (resp.is_sample) return "SAMPLE";
  if (resp.verdict !== VERDICT_WORTH) return VERDICT_CANT;
  const p = Number(resp.forecast?.p_team_win);
  const bid = Number(resp.quote?.best_bid);
  const ask = Number(resp.quote?.best_ask);
  const pts = (x) => (Math.round(x * 1000) / 10).toFixed(1);
  if (resp.flag === "FORECAST_ABOVE_ASK") return `${pts(p - ask)} pts above the ask`;
  if (resp.flag === "FORECAST_BELOW_BID") return `${pts(bid - p)} pts below the bid`;
  if (resp.flag === "FORECAST_INSIDE_SPREAD") return "Inside the bid–ask spread";
  return VERDICT_CANT;
}

/** Everything one card shows. ``row`` is the forecast row; ``resp`` Max's investigate response
 *  (or null); ``error`` why there is none. */
export function cardView(row, { resp = null, error = null, forecast = null, isSample = false } = {}) {
  const sample = Boolean(resp ? resp.is_sample : isSample);
  const home = row.home_team;
  const teamName = resp?.team || home;
  const pTeam = resp ? resp.forecast?.p_team_win : row.p_home_win;
  const q = resp?.quote || null;
  const reasons = resp ? failedReasons(resp) : [error || "No comparison was run"];
  const verdict = resp?.verdict === VERDICT_WORTH ? VERDICT_WORTH : VERDICT_CANT;
  const recorded = !sample && resp?.mode === "RECORDED";
  return {
    title: `${row.away_team} at ${home}`,
    tip: `Tip ${fmtUtc(row.tip_utc)}`,
    sample,
    forecast: `${teamName} ${pct(pTeam)} to win`,
    forecastNote: sample ? "SAMPLE: invented value" : `Model: ${resp?.forecast?.model || forecast?.model || ""}`,
    price: q && q.best_bid != null && q.best_ask != null
      ? `${venueName(q.venue)}: bid ${pct(q.best_bid)} · ask ${pct(q.best_ask)}`
      : q ? `${venueName(q.venue)}: one-sided (bid ${q.best_bid ?? "none"}, ask ${q.best_ask ?? "none"})`
        : "No price",
    diff: resp ? diffText(resp) : sample ? "SAMPLE" : VERDICT_CANT,
    cutoff: fmtUtc(resp?.forecast?.data_cutoff_utc || forecast?.data_cutoff_utc),
    recorded,
    received: q ? fmtUtc(q.received_utc, { seconds: true }) + (recorded ? " (RECORDED, not live)" : "")
      : "no price received",
    inputs: inputsPlain(resp?.forecast?.inputs_used || forecast?.inputs_used).join(", "),
    verdict,
    verdictKind: verdict === VERDICT_WORTH ? "worth" : "cant",
    why: verdict === VERDICT_WORTH
      ? `Same game, team and outcome; the price ${recorded ? "was fresh when recorded" : "is fresh"}. Nothing shows the model beats the market.`
      : reasons.join("; "),
    dataNote: resp?.data_note || (sample ? "SAMPLE forecast: values are invented, not a real forecast." : ""),
    // Max's server decides when a caveat applies (e.g. the model's home-team bias); the card shows its text.
    caveats: Array.isArray(resp?.caveats) ? resp.caveats.filter((c) => typeof c === "string" && c) : [],
    canAsk: Boolean(resp),
  };
}

/** The Ref's plain words for an investigation: the verdict first, then why. */
export function marketRefPlain(resp) {
  const recorded = !resp?.is_sample && resp?.mode === "RECORDED";
  const rec = recorded
    ? ` RECORDED: price received ${resp?.quote ? fmtUtc(resp.quote.received_utc, { seconds: true }) : "unknown time"}, not live.`
    : "";
  if (resp?.verdict === VERDICT_WORTH) {
    return `Worth investigating, edge unverified. Same game, same team, same outcome, and the price ${recorded ? "was fresh when recorded" : "is fresh"}. `
      + "Nothing shows this model beats the market, so the gap is a question to look into, not a finding." + rec;
  }
  const why = failedReasons(resp);
  return `Can't compare: ${why.length ? why.join("; ") : "the comparison could not be run"}.${rec}`;
}

/** Stamp text and colour class: SAMPLE says so plainly. */
export function marketStamp(resp) {
  if (resp?.is_sample) return { text: "SAMPLE", kind: "blocked" };
  if (resp?.verdict === VERDICT_WORTH) return { text: "EDGE UNVERIFIED", kind: "insufficient" };
  return { text: "CAN'T COMPARE", kind: "blocked" };
}

/** Heater's end pose after an investigation. */
export const marketEndState = (resp) => (resp?.verdict === VERDICT_WORTH ? "thinking" : "blocked");
