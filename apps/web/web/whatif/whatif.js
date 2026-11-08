// Scenario questions and free-text routing on the demo page. Max's API does the parsing,
// confirmation binding and arithmetic (POST /api/route, /api/scenario, /api/scenario/estimate);
// this file only words and draws what it returns. Relative URLs only; all text via textContent.

import { fmtUtc } from "../market/board-model.js";

export const ROUTE_URL = "/api/route";
export const SCENARIO_URL = "/api/scenario";
export const ESTIMATE_URL = "/api/scenario/estimate";

export async function postJson(url, body, { fetchImpl = fetch } = {}) {
  const r = await fetchImpl(url, { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body) });
  let data = null;
  try { data = await r.json(); } catch { data = null; }
  return { ok: r.ok, status: r.status, data };
}

/** Where the page sends a typed message. Any failure falls back to the dialogue. */
export async function routeMessage(message, opts) {
  try {
    const r = await postJson(ROUTE_URL, { message }, opts);
    if (r.ok && r.data && ["OPEN_BOARD", "OPEN_CARD", "SCENARIO", "DIALOGUE"].includes(r.data.action)) return r.data;
  } catch { /* the route service is down: the dialogue still works */ }
  return { action: "DIALOGUE", game_id: null, reason: "route unavailable" };
}

/** The body that confirms exactly what the server showed; the server re-derives the id. */
export function confirmBody(it) {
  return { game_id: it.game_id, changes: it.changes, focus_team: it.focus_team,
    interpretation_id: it.interpretation_id, confirmed: true, message_sha256: it.message_sha256 };
}

const pct = (p) => `${(Math.round(Number(p) * 1000) / 10).toFixed(1)}%`;

export const TYPE_LABEL = {
  MODEL_RECALC: "ESTIMATE",  // the forecast's own Elo model, recalculated: a number from data
  ESTIMATE: "ESTIMATE",
  YOUR_ASSUMPTION: "YOUR ASSUMPTION",
  HYPOTHETICAL_PRICE: "YOUR ASSUMPTION",  // a market price the user supplied
  NO_NUMBER: "NO NUMBER",
  FAILED_TEST: "FAILED OUR TEST",
};

/** The stamp is the server's (heatcheck.agents.scenario.stamp_for): ESTIMATE when the number comes from
 *  data, YOUR ASSUMPTION when it depends on a number the user supplied, SAMPLE, or NO NUMBER. The page never
 *  decides it; an answer without a known stamp shows NO NUMBER. */
export const STAMPS = { ESTIMATE: "insufficient", "YOUR ASSUMPTION": "insufficient", SAMPLE: "blocked", "NO NUMBER": "blocked" };
const SOURCE_STAMP = { DATA: "ESTIMATE", USER: "YOUR ASSUMPTION" };
export function whatifStamp(est) {
  let text = Object.hasOwn(STAMPS, est?.stamp) ? est.stamp : "NO NUMBER";
  // The server also says where the number comes from; if the two ever disagree, show no number.
  if (est && "number_source" in est && SOURCE_STAMP[est.number_source] && SOURCE_STAMP[est.number_source] !== text) text = "NO NUMBER";
  return { text, kind: STAMPS[text] };
}

