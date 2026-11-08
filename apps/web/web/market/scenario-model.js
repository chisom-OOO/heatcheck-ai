// Scenario view for one game card: pure display logic. No DOM, no fetch.
//
// Every number comes from GET /api/scenario?game_id=... (Max's server, passed through unchanged;
// format "heatcheck-scenario/1", proposed in apps/web/HANDOFF.md). The page computes no
// probability, range or n: it checks the answer is well formed, words it, and positions a bar.
// A scenario is always an ESTIMATE, never a finding, and never changes the market verdict: the
// Ref's line keeps "Edge unverified".

import { pct } from "./board-model.js";

export const SCENARIO_FORMAT = "heatcheck-scenario/1";
export const EDGE_UNVERIFIED = "Edge unverified: nothing shows this model beats the market.";
/** Below half a point the change rounds to nothing at one decimal: Heater calls it flat. */
export const FLAT = 0.005;

const PROB = /^(0(\.\d+)?|1(\.0+)?)$/;
const isProb = (x) => typeof x === "string" && PROB.test(x);

/** Why one scenario cannot be shown, or null when it is well formed. */
export function scenarioProblem(s) {
  if (!s || typeof s !== "object") return "not an object";
  if (typeof s.scenario_id !== "string" || !s.scenario_id) return "no scenario_id";
  if (typeof s.text !== "string" || !s.text.trim()) return "no scenario text";
  if (s.label !== "ESTIMATE") return `label is ${JSON.stringify(s.label ?? null)}, not "ESTIMATE"`;
  if (!isProb(s.p_team_win)) return "p_team_win is not a decimal string between 0 and 1";
  const r = s.range;
  if (!r || !isProb(r.low) || !isProb(r.high)) return "range low/high are not decimal strings between 0 and 1";
  if (!(Number(r.low) <= Number(s.p_team_win) && Number(s.p_team_win) <= Number(r.high))) return "p_team_win is outside its range";
  if (!isProb(r.level) || !(Number(r.level) > 0 && Number(r.level) < 1)) return "range level is not a decimal between 0 and 1";
  if (!Number.isInteger(s.n) || s.n < 1) return "n is not a positive whole number";
  if (typeof s.n_unit !== "string" || !s.n_unit) return "no n_unit";
  if (!Array.isArray(s.caveats) || !s.caveats.length || !s.caveats.every((c) => typeof c === "string" && c.trim())) {
    return "no caveats (an estimate must say what it leaves out)";
  }
  return null;
}

/** Check a whole /api/scenario answer against the card it belongs to.
 *  Returns {status: OK|UNAVAILABLE, reason, team, baseline, isSample, scenarios, refused}. */
export function readScenarios(http, { gameId, resp = null } = {}) {
  const { status, body } = http || {};
  if (status === 404 && body?.error === "not found") {  // Max's server's answer to a path it lacks
    return { status: "UNAVAILABLE", reason: "Max's server has no scenario endpoint yet", scenarios: [], refused: [] };
  }
  if (status === 502 && body?.error === "UPSTREAM_UNAVAILABLE") {
    return { status: "UNAVAILABLE", reason: "Max's server is not answering", scenarios: [], refused: [] };
  }
  if (status !== 200 || body?.status !== "OK") {
    const why = body?.reason || body?.message || body?.error || `HTTP ${status}`;
    return { status: "UNAVAILABLE", reason: `no scenarios for this game (${why})`, scenarios: [], refused: [] };
  }
  const bad = (reason) => ({ status: "UNAVAILABLE", reason, scenarios: [], refused: [] });
  if (body.format !== SCENARIO_FORMAT) return bad(`unknown format ${JSON.stringify(body.format ?? null)}`);
  if (body.game_id !== gameId) return bad("the answer is for a different game");
  if (typeof body.is_sample !== "boolean") return bad("is_sample is missing");
  const base = body.baseline?.p_team_win;
  if (!isProb(base)) return bad("the baseline probability is missing");
  if (typeof body.team !== "string" || !body.team) return bad("the team is missing");
  if (resp) {  // the card already shows a forecast: the scenario must start from that same number
    if (resp.team && resp.team !== body.team) return bad(`the scenario is for ${body.team}, the card for ${resp.team}`);
    const cardP = resp.forecast?.p_team_win;
    if (cardP != null && Number(cardP) !== Number(base)) return bad("the scenario's baseline is not the card's forecast");
    if (Boolean(resp.is_sample) !== body.is_sample) return bad("the scenario and the card disagree on SAMPLE");
  }
  const scenarios = [];
  const refused = [];
  for (const s of Array.isArray(body.scenarios) ? body.scenarios : []) {
    const why = scenarioProblem(s);
    if (why) refused.push({ text: typeof s?.text === "string" ? s.text : String(s?.scenario_id ?? "?"), reason: why });
    else scenarios.push(s);
  }
  return { status: "OK", team: body.team, baseline: body.baseline, isSample: body.is_sample, source: body.source || "",
    scenarios, refused };
}

