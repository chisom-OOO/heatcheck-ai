// HeatCheck demo page: ask a question, Heater gives a hot take, the Ref checks it against a
// real evidence record, and the verdict stamp lands as Heater changes pose.
//
// Answer source, in order:
//   1. Max's dialogue API (POST /api/dialogue, same origin: the UI server passes it through to
//      Max's server) for Heater's line, the claim and the evidence id;
//   2. offline: question -> claim by keywords, Heater's line from heater_personality.json.
// The Ref's words and every number always come from the evidence record (GET /api/evidence,
// or the byte-copy fixture of Max's ledger). ?debug=1 opens a drawer with the internals.

import { loadPersonality, mount } from "./heater/heater.js";
import {
  CLAIM_TITLES, DEFAULT_PERSONALITY, NEVER_SEEN, TIMING, fmtP, latestFor, parseJsonl, reactFor,
  refPlain, routeQuestion, stampFor, stateForDecision, takeFor,
} from "./heater/heater-model.js";
import { loadBoard, renderBoard } from "./market/board.js";
import { failedReasons, fmtUtc, heaterPlain, marketEndState, marketRefPlain, marketStamp } from "./market/board-model.js";
import { heaterScenarioLine, refScenarioText, scenarioEndState, scenarioStamp } from "./market/scenario-model.js";
import { loadIdeas, renderIdeas } from "./ideas/idea-board.js";
import { heaterIdeaLine, ideaEndState, ideaStamp, ideaTitle, refIdeaText } from "./ideas/idea-model.js";
import {
  ESTIMATE_URL, SCENARIO_URL, confirmBody, whatifStamp, postJson, renderEstimate, renderInterpretation, routeMessage,
} from "./whatif/whatif.js";
import { createVoice } from "./voice.js";

const params = new URLSearchParams(location.search);
const DEBUG = params.get("debug") === "1";
// Relative URLs only: same origin on any port, no CORS. server/app.py forwards Max's endpoints.
const DIALOGUE_URL = "/api/dialogue";
const FIXTURE = new URL("./heater/fixtures/evidence_real_game.jsonl", import.meta.url);
const $ = (id) => document.getElementById(id);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const ui = {
  bubble: $("bubble"), take: $("take"), react: $("react"), ref: $("ref"), refTitle: $("ref-title"),
  refText: $("ref-text"), stamp: $("stamp"), evidence: $("evidence"), evidenceBody: $("evidence-body"),
  hint: $("hint"), q: $("q"), go: $("go"), chips: [...document.querySelectorAll(".chip")],
  scenario: $("scenario"),
};
const state = { heater: null, personality: DEFAULT_PERSONALITY, personalitySource: "built-in defaults",
  ledger: null, turn: 0, busy: false, voiceOn: params.get("voice") !== "0", forceRecord: "", log: [] };

function log(msg) {
  state.log.push(`${new Date().toISOString().slice(11, 19)} ${msg}`);
  if (DEBUG) renderDebug();
}

// ------------------------------------------------------------------ data
async function loadLedger() {
  try {
    const r = await fetch("/api/evidence", { headers: { Accept: "application/json" } });
    if (r.ok) {
      const body = await r.json();
      if (Array.isArray(body.entries) && body.entries.length) {
        return { entries: body.entries, verified: true, source: `${body.ledger} (verified by ${body.verified_by})` };
      }
    }
  } catch { /* no evidence endpoint: fixture */ }
  const r = await fetch(FIXTURE);
  if (!r.ok) throw new Error(`fixture ledger: HTTP ${r.status}`);
  return { entries: parseJsonl(await r.text()), verified: false,
    source: "fixture: byte copy of reports/max/logs/2026-11-07-loop/evidence_real_game.jsonl" };
}

async function askDialogue(question) {
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), 30000);  // Max's doc: client timeout of at least 30 s
  try {
    const r = await fetch(DIALOGUE_URL, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }), signal: ctl.signal });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const d = await r.json();
    if (typeof d.claim_id !== "string") throw new Error("no claim_id in reply");
    return d;
  } finally {
    clearTimeout(t);
  }
}