/** Everything the result panel shows, as plain strings. No arithmetic here beyond formatting. */
export function scenarioView(est) {
  const sample = Boolean(est.is_sample);
  const base = est.baseline ? pct(est.baseline.p) : sample ? "SAMPLE: not shown" : "unavailable";
  let scen = "No number";
  if (est.scenario) {
    scen = pct(est.scenario.p);
    if (!est.scenario.range_is_point) scen += ` (range ${pct(est.scenario.range[0])} to ${pct(est.scenario.range[1])})`;
  } else if (!sample && est.hypothetical_price != null && !est.effects.some((e) => e.type !== "HYPOTHETICAL_PRICE")) {
    scen = `${base} (forecast unchanged)`;
  }
  const effects = est.effects.map((e) => {
    const facts = [];
    if (e.n != null) facts.push(`n = ${e.n} games`);
    if (e.verdict) facts.push(`verdict: ${e.verdict}`);
    if (e.detail?.interval) facts.push(e.detail.interval);
    if (e.type === "ESTIMATE" || e.type === "FAILED_TEST") {
      if (e.elo_range_home) facts.push(`Elo shift ${e.elo_range_home[0]} to ${e.elo_range_home[1]} (home side)`);
    }
    return { label: TYPE_LABEL[e.type] || e.type, kind: e.type.toLowerCase(), text: e.text,
      facts: facts.join(" · "), caveats: e.caveats || [], included: Boolean(e.included) };
  });
  const flags = (est.challenger_checks || []).filter((c) => c.status === "FLAG" || c.status === "FAIL")
    .map((c) => `${c.check_id}: ${c.detail}`);
  return {
    badge: whatifStamp(est).text,
    title: `${est.game} · what-if for ${est.focus_team}`,
    baselineLabel: `Baseline: ${est.focus_team} to win`,
    baseline: base,
    baselineNote: est.baseline ? `Live forecast, data to ${fmtUtc(est.baseline.data_cutoff_utc)}` : (est.sample_note || ""),
    scenarioLabel: `Scenario (${whatifStamp(est).text})`,
    scenario: scen,
    price: est.hypothetical_price != null ? `Your market price: ${pct(est.hypothetical_price)}` : "",
    effects,
    flags,
    verdict: est.verdict,
    receipt: est.evidence_id ? `Receipt ${est.evidence_id.slice(0, 12)} · ${fmtUtc(est.recorded_at_utc, { seconds: true })}` : "",
  };
}

const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
};

/** The interpretation, for the user to confirm. No numbers. */
export function renderInterpretation(root, it, { onConfirm, onCancel } = {}) {
  root.replaceChildren();
  root.hidden = false;
  const head = el("header", "scn-head");
  head.append(el("span", "scn-badge", "CONFIRM"), el("span", "scn-title", `${it.game} · how Heater read it`));
  root.append(head);
  const ul = el("ul", "scn-list");
  for (const line of it.interpretation || []) ul.append(el("li", "", line));
  root.append(ul);
  const row = el("div", "scn-actions");
  const yes = el("button", "scn-confirm", "Yes, run it");
  yes.type = "button";
  const no = el("button", "scn-cancel", "Not right");
  no.type = "button";
  yes.addEventListener("click", () => { yes.disabled = true; no.disabled = true; onConfirm?.(); });
  no.addEventListener("click", () => { yes.disabled = true; no.disabled = true; onCancel?.(); });
  row.append(yes, no);
  root.append(row);
}

/** Baseline vs scenario side by side, each change with its label, n, verdict and caveats. */
export function renderEstimate(root, est) {
  const v = scenarioView(est);
  root.replaceChildren();
  root.hidden = false;
  const head = el("header", "scn-head");
  head.append(el("span", `scn-badge${v.badge === "SAMPLE" ? " sample" : ""}`, v.badge), el("span", "scn-title", v.title));
  root.append(head);
  const grid = el("div", "scn-compare");
  const col = (label, value, note, cls) => {
    const c = el("div", `scn-col ${cls}`);
    c.append(el("div", "scn-col-label", label), el("div", "scn-col-value", value));
    if (note) c.append(el("div", "scn-col-note", note));
    return c;
  };
  grid.append(col(v.baselineLabel, v.baseline, v.baselineNote, "base"),
    col(v.scenarioLabel, v.scenario, v.price, "what-if"));
  root.append(grid);
  const ul = el("ul", "scn-effects");
  for (const e of v.effects) {
    const li = el("li", `scn-effect ${e.kind}${e.included ? "" : " excluded"}`);
    li.append(el("span", "scn-effect-label", e.label), el("span", "scn-effect-text", ` ${e.text}`));
    if (e.facts) li.append(el("div", "scn-effect-facts", e.facts));
    for (const c of e.caveats) li.append(el("div", "scn-effect-caveat", `Caveat: ${c}`));
    ul.append(li);
  }
  root.append(ul);
  if (v.flags.length) {
    const f = el("ul", "scn-flags");
    for (const x of v.flags) f.append(el("li", "", x));
    root.append(el("div", "scn-flags-title", "The Challenger flagged"), f);
  }
  root.append(el("p", "scn-verdict", v.verdict));
  if (v.receipt) root.append(el("p", "scn-receipt", v.receipt));
}