const pts = (d) => `${d >= 0 ? "+" : "−"}${(Math.round(Math.abs(d) * 1000) / 10).toFixed(1)} pts`;

/** Which way the scenario moves the team's chance: up, down or flat. */
export function direction(s, baseline) {
  const d = Number(s.p_team_win) - Number(baseline.p_team_win);
  return Math.abs(d) < FLAT ? "flat" : d > 0 ? "up" : "down";
}

/** Everything one scenario panel shows. Bar positions are fractions 0..1 of a 0–100% track. */
export function scenarioView(s, data) {
  const base = Number(data.baseline.p_team_win);
  const p = Number(s.p_team_win);
  const low = Number(s.range.low);
  const high = Number(s.range.high);
  const dir = direction(s, data.baseline);
  const covers = low <= base && base <= high;
  const levelPct = `${Math.round(Number(s.range.level) * 100)}%`;
  return {
    title: s.text,
    sample: data.isSample,
    label: "ESTIMATE",
    baseline: { head: "Forecast now", value: `${data.team} ${pct(data.baseline.p_team_win)}` },
    scenario: { head: "In this scenario", value: `${data.team} ${pct(s.p_team_win)}` },
    change: dir === "flat" ? "No real change" : pts(p - base),
    dir,
    range: `Range ${pct(s.range.low)} to ${pct(s.range.high)} (${levelPct})`,
    n: `Based on ${s.n.toLocaleString("en-US")} ${s.n_unit}`,
    caveats: [...s.caveats],
    coversBaseline: covers,
    bar: { base, p, low, high },
    barLabel: `Range ${pct(s.range.low)} to ${pct(s.range.high)}, scenario ${pct(s.p_team_win)}, forecast now ${pct(data.baseline.p_team_win)}`,
    sampleNote: data.isSample ? "SAMPLE: invented values, not a real estimate" : "",
  };
}

/** Heater's reaction: direction only, no digits, never a SAMPLE value. */
export function heaterScenarioLine(s, data) {
  if (data.isSample) {
    return "This scenario uses SAMPLE numbers: they are made up, so there is nothing real to react to yet.";
  }
  const team = data.team;
  const dir = direction(s, data.baseline);
  if (dir === "up") return `That pushes ${team} UP! I can FEEL it heating up!`;
  if (dir === "down") return `Whoa, that knocks ${team} DOWN! Somebody turn the heat back on!`;
  return `That barely moves ${team}. I'm not buying the hype on this one.`;
}

/** The Ref's words: the estimate with its range, n and caveats, then "Edge unverified". */
export function refScenarioText(s, data) {
  if (data.isSample) return `SAMPLE scenario: the numbers are made up, so there is nothing to read. ${EDGE_UNVERIFIED}`;
  const v = scenarioView(s, data);
  const change = v.dir === "flat" ? "no real change" : v.change;
  const noise = v.coversBaseline ? " The range still includes the current forecast, so the change may be noise." : "";
  return `ESTIMATE, not a finding. If ${lowerFirst(s.text)}: ${data.team} ${pct(s.p_team_win)}, against ${pct(data.baseline.p_team_win)} now (${change}).`
    + ` ${v.range}, ${lowerFirst(v.n)}.${noise}`
    + ` Caveats: ${s.caveats.map((c) => c.replace(/\.$/, "")).join("; ")}. ${EDGE_UNVERIFIED}`;
}

const lowerFirst = (t) => (/^[A-Z][a-z]/.test(t) ? t[0].toLowerCase() + t.slice(1) : t);

// Stamp rule (2026-11-08): ESTIMATE whenever the number comes from data, preset or typed;
// YOUR ASSUMPTION when the user supplied the number. Typed what-ifs show the server's own "stamp"
// (Max's whatifStamp in whatif/whatif.js). Presets come from GET /api/scenario, whose numbers are
// always Research's data: their stamp is the scenario's own label. Kinds match Max's STAMPS.
export const STAMP_ESTIMATE = { text: "ESTIMATE", kind: "insufficient" };
const STAMP_SAMPLE = { text: "SAMPLE", kind: "blocked" };
const STAMP_NO_NUMBER = { text: "NO NUMBER", kind: "blocked" };

/** Preset scenario stamp: the scenario's own label from GET /api/scenario (readScenarios accepts only
 *  "ESTIMATE"), or SAMPLE when the numbers are invented. */
export function scenarioStamp(data, s) {
  if (data.isSample) return STAMP_SAMPLE;
  return s?.label === "ESTIMATE" ? STAMP_ESTIMATE : STAMP_NO_NUMBER;
}

/** Heater's end pose. Never vindicated: a scenario is an estimate, not a result. */
export function scenarioEndState(s, data) {
  if (data.isSample) return "blocked";
  const dir = direction(s, data.baseline);
  if (dir === "flat" || scenarioView(s, data).coversBaseline) return "unsure";
  return dir === "up" ? "thinking" : "cooled";
}