/** Decide the claim, Heater's line and the evidence entry for a question. */
async function answer(question) {
  let api = null;
  try {
    api = await askDialogue(question);
    log(`dialogue API: claim ${api.claim_id}, verdict ${api.verdict}, evidence ${api.evidence_record_id}`);
  } catch (e) {
    log(`dialogue API unavailable (${e.name === "AbortError" ? "timeout" : e.message}); offline routing`);
  }
  if (api) state.ledger = await loadLedger();      // the API may have appended a new entry
  const forced = state.forceRecord ? state.ledger.entries[Number(state.forceRecord)] : null;
  const claimId = forced ? forced.identity.claim.claim_id : api ? api.claim_id : routeQuestion(question);
  let entry = forced
    || (api?.evidence_record_id && state.ledger.entries.find((e) => e.evidence_id === api.evidence_record_id))
    || latestFor(state.ledger.entries, claimId);
  if (api?.verdict && entry && entry.identity.decision !== api.verdict) {
    log(`API verdict ${api.verdict} != record ${entry.identity.decision}; the record wins`);
  }
  if (!entry) entry = null;
  // The API ruled but this page's ledger copy lacks the entry (e.g. the UI server shows another
  // ledger file): show the API's own verdict and deterministic Ref text, never "not tested".
  const apiOnly = !entry && !forced && api?.verdict
    ? { verdict: api.verdict, refText: api.ref_text, lane: api.lane, evidenceId: api.evidence_record_id }
    : null;
  if (apiOnly) log(`record ${api.evidence_record_id} not in this page's ledger; using the API's verdict and Ref text`);
  const take = (!forced && api?.heater_text) || takeFor(claimId, state.personality, state.turn);
  return { claimId, entry, apiOnly, take, takeSource: !forced && api?.heater_text ? "dialogue API" : state.personalitySource };
}

/** The Ref's words: plain text from the record; else the API's own text (with the sealed-season
 *  note for a confirmatory result); else "no ruling yet". */
function refLineFor(a) {
  if (a.entry) return refPlain(a.entry, state.personality).text;
  if (a.apiOnly) {
    const t = String(a.apiOnly.refText || "").trim();
    return a.apiOnly.lane === "CONFIRMATORY" && !t.includes(NEVER_SEEN)
      ? `${t} It was ${NEVER_SEEN}.` : t;
  }
  return "No ruling yet. We haven't run a test for this one, so there's nothing to report.";
}

// ------------------------------------------------------------------ rendering
function reset() {
  ui.hint.hidden = true;
  ui.bubble.hidden = true;
  ui.react.hidden = true;
  ui.ref.hidden = true;
  ui.ref.className = "ref";
  ui.stamp.hidden = true;
  ui.evidence.hidden = true;
  ui.evidence.open = false;
  ui.scenario.hidden = true;
}

function restartAnim(el) {
  el.style.animation = "none";
  void el.offsetWidth;
  el.style.animation = "";
}

function evidenceDetails(entry, verified) {
  const id = entry.identity;
  const dl = document.createElement("dl");
  const row = (k, v) => {
    const dt = document.createElement("dt");
    dt.textContent = k;
    const dd = document.createElement("dd");
    if (v instanceof Node) dd.append(v); else dd.textContent = v;
    dl.append(dt, dd);
  };
  row("Claim", id.claim.plan?.statement || id.claim.statement || id.claim.claim_id);
  row("Verdict", `${id.decision}: ${id.reason || ""}`);
  const attacks = Array.isArray(id.attack_results) ? id.attack_results : [];
  const perm = attacks.find((a) => String(a.test_id_version).startsWith("A-PERMUTATION-NULL@"));
  if (perm && typeof perm.effect_estimate === "number") {
    row("Effect", `${perm.effect_estimate >= 0 ? "+" : ""}${perm.effect_estimate.toFixed(4)} (bias-corrected; p = ${fmtP(perm.p_value)}, ${perm.details?.B_effective ?? "?"} permutations)`);
  }
  const d = id.data || {};
  const code = (s) => { const c = document.createElement("code"); c.textContent = s; return c; };
  if (id.source === "RECORDED_RESEARCH_RESULT") {
    // a receipted Research final copied into the ledger: no attacks were run by the Referee
    const r = id.result || {};
    const det = r.detail || {};
    row("Source", "Research's recorded final run, copied into the ledger, not recomputed");
    row("Season", `${d.season || "?"} · ${String(id.lane || "").toLowerCase()} lane${d.pseudo_out_of_sample ? " · pseudo-out-of-sample" : ""}`);
    const nums = [];
    if (typeof r.p_holm === "number") nums.push(`Holm p = ${fmtP(r.p_holm)}`);
    if (typeof r.p_one_sided === "number") nums.push(`one-sided p = ${fmtP(r.p_one_sided)}`);
    if (Array.isArray(det.ci95)) nums.push(`95% CI [${det.ci95.map((x) => x.toFixed(4)).join(", ")}]`);
    if (Number.isInteger(det.n_games)) nums.push(`${det.n_games.toLocaleString("en-US")} games`);
    if (Number.isInteger(det.n_fga)) nums.push(`${det.n_fga.toLocaleString("en-US")} shots`);
    if (nums.length) row("Result", nums.join(" · "));
    if (id.custodian?.receipt_id) row("Custodian receipt", code(id.custodian.receipt_id));
  } else {
    if (d.data_mode) row("Data", `${String(d.data_mode).toLowerCase().replaceAll("_", " ")} · ${d.n_attempts ?? "?"} shots · ${d.n_games ?? "?"} game(s)`);
    const ul = document.createElement("ul");
    for (const a of attacks) {
      const li = document.createElement("li");
      li.textContent = `${String(a.test_id_version).replace(/@\d+$/, "")}: ${a.status} — ${a.reason || ""}`;
      ul.append(li);
    }
    row(`Attacks (${attacks.length})`, attacks.length ? ul : "none run");
  }
  row("Receipt", code(entry.evidence_id));
  if (id.claim.canonical_plan_hash) row("Plan hash", code(id.claim.canonical_plan_hash));
  if (d.arrays_sha256) row("Data hash", code(d.arrays_sha256));
  row("Hashes", verified ? "verified by the server" : "not verified in the browser");
  if (id.limits) row("Limits", id.limits);
  return dl;
}

// ------------------------------------------------------------------ the exchange
async function ask(question) {
  question = question.trim();
  if (!question || state.busy) return;
  // Free text first goes to Max's router: tonight's markets, one game's card, or a what-if.
  // Anything else (and any router failure) continues to the dialogue below.
  state.busy = true;
  setBusy(true);
  const routed = await routeMessage(question);
  state.busy = false;
  setBusy(false);
  log(`route: ${routed.action}${routed.game_id ? ` ${routed.game_id}` : ""} (${routed.reason})`);
  if (routed.action === "OPEN_BOARD" || routed.action === "OPEN_CARD") return openBoardFor(routed);
  if (routed.action === "SCENARIO") return runScenario(question, routed.game_id);
  state.busy = true;
  setBusy(true);
  setView("talk");
  document.body.dataset.phase = "asking";
  const h = state.heater;
  const turn = state.turn++;
  reset();
  voice.stopSpeaking();
  log(`question: ${question}`);

  h.setState("listening");
  await sleep(450);
  h.setState("thinking");
  const [a] = await Promise.all([answer(question), sleep(TIMING.thinkingMin)]);
  state.current = a;
  log(`claim ${a.claimId}; record ${a.entry ? a.entry.evidence_id.slice(0, 8) : "none"}; line from ${a.takeSource}`);

  // 1. Heater's hot take
  document.body.dataset.phase = "take";
  ui.take.textContent = a.take;
  ui.bubble.hidden = false;
  restartAnim(ui.bubble);
  h.setState("hot_take");
  await h.speak(a.take, "heater", { voiceOn: state.voiceOn });

  // 2. the Ref checks the tape
  document.body.dataset.phase = "check";
  ui.refTitle.textContent = CLAIM_TITLES[a.claimId] || a.claimId;
  ui.refText.textContent = "Checking the tape";
  ui.ref.classList.add("checking");
  ui.ref.hidden = false;
  restartAnim(ui.ref);
  await h.play("heat_check", TIMING.heat_check);
  h.setState("thinking");

  // 3. the Ref's ruling, plain words first, numbers from the record
  const decision = a.entry ? a.entry.identity.decision : a.apiOnly ? a.apiOnly.verdict : null;
  const refLine = refLineFor(a);
  ui.ref.classList.remove("checking");
  ui.refText.textContent = refLine;
  document.body.dataset.phase = "ref";
  await h.speak(refLine, "ref", { voiceOn: state.voiceOn });

  // 4. the stamp lands as Heater changes pose
  const stamp = stampFor(decision, state.personality);
  ui.stamp.className = `stamp ${stamp.kind}`;
  ui.stamp.textContent = stamp.text;
  ui.stamp.hidden = false;
  restartAnim(ui.stamp);
  ui.ref.classList.add("slammed");
  h.setState(decision ? stateForDecision(decision) : "unsure", { restart: true });
  if (a.entry) {
    ui.evidenceBody.replaceChildren(evidenceDetails(a.entry, state.ledger.verified));
    ui.evidence.hidden = false;
  }
  document.body.dataset.phase = "verdict";

  // 5. Heater has the last word
  const react = decision ? reactFor(decision, state.personality, turn) : "";
  await sleep(700);
  if (react) {
    ui.react.textContent = react;
    ui.react.hidden = false;
    await h.speak(react, "heater", { voiceOn: state.voiceOn });
  }
  document.body.dataset.phase = "done";
  state.busy = false;
  setBusy(false);
}

function setBusy(b) {
  ui.go.disabled = b;
  ui.chips.forEach((c) => { c.disabled = b; });
  ui.boardBtn.disabled = b;
  ui.ideasBtn.disabled = b;
}

// ------------------------------------------------------------------ views: talk, market board, idea board
ui.board = $("board");
ui.boardBtn = $("btn-board");
ui.ideas = $("ideas");
ui.ideasBtn = $("btn-ideas");
const VIEWS = {
  board: { section: () => ui.board, button: () => ui.boardBtn, label: "Tonight's games" },
  ideas: { section: () => ui.ideas, button: () => ui.ideasBtn, label: "Idea board" },
};

function setView(view) {
  document.body.dataset.view = view;
  for (const [name, v] of Object.entries(VIEWS)) {
    const on = view === name;
    v.section().hidden = !on;
    v.button().setAttribute("aria-pressed", String(on));
    v.button().textContent = on ? "Back to Heater" : v.label;
  }
  if (view !== "talk") { ui.hint.hidden = true; ui.bubble.hidden = true; ui.ref.hidden = true; }
}

function toggleView(view, open) {
  if (document.body.dataset.view === view) { setView("talk"); ui.hint.hidden = Boolean(state.current); }
  else open();
}

// ------------------------------------------------------------------ idea board
async function openIdeas() {
  setView("ideas");
  if (!state.ideas) {
    ui.ideas.replaceChildren(Object.assign(document.createElement("p"), { className: "board-note", textContent: "Loading the idea board…" }));
    state.ideas = await loadIdeas();
    log(`ideas: ${state.ideas.status} ${state.ideas.families.length} families${state.ideas.reason ? ` (${state.ideas.reason})` : ""}`);
  }
  renderIdeas(ui.ideas, state.ideas, { onAsk: (r, f) => askIdea(r, f) });
}

function ideaDetails(r, f) {
  const dl = document.createElement("dl");
  const row = (k, v) => {
    const dt = document.createElement("dt"); dt.textContent = k;
    const dd = document.createElement("dd"); dd.textContent = v;
    dl.append(dt, dd);
  };
  row("Verdict", `${r.verdict} (exploratory, never SURVIVED_PROTOCOL)`);
  row("Idea", `${r.template} ${JSON.stringify(r.params)}`);
  row("Test", `permutation, B = ${r.B_effective ?? f.B}; observed ${r.T}, null mean ${r.null_mean}`);
  row("p", `raw ${r.p_raw}, Holm ${r.p_holm} (${f.multiplicity || `Holm across ${f.n_ideas}`})`);
  row("Data", f.data_scope || "");
  row("Registered", `${fmtUtc(f.registered_utc, { seconds: true })}, before any result (${f.registration_hash.slice(0, 12)}…)`);
  row("Results", `${fmtUtc(f.created_utc, { seconds: true })} (sha256 ${f.results_sha256.slice(0, 12)}…)`);
  row("Idea hash", r.idea_hash);
  row("Checked here", f.checks.join("; "));
  return dl;
}

/** Heater pitches one idea; the Ref words Research's verdict; the stamp lands. */
async function askIdea(r, f) {
  if (state.busy) return;
  state.busy = true;
  setBusy(true);
  setView("talk");
  reset();
  voice.stopSpeaking();
  const h = state.heater;
  log(`idea ${r.idea_hash.slice(0, 8)}: ${r.verdict}`);
  h.setState("listening");
  await sleep(350);
  h.setState("thinking");
  await sleep(TIMING.thinkingMin);
  document.body.dataset.phase = "take";
  const take = heaterIdeaLine(r);
  ui.take.textContent = take;
  ui.bubble.hidden = false;
  restartAnim(ui.bubble);
  h.setState("hot_take");
  await h.speak(take, "heater", { voiceOn: state.voiceOn });
  document.body.dataset.phase = "check";
  ui.refTitle.textContent = `Idea board · ${ideaTitle(r)}`;
  ui.refText.textContent = "Checking the tape";
  ui.ref.classList.add("checking");
  ui.ref.hidden = false;
  restartAnim(ui.ref);
  await h.play("heat_check", TIMING.heat_check);
  h.setState("thinking");
  const line = refIdeaText(r, f);
  ui.ref.classList.remove("checking");
  ui.refText.textContent = line;
  document.body.dataset.phase = "ref";
  await h.speak(line, "ref", { voiceOn: state.voiceOn });
  const stamp = ideaStamp(r);
  ui.stamp.className = `stamp ${stamp.kind}`;
  ui.stamp.textContent = stamp.text;
  ui.stamp.hidden = false;
  restartAnim(ui.stamp);
  ui.ref.classList.add("slammed");
  h.setState(ideaEndState(r), { restart: true });
  ui.evidenceBody.replaceChildren(ideaDetails(r, f));
  ui.evidence.hidden = false;
  document.body.dataset.phase = "done";
  state.busy = false;
  setBusy(false);
}

// ------------------------------------------------------------------ market board

async function openBoard() {
  setView("board");
  if (!state.board) {                       // investigate each game once per page view
    ui.board.replaceChildren(Object.assign(document.createElement("p"), { className: "board-note", textContent: "Loading tonight's games…" }));
    state.heater.setState("thinking");
    state.board = await loadBoard({ log });
    state.heater.setState("idle");
  }
  renderBoard(ui.board, state.board, {
    onAsk: (g) => askMarket(g),
    onScenario: (g, s, data) => askScenario(g, s, data),
    // "Your own scenario" on a card: Max's free-text what-if flow, pinned to that card's game.
    onOwnScenario: (g, text) => { if (!state.busy) runScenario(text, g.row.game_id); },
  });
}

function scenarioDetails(s, data) {
  const dl = document.createElement("dl");
  const row = (k, v) => {
    const dt = document.createElement("dt"); dt.textContent = k;
    const dd = document.createElement("dd"); dd.textContent = v;
    dl.append(dt, dd);
  };
  row("Label", data.isSample ? "SAMPLE ESTIMATE" : "ESTIMATE");
  row("Scenario", `${s.text} (${s.scenario_id})`);
  row("Forecast now", `${data.baseline.p_team_win}${data.baseline.forecast_id ? ` (${data.baseline.forecast_id})` : ""}`);
  row("In this scenario", s.p_team_win);
  row("Range", `${s.range.low} to ${s.range.high} at level ${s.range.level}`);
  row("n", `${s.n} ${s.n_unit}`);
  if (s.method) row("Method", s.method);
  s.caveats.forEach((c, i) => row(`Caveat ${i + 1}`, c));
  if (data.source) row("Source", data.source);
  row("Receipt", s.evidence_id || "not recorded");
  return dl;
}

/** Heater reacts to one scenario; the Ref words the estimate and keeps "Edge unverified". */
async function askScenario(g, s, data) {
  if (state.busy) return;
  state.busy = true;
  setBusy(true);
  setView("talk");
  reset();
  voice.stopSpeaking();
  const h = state.heater;
  log(`scenario ${g.row.game_id} ${s.scenario_id}: ${data.baseline.p_team_win} -> ${s.p_team_win}`);
  h.setState("listening");
  await sleep(350);
  h.setState("thinking");
  await sleep(TIMING.thinkingMin);
  document.body.dataset.phase = "take";
  const take = heaterScenarioLine(s, data);
  ui.take.textContent = take;
  ui.bubble.hidden = false;
  restartAnim(ui.bubble);
  h.setState("hot_take");
  await h.speak(take, "heater", { voiceOn: state.voiceOn });
  document.body.dataset.phase = "check";
  ui.refTitle.textContent = `${g.row.away_team} at ${g.row.home_team} · what if: ${s.text}`;
  ui.refText.textContent = "Checking the tape";
  ui.ref.classList.add("checking");
  ui.ref.hidden = false;
  restartAnim(ui.ref);
  await h.play("heat_check", TIMING.heat_check);
  h.setState("thinking");
  const line = refScenarioText(s, data);
  ui.ref.classList.remove("checking");
  ui.refText.textContent = line;
  document.body.dataset.phase = "ref";
  await h.speak(line, "ref", { voiceOn: state.voiceOn });
  const stamp = scenarioStamp(data, s);
  ui.stamp.className = `stamp ${stamp.kind}`;
  ui.stamp.textContent = stamp.text;
  ui.stamp.hidden = false;
  restartAnim(ui.stamp);
  ui.ref.classList.add("slammed");
  h.setState(scenarioEndState(s, data), { restart: true });
  ui.evidenceBody.replaceChildren(scenarioDetails(s, data));
  ui.evidence.hidden = false;
  document.body.dataset.phase = "done";
  state.busy = false;
  setBusy(false);
}

/** Open the board from a typed message; Heater introduces it, or the named game's card. */
async function openBoardFor(routed) {
  voice.stopSpeaking();
  await openBoard();
  const line = routed.heater_text || "";
  if (line) {
    const p = document.createElement("p");
    p.className = "board-heater";
    p.textContent = `Heater: ${line}`;
    const head = ui.board.firstElementChild;
    if (head) head.append(p); else ui.board.prepend(p);
  }
  if (routed.action === "OPEN_CARD" && routed.game_id) {
    const card = ui.board.querySelector(`[data-game-id="${CSS.escape(routed.game_id)}"]`);
    if (card) {
      card.classList.add("mcard-focus");
      card.scrollIntoView({ block: "center", behavior: "smooth" });
    }
  }
  if (line) {
    state.heater.setState("hot_take");
    await state.heater.speak(line, "heater", { voiceOn: state.voiceOn });
    state.heater.setState("idle");
  }
}

// ------------------------------------------------------------------ what-if scenarios
function whatifDetails(est) {
  const dl = document.createElement("dl");
  const row = (k, v) => {
    const dt = document.createElement("dt"); dt.textContent = k;
    const dd = document.createElement("dd"); dd.textContent = v;
    dl.append(dt, dd);
  };
  row("Label", `${whatifStamp(est).text}: a what-if, not a forecast`);
  row("Verdict", est.verdict);
  row("Computed at", fmtUtc(est.as_of_utc, { seconds: true }));
  for (const c of est.challenger_checks || []) row(c.check_id, `${c.status}: ${c.detail}`);
  row("Research effects", `${est.provider?.name || "?"} ${est.provider?.version || ""}`.trim());
  // Raw (unshrunk) numbers appear only here, in the evidence drawer; the page shows the shrunk estimate.
  for (const e of est.effects || []) {
    const raw = e.evidence?.raw?.effect_log_odds;
    if (raw && raw.raw_estimate != null) {
      row(`Raw estimate (${e.evidence.player || "player"})`,
        `log-odds ${raw.raw_estimate.toFixed(3)}, 95% ${raw.raw_ci95.map((x) => x.toFixed(3)).join(" to ")}; ` +
        `shrinkage factor ${raw.shrinkage_factor.toFixed(2)} (shown: shrunk)`);
    }
  }
  row("Receipt", est.evidence_id || "not recorded");
  return dl;
}

function finishTurn(endState) {
  if (endState) state.heater.setState(endState, { restart: true });
  document.body.dataset.phase = "done";
  state.busy = false;
  setBusy(false);
}

/** Heater reads the scenario back; nothing is estimated until the user confirms. */
async function runScenario(question, gameId) {
  state.busy = true;
  setBusy(true);
  setView("talk");
  reset();
  voice.stopSpeaking();
  const h = state.heater;
  h.setState("listening");
  await sleep(350);
  h.setState("thinking");
  let it = null;
  try {
    const r = await postJson(SCENARIO_URL, gameId ? { message: question, game_id: gameId } : { message: question });
    it = r.ok ? r.data : null;
    if (!r.ok) log(`scenario: HTTP ${r.status} ${r.data?.error || ""}`);
  } catch (e) { log(`scenario: ${e.message}`); }
  const take = it?.heater_text || "I couldn't reach the what-if service just now, so I won't guess.";
  document.body.dataset.phase = "take";
  ui.take.textContent = take;
  ui.bubble.hidden = false;
  restartAnim(ui.bubble);
  h.setState("hot_take");
  await h.speak(take, "heater", { voiceOn: state.voiceOn });
  if (it?.status !== "NEEDS_CONFIRMATION") return finishTurn("unsure");
  h.setState("listening");
  finishTurn(null);
  renderInterpretation(ui.scenario, it, {
    onConfirm: () => runEstimate(it),
    onCancel: async () => {
      ui.scenario.hidden = true;
      ui.take.textContent = "Fair enough. Say it another way and I'll read it again.";
      h.setState("idle");
    },
  });
}

/** After confirmation: the Ref runs it; baseline vs scenario side by side, marked HYPOTHETICAL. */
async function runEstimate(it) {
  if (state.busy) return;
  state.busy = true;
  setBusy(true);
  const h = state.heater;
  document.body.dataset.phase = "check";
  ui.refTitle.textContent = `${it.game} · what-if`;
  ui.refText.textContent = "Checking the tape";
  ui.ref.className = "ref checking";
  ui.ref.hidden = false;
  restartAnim(ui.ref);
  const [r] = await Promise.all([
    postJson(ESTIMATE_URL, confirmBody(it)).catch((e) => ({ ok: false, status: 0, data: { error: e.message } })),
    h.play("heat_check", TIMING.heat_check),
  ]);
  h.setState("thinking");
  ui.ref.classList.remove("checking");
  if (!r.ok) {
    const line = `Can't run this what-if: ${r.data?.error || `HTTP ${r.status}`}.`;
    ui.refText.textContent = line;
    await h.speak(line, "ref", { voiceOn: state.voiceOn });
    return finishTurn("blocked");
  }
  const est = r.data;
  log(`scenario ${est.game_id}: ${est.scenario ? est.scenario.p : "no number"}; receipt ${est.evidence_id?.slice(0, 8)}`);
  renderEstimate(ui.scenario, est);
  ui.refText.textContent = est.ref_text;
  document.body.dataset.phase = "ref";
  await h.speak(est.ref_text, "ref", { voiceOn: state.voiceOn });
  const wst = whatifStamp(est);  // the server's stamp: ESTIMATE / YOUR ASSUMPTION / SAMPLE / NO NUMBER
  ui.stamp.className = `stamp ${wst.kind}`;
  ui.stamp.textContent = wst.text;
  ui.stamp.hidden = false;
  restartAnim(ui.stamp);
  ui.ref.classList.add("slammed");
  ui.evidenceBody.replaceChildren(whatifDetails(est));
  ui.evidence.hidden = false;
  finishTurn("thinking");
}

function marketDetails(resp) {
  const dl = document.createElement("dl");
  const row = (k, v) => {
    const dt = document.createElement("dt"); dt.textContent = k;
    const dd = document.createElement("dd"); dd.textContent = v;
    dl.append(dt, dd);
  };
  row("Verdict", resp.verdict);
  row("Data", resp.data_note);
  row("Compared as of", `${fmtUtc(resp.as_of_utc, { seconds: true })} (${resp.mode})`);
  for (const c of resp.challenger_checks || []) row(c.check_id, `${c.status}: ${c.detail}`);
  if (resp.thesis?.text) row("Rest thesis", resp.thesis.text);
  row("Ref text", resp.ref_text);
  row("Receipt", resp.evidence_id || "not recorded");
  return dl;
}

/** Heater explains one card; the Ref words Max's verdict; the stamp lands. */
async function askMarket(g) {
  const resp = g.resp;
  if (!resp || state.busy) return;
  state.busy = true;
  setBusy(true);
  setView("talk");
  reset();
  voice.stopSpeaking();
  const h = state.heater;
  log(`market card ${g.row.game_id}: ${resp.verdict}`);
  h.setState("listening");
  await sleep(350);
  h.setState("thinking");
  await sleep(TIMING.thinkingMin);
  document.body.dataset.phase = "take";
  const take = heaterPlain(resp.heater_text, resp.forecast?.inputs_used);
  ui.take.textContent = take;
  ui.bubble.hidden = false;
  restartAnim(ui.bubble);
  h.setState("hot_take");
  await h.speak(take, "heater", { voiceOn: state.voiceOn });
  document.body.dataset.phase = "check";
  ui.refTitle.textContent = `${g.row.away_team} at ${g.row.home_team} · forecast vs. market`;
  ui.refText.textContent = "Checking the tape";
  ui.ref.classList.add("checking");
  ui.ref.hidden = false;
  restartAnim(ui.ref);
  await h.play("heat_check", TIMING.heat_check);
  h.setState("thinking");
  const line = marketRefPlain(resp);
  ui.ref.classList.remove("checking");
  ui.refText.textContent = line;
  document.body.dataset.phase = "ref";
  await h.speak(line, "ref", { voiceOn: state.voiceOn });
  const stamp = marketStamp(resp);
  ui.stamp.className = `stamp ${stamp.kind}`;
  ui.stamp.textContent = stamp.text;
  ui.stamp.hidden = false;
  restartAnim(ui.stamp);
  ui.ref.classList.add("slammed");
  h.setState(marketEndState(resp), { restart: true });
  ui.evidenceBody.replaceChildren(marketDetails(resp));
  ui.evidence.hidden = false;
  document.body.dataset.phase = "done";
  log(`market reasons: ${failedReasons(resp).join("; ") || "none"}`);
  state.busy = false;
  setBusy(false);
}

// ------------------------------------------------------------------ voice input
const micStatus = $("mic-status");
const voice = createVoice({
  provider: () => (window.SpeechRecognition || window.webkitSpeechRecognition ? "browser" : "server"),
  onState: (s) => {
    if (s === "LISTENING") state.heater?.setState("listening");
    else if (!state.busy && state.heater?.state === "listening") state.heater.setState("idle");
  },
  onTranscript: (text) => { micStatus.textContent = ""; ui.q.value = text; ask(text); },
  onStatus: (s) => { micStatus.textContent = /Hearing|Listening|Recording|Transcribing/.test(s) ? s.replace(/^●\s*/, "") : ""; },
  onError: (e) => { micStatus.textContent = e; },
});
// voice.js writes text labels into the button; keep a drawn mic icon instead
const micBtn = $("btn-mic");
function micIcon() {
  const NS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  const rect = document.createElementNS(NS, "rect");
  for (const [k, v] of Object.entries({ x: 9, y: 3, width: 6, height: 11, rx: 3 })) rect.setAttribute(k, v);
  const path = document.createElementNS(NS, "path");
  path.setAttribute("d", "M5 11a7 7 0 0 0 14 0M12 18v3");
  svg.append(rect, path);
  return svg;
}
const keepIcon = () => {
  if (!micBtn.querySelector("svg")) micBtn.replaceChildren(micIcon());
  micBtn.setAttribute("aria-label", micBtn.getAttribute("aria-pressed") === "true" ? "Stop listening" : "Ask with your voice");
};
keepIcon();
new MutationObserver(keepIcon).observe(micBtn, { childList: true, characterData: true, subtree: true, attributeFilter: ["aria-pressed"] });
micBtn.addEventListener("click", () => voice.toggle());

// ------------------------------------------------------------------ debug drawer
let dbg = null;
function renderDebug() {
  if (!dbg) return;
  const a = state.current;
  const id = a?.entry?.identity;
  dbg.querySelector("#dbg-state").textContent = [
    `phase: ${document.body.dataset.phase || "idle"}  pose: ${state.heater?.state}`,
    `claim: ${a ? a.claimId : "-"}`,
    `registry text: ${id?.claim?.plan?.statement || "-"}`,
    `evidence: ${a?.entry?.evidence_id || "-"}`,
    `ledger: ${state.ledger?.source || "-"}`,
    `hashes: ${state.ledger?.verified ? "verified by server" : "not verified here"}`,
    `Heater line source: ${a ? a.takeSource : state.personalitySource}`,
    `dialogue API: ${DIALOGUE_URL}`,
  ].join("\n");
  dbg.querySelector("#dbg-log").textContent = state.log.slice(-30).join("\n");
}
function buildDebug() {
  dbg = document.createElement("aside");
  dbg.className = "debug";
  dbg.innerHTML = `<h2>Debug</h2>
    <label>Evidence record <select id="dbg-rec"><option value="">(route by question)</option></select></label>
    <label><input type="checkbox" id="dbg-voice"> Voices</label>
    <pre id="dbg-state"></pre><h2>Log</h2><pre id="dbg-log"></pre>`;
  document.body.append(dbg);
  const sel = dbg.querySelector("#dbg-rec");
  state.ledger.entries.forEach((e, i) => {
    const o = document.createElement("option");
    o.value = String(i);
    o.textContent = `${e.identity.claim.claim_id} · ${e.identity.decision} · ${e.evidence_id.slice(0, 8)}`;
    sel.append(o);
  });
  sel.addEventListener("change", () => { state.forceRecord = sel.value; });
  const v = dbg.querySelector("#dbg-voice");
  v.checked = state.voiceOn;
  v.addEventListener("change", () => { state.voiceOn = v.checked; });
  renderDebug();
}

// ------------------------------------------------------------------ start
async function main() {
  state.heater = await mount($("heater"), { state: "idle", hold: true });
  const p = await loadPersonality();
  if (p) { state.personality = p; state.personalitySource = "heater_personality.json"; }
  state.ledger = await loadLedger();
  log(`ledger: ${state.ledger.entries.length} entries from ${state.ledger.source}`);
  $("ask").addEventListener("submit", (e) => { e.preventDefault(); ask(ui.q.value); });
  ui.chips.forEach((c) => c.addEventListener("click", () => { ui.q.value = c.textContent; ask(c.textContent); }));
  ui.boardBtn.addEventListener("click", () => toggleView("board", openBoard));
  ui.ideasBtn.addEventListener("click", () => toggleView("ideas", openIdeas));
  setView("talk");
  if (DEBUG) buildDebug();
  document.body.dataset.ready = "1";
  if (params.get("ask")) { ui.q.value = params.get("ask"); ask(params.get("ask")); }
  else if (params.get("board") === "1") openBoard();
  else if (params.get("ideas") === "1") openIdeas();
}

main().catch((e) => {
  ui.hint.textContent = `Could not start: ${e.message}`;
});
