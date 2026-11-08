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
  dialogueLines, refPlain, routeQuestion, splitTake, stampFor, stateForDecision, takeFor,
} from "./heater/heater-model.js";
import { ASK_MESSAGE, investigateGames, investigateOne, loadForecast, renderBoard } from "./market/board.js";
import {
  failedReasons, fmtUtc, heaterPlain, marketEndState, marketReaction, marketRefPlain, marketStamp,
} from "./market/board-model.js";
import { heaterScenarioLine, refScenarioText, scenarioEndState, scenarioStamp } from "./market/scenario-model.js";
import { loadIdeas, renderIdeas } from "./ideas/idea-board.js";
import { heaterIdeaLine, ideaEndState, ideaStamp, ideaTitle, refIdeaText } from "./ideas/idea-model.js";
import {
  ESTIMATE_URL, SCENARIO_URL, confirmBody, whatifStamp, postJson, renderEstimate, renderInterpretation, routeMessage,
} from "./whatif/whatif.js";
import { MIC, createVoice } from "./voice.js";
import { firstAskThisSession, loadResponsibleUse } from "./responsible.js";
import { mount as mountFrost } from "./frost/frost.js";
import { exchangeFromApi, exchangeSteps, frostEndState, isSkipKey, pickCastVoices, skippable } from "./frost/frost-model.js";
import {
  TAMPER_EVENTS_URL, TAMPER_FLIP_URL, TAMPER_RESTORE_URL, eventRows, flipView, mockTamperFetch, postTamper, restoreView,
  tamperMode, tamperRefLine,
} from "./tamper/tamper-model.js";
import { renderTamper, setTamperStatus } from "./tamper/tamper.js";

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
  scenario: $("scenario"), ruNotice: $("ru-notice"),
  convo: $("convo"), frostSide: $("frost-side"), skipHint: $("skip-hint"), sampleFlag: $("sample-flag"),
  tamper: $("tamper"), tamperBtn: $("btn-tamper"), restoreBtn: $("btn-restore"),
};
// The tamper button against Max's endpoints (shown by default; ?tamper=0 hides it); ?tamper=mock:
// against in-page MOCK replies.
const TAMPER = tamperMode(params);
const state = { heater: null, personality: DEFAULT_PERSONALITY, personalitySource: "built-in defaults",
  ledger: null, turn: 0, busy: false, responsible: null, ruMemo: { shown: false }, voiceOn: params.get("voice") !== "0", forceRecord: "", log: [] };

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

// ?frost=sample: the dialogue answer is the user's sample response (8 Nov), for building Frost before
// Max's API returns ``frost``. Always labelled SAMPLE on the page; never used without the parameter.
const FROST_SAMPLE = params.get("frost") === "sample" ? new URL("./frost/fixtures/sample-dialogue.json", import.meta.url) : null;

async function askDialogue(question) {
  if (FROST_SAMPLE) {
    const r = await fetch(FROST_SAMPLE);
    if (!r.ok) throw new Error(`Frost sample: HTTP ${r.status}`);
    return { ...(await r.json()), is_sample: true };
  }
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

/** The evidence ledger, once its background load (started in main) has finished. */
async function ledgerReady() {
  return state.ledger || state.ledgerLoad;
}

/** Decide the claim, Heater's lines and the evidence entry for a question.
 *  ``take`` is said before the Ref and never mentions the Ref or a verdict: Max's heater_text when it
 *  passes preemptsRef, else the personality's line for the claim. ``lastWord`` is said after the
 *  stamp: Max's heater_reaction (else a held-back take; else the page uses reactFor). */
async function answer(question) {
  try {
    await ledgerReady();
  } catch (e) {
    state.ledgerError = e.message;
    state.ledger = { entries: [], verified: false, source: `not loaded (${e.message})` };
  }
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
  // Since Max's 8 Nov fix, heater_text is the hot take only (written without the verdict, his guard
  // rejects Ref words) and heater_reaction is the line for after the stamp. The page checks the take
  // again: one that mentions the Ref or a verdict (an older server) is held back to after the stamp.
  const { take, takeFromApi, lastWord } = dialogueLines(forced ? null : api, () => takeFor(claimId, state.personality, state.turn));
  // Frost's questions and result chips come only from the server's answer; none: Heater-only flow.
  const exchange = forced ? null : exchangeFromApi(api, { take });
  return { claimId, entry, apiOnly, take, lastWord, exchange, sample: Boolean(api?.is_sample),
    takeSource: `${takeFromApi ? "dialogue API" : state.personalitySource}${lastWord ? "; reaction: dialogue API" : ""}` };
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
  if (state.ledgerError) return `Can't rule: the evidence ledger did not load (${state.ledgerError}).`;
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
  ui.ruNotice.hidden = true;
  ui.convo.replaceChildren();
  ui.convo.classList.remove("settled");
  ui.convo.hidden = true;
  ui.skipHint.hidden = true;
  ui.sampleFlag.hidden = true;
  ui.tamper.hidden = true;
  setCast(false);
}

// ------------------------------------------------------------------ Frost on stage
/** Three-column stage with Frost (he stays off stage until his first question), or Heater alone.
 *  With Frost, the Ref's voice is chosen so it never matches Frost's. */
function setCast(frost) {
  document.body.dataset.cast = frost ? "frost" : "";
  ui.frostSide.hidden = !frost;
  if (!frost) state.frost?.leave();
  if (state.heater) state.heater.voicePicker = frost ? pickCastVoices : null;
}

/** One bubble in the middle column, no name tag: the side and colour say who is talking. */
function convoBubble(who, text, extra = "") {
  const li = document.createElement("li");
  li.className = `cv cv-${who}${extra ? ` ${extra}` : ""}`;
  const p = document.createElement("p");
  p.className = "cv-text";
  p.textContent = text;
  li.append(p);
  ui.convo.append(li);
  return li;
}

/** A result chip under Frost's question, on his side. No voice. The tooltip holds the full text (chips
 *  fold to one line once the Ref is checking) and the source. Focusable, so the keyboard can open it. */
function convoChip(chip) {
  const li = document.createElement("li");
  li.className = `cv-chip ${chip.kind}`;
  li.textContent = chip.text;
  li.title = chip.source ? `${chip.text} (source: ${chip.source})` : chip.text;
  li.tabIndex = 0;
  ui.convo.append(li);
  return li;
}

/** Keep the newest line of the exchange on screen; the Ref card and its stamp are scrolled fully into
 *  view (above the fixed footer, via scroll-margin) when they land. */
function keepInView(el, block = "nearest") {
  const reduce = globalThis.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  el?.scrollIntoView?.({ block, behavior: reduce ? "auto" : "smooth" });
}

/** Space: draw everything up to the stamp at once and stop the voice that is talking. */
function skipToStamp() {
  if (!state.exchangeRunning || state.skip) return;
  state.skip = true;
  globalThis.speechSynthesis?.cancel();
  state.skipNow?.();
  log("skip: Space, straight to the stamp");
}

/** Await a step unless Space was pressed (then at once). */
const untilSkip = (p) => (state.skip ? Promise.resolve() : Promise.race([p, state.skipSignal]));
/** Pause while a result chip shows (adviser: about 1.2 s, no voice). */
const CHIP_PAUSE_MS = 1200;

/** Heater's take, Frost's questions with their result chips, the Ref, the stamp, then Frost's and
 *  Heater's reactions. Used by the dialogue and by market cards. Nothing here decides: the questions,
 *  chips and verdict are the server's and the record's; ``show`` says what the Ref shows:
 *  {title, refLine(), stamp: {text, kind}, heaterEnd, frostEnd, evidence() -> Node|null, sample}. */
async function runExchange(ex, show) {
  const h = state.heater;
  const opts = { voiceOn: state.voiceOn };
  const steps = exchangeSteps(ex);
  setCast(true);
  const f = state.frost || (state.frost = mountFrost($("frost")));
  f.leave();
  f.setState("idle");
  ui.convo.hidden = false;
  ui.sampleFlag.hidden = !show.sample;
  state.skip = false;
  state.skipSignal = new Promise((res) => { state.skipNow = res; });
  state.exchangeRunning = true;
  ui.skipHint.hidden = false;
  log(`frost: ${ex.challenges.length} question(s)`);
  try {
    for (const st of steps) {
      const fast = state.skip && skippable(st);
      if (st.kind === "take") {
        document.body.dataset.phase = "take";
        keepInView(convoBubble("heater", st.text));
        h.setState("hot_take");
        if (!fast) await untilSkip(h.speak(st.text, "heater", opts));
      } else if (st.kind === "question") {
        document.body.dataset.phase = "challenge";
        if (st.first) { f.enter(); if (!fast) await untilSkip(sleep(450)); }
        f.setState("challenging");
        h.setState("listening");
        keepInView(convoBubble("frost", st.text));
        if (!fast) await untilSkip(f.speak(st.text, opts));
      } else if (st.kind === "chip") {
        f.setState("evidence");
        keepInView(convoChip(st.chip));
        if (!fast) await untilSkip(sleep(CHIP_PAUSE_MS));
      } else if (st.kind === "ruling") {
        f.setState("unconvinced");
        document.body.dataset.phase = "check";
        ui.convo.classList.add("settled");          // earlier chips fold to one line
        ui.refTitle.textContent = show.title;
        ui.refText.textContent = "Checking the tape";
        ui.ref.classList.add("checking");
        ui.ref.hidden = false;
        restartAnim(ui.ref);
        keepInView(ui.ref, "end");
        if (!fast) await untilSkip(h.play("heat_check", TIMING.heat_check));
        h.setState("thinking");
        const refLine = show.refLine();
        ui.ref.classList.remove("checking");
        ui.refText.textContent = refLine;
        document.body.dataset.phase = "ref";
        keepInView(ui.ref, "end");
        if (!fast) await untilSkip(h.speak(refLine, "ref", opts));
      } else if (st.kind === "stamp") {
        state.exchangeRunning = false;
        ui.skipHint.hidden = true;
        ui.stamp.className = `stamp ${show.stamp.kind}`;
        ui.stamp.textContent = show.stamp.text;
        ui.stamp.hidden = false;
        restartAnim(ui.stamp);
        ui.ref.classList.add("slammed");
        h.setState(show.heaterEnd, { restart: true });
        f.setState(show.frostEnd);
        const ev = show.evidence?.();
        if (ev) {
          ui.evidenceBody.replaceChildren(ev);
          ui.evidence.hidden = false;
        }
        document.body.dataset.phase = "verdict";
        keepInView(ui.ref, "end");
        await sleep(700);
      } else if (st.kind === "reaction") {
        convoBubble(st.who, st.text, "cv-reaction");
        keepInView(ui.ref, "end");                  // the reaction lands above the card; the card stays in view
        if (st.who === "frost") await f.speak(st.text, opts);
        else await h.speak(st.text, "heater", opts);
      }
    }
    f.setState("idle");
    h.setState("idle");
  } finally {
    state.exchangeRunning = false;
    state.skip = false;
    ui.skipHint.hidden = true;
  }
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

  // With Frost's questions in the answer: Heater, Frost, the Ref in the middle column.
  if (a.exchange) {
    const decision = a.entry ? a.entry.identity.decision : a.apiOnly ? a.apiOnly.verdict : null;
    const heaterReaction = a.exchange.heaterReaction || a.lastWord || (decision ? reactFor(decision, state.personality, turn) : "");
    await runExchange({ ...a.exchange, heaterReaction }, {
      title: CLAIM_TITLES[a.claimId] || a.claimId,
      refLine: () => refLineFor(a),
      stamp: stampFor(decision, state.personality),
      heaterEnd: decision ? stateForDecision(decision) : "unsure",
      frostEnd: frostEndState(decision),
      evidence: () => (a.entry ? evidenceDetails(a.entry, state.ledger.verified) : null),
      sample: a.sample,
    });
    document.body.dataset.phase = "done";
    state.busy = false;
    setBusy(false);
    return;
  }

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

  // 5. Heater has the last word, only now that the stamp is down: Max's verdict-aware line, else
  // the personality's reaction to the ruling.
  const react = a.lastWord || (decision ? reactFor(decision, state.personality, turn) : "");
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
  ui.tamperBtn.disabled = b || Boolean(state.tampered);
  ui.restoreBtn.disabled = b;
}

// ------------------------------------------------------------------ tamper test
/** "Corrupt one byte": Max's server flips one byte of a sealed file; the panel shows what the
 *  validator caught, the Ref rules DATA_INVALID and the new ledger row appears. The values are the
 *  server's (or, with ?tamper=mock, labelled MOCK); nothing here decides. */
const mockFetch = TAMPER === "mock" ? mockTamperFetch() : null;
const tamperFetch = () => mockFetch || globalThis.fetch.bind(globalThis);

async function runTamper() {
  if (state.busy || state.tampered) return;
  state.busy = true;
  setBusy(true);
  setView("talk");
  reset();
  voice.stopSpeaking();
  const h = state.heater;
  document.body.dataset.phase = "check";
  ui.tamper.hidden = false;
  renderTamper(ui.tamper, null, { status: "Flipping one byte…" });
  ui.refTitle.textContent = "Tamper test";
  ui.refText.textContent = "Checking the seal";
  ui.ref.classList.add("checking");
  ui.ref.hidden = false;
  restartAnim(ui.ref);
  const [res] = await Promise.all([postTamper(TAMPER_FLIP_URL, tamperFetch()), h.play("heat_check", TIMING.heat_check)]);
  const view = flipView(res.body, { httpStatus: res.status, mock: TAMPER === "mock" || res.body?.mock === true });
  log(`tamper flip: HTTP ${res.status}; ${view.ok ? `verdict ${view.verdict || "none"}; row ${view.row ? view.row.id : "none"}` : view.problem}`);
  if (view.ok) { state.tampered = true; ui.restoreBtn.hidden = false; }
  // the new row: the TAMPER_ATTEMPT event Max's server appended (GET /api/tamper/events)
  let rows = { recent: [], row: null, found: false };
  let rowNote = "";
  if (view.ok) {
    const ev = await postTamper(TAMPER_EVENTS_URL, tamperFetch(), "GET");
    if (ev.status === 200) {
      rows = eventRows(ev.body, view.eventId);
      if (!rows.found) rowNote = `The tamper ledger does not list the new entry${view.eventId ? ` (${view.eventId.slice(0, 12)})` : ""}.`;
    } else {
      rowNote = `The tamper ledger did not load (HTTP ${ev.status}${ev.body?.error ? `: ${ev.body.error}` : ""}).`;
    }
    log(`tamper events: HTTP ${ev.status}; new row ${rows.found ? "found" : "not found"}`);
  }
  renderTamper(ui.tamper, view, { recent: rows.recent, row: rows.row, rowNote,
    status: view.ok ? "One byte is corrupted in a scratch copy. Press Restore the byte to delete it." : "" });
  const refLine = tamperRefLine(view, state.personality);
  ui.ref.classList.remove("checking");
  ui.refText.textContent = refLine;
  document.body.dataset.phase = "ref";
  h.setState("thinking");
  await h.speak(refLine, "ref", { voiceOn: state.voiceOn });
  if (view.ok && view.caught) {
    const stamp = stampFor("DATA_INVALID", state.personality);
    ui.stamp.className = `stamp ${stamp.kind}`;
    ui.stamp.textContent = stamp.text;
    ui.stamp.hidden = false;
    restartAnim(ui.stamp);
    ui.ref.classList.add("slammed");
    h.setState(stateForDecision("DATA_INVALID"), { restart: true });
    document.body.dataset.phase = "verdict";
    await sleep(700);
    const react = reactFor("DATA_INVALID", state.personality, state.turn++);
    if (react) { ui.react.textContent = react; ui.react.hidden = false; ui.bubble.hidden = true; await h.speak(react, "heater", { voiceOn: state.voiceOn }); }
  } else if (view.notDetected) {
    ui.stamp.className = "stamp blocked";
    ui.stamp.textContent = "CHECK FAILED";
    ui.stamp.hidden = false;
    restartAnim(ui.stamp);
    h.setState("unsure", { restart: true });
  } else {
    h.setState("unsure", { restart: true });
  }
  document.body.dataset.phase = "done";
  state.busy = false;
  setBusy(false);
}

async function runRestore() {
  if (state.busy || !state.tampered) return;
  state.busy = true;
  setBusy(true);
  const res = await postTamper(TAMPER_RESTORE_URL, tamperFetch());
  const view = restoreView(res.body, { httpStatus: res.status });
  log(`tamper restore: HTTP ${res.status}; ${view.ok ? "restored" : "failed"}`);
  ui.tamper.hidden = false;
  setTamperStatus(ui.tamper, view.text, view.ok);
  if (view.ok) {
    // the committed ledger was only read, so nothing on the page needs reloading
    state.tampered = false;
    ui.restoreBtn.hidden = true;
  }
  state.busy = false;
  setBusy(false);
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
  if (view !== "talk") { ui.hint.hidden = true; ui.bubble.hidden = true; ui.ref.hidden = true; ui.convo.hidden = true; ui.sampleFlag.hidden = true; ui.tamper.hidden = true; setCast(false); }
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

// Lazy: nothing is fetched for the board until "Tonight's games" is opened. Opening it waits at most
// BOARD_TIMEOUT_MS for the forecast (then every card is drawn, pending) or says why it failed with a
// "Try again" button; the comparisons then fill the cards in one by one in the background.
const boardHandlers = () => ({
  onAsk: (g) => askMarket(g),
  onScenario: (g, s, data) => askScenario(g, s, data),
  // "Your own scenario" on a card: Max's free-text what-if flow, pinned to that card's game.
  onOwnScenario: (g, text) => { if (!state.busy) runScenario(text, g.row.game_id); },
  responsibleText: state.responsible?.full || "",
});

async function openBoard() {
  setView("board");
  if (state.board) {                        // investigate each game once per page view
    state.boardView = renderBoard(ui.board, state.board, boardHandlers());
    return;
  }
  if (!state.boardLoading) state.boardLoading = loadBoardView().finally(() => { state.boardLoading = null; });
  await state.boardLoading;
}

async function loadBoardView() {
  ui.board.replaceChildren(Object.assign(document.createElement("p"), { className: "board-note", textContent: "Loading tonight's games…" }));
  if (!state.busy) state.heater?.setState("thinking");
  const board = await loadForecast();
  if (!state.busy) state.heater?.setState("idle");
  log(`board: ${board.status}${board.reason ? ` (${board.reason})` : ""}, ${board.games.length} games`);
  if (board.status !== "OK") {              // not kept: opening the board again retries
    renderBoard(ui.board, board, { onRetry: () => openBoard() });
    return;
  }
  state.board = board;
  state.boardView = renderBoard(ui.board, board, boardHandlers());
  investigateGames(board, { log, onCard: (g) => state.boardView?.update(g) });  // not awaited
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

/** After confirmation: the Ref runs it; baseline vs scenario side by side, marked with the server's stamp. */
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

const MARKET_OPENER = "Let's put this card under the lights.";

/** Heater explains one card; the Ref words Max's verdict; the stamp lands.
 *  The card's board answer was made without the model (empty message). Asking sends the card again
 *  with ASK_MESSAGE, so Max's server has the model voice it, and the card is redrawn from that answer
 *  so the card and the Ref say the same thing. If that call fails, the board's answer is used. */
async function askMarket(g) {
  if (!g.resp || state.busy) return;
  state.busy = true;
  setBusy(true);
  setView("talk");
  reset();
  voice.stopSpeaking();
  const h = state.heater;
  // Responsible use: the full notice once per session, the first time a market card is asked about.
  if (state.responsible && firstAskThisSession(globalThis.sessionStorage, state.ruMemo)) {
    ui.ruNotice.textContent = state.responsible.full;
    ui.ruNotice.hidden = false;
    log("responsible-use notice shown (first market Ask this session)");
  }
  h.setState("listening");
  await sleep(350);
  h.setState("thinking");
  const [asked] = await Promise.all([investigateOne(g, ASK_MESSAGE), sleep(TIMING.thinkingMin)]);
  if (asked.resp) {
    g.resp = asked.resp;
    state.boardView?.update(g);
  }
  const resp = g.resp;
  log(`market card ${g.row.game_id}: ${resp.verdict}; Heater line ${asked.resp ? resp.heater_source || "?" : `from the board load (${asked.error})`}`);
  document.body.dataset.phase = "take";
  // Max's take is written before the verdict (his guard rejects Ref words); the page checks again and
  // holds back any sentence that mentions the Ref or a verdict until after the stamp.
  const split = splitTake(heaterPlain(resp.heater_text, resp.forecast?.inputs_used));
  const take = split.first || MARKET_OPENER;
  // With Frost's challenges in the card's answer (Max's /api/investigate): the same sequence as a
  // question, Heater left, Frost right, the Ref and the card's stamp in the middle column.
  const exchange = exchangeFromApi(resp, { take });
  if (exchange) {
    await runExchange({ ...exchange, heaterReaction: marketReaction(split, resp) }, {
      title: `${g.row.away_team} at ${g.row.home_team} · forecast vs. market`,
      refLine: () => marketRefPlain(resp),
      stamp: marketStamp(resp),
      heaterEnd: marketEndState(resp),
      frostEnd: frostEndState(resp.verdict),
      evidence: () => marketDetails(resp),
      sample: false,
    });
    document.body.dataset.phase = "done";
    log(`market reasons: ${failedReasons(resp).join("; ") || "none"}`);
    state.busy = false;
    setBusy(false);
    return;
  }
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
  document.body.dataset.phase = "verdict";
  const reaction = marketReaction(split, resp);
  if (reaction) {                          // Heater's reaction, only now that the stamp is down
    await sleep(700);
    ui.react.textContent = reaction;
    ui.react.hidden = false;
    await h.speak(reaction, "heater", { voiceOn: state.voiceOn });
  }
  document.body.dataset.phase = "done";
  log(`market reasons: ${failedReasons(resp).join("; ") || "none"}`);
  state.busy = false;
  setBusy(false);
}

// ------------------------------------------------------------------ voice input
const micStatus = $("mic-status");
const voice = createVoice({
  // Default: record and transcribe on our server (every browser); browser speech is a fallback only.
  onState: (s) => {
    if (s === "LISTENING") state.heater?.setState("listening");
    else if (!state.busy && state.heater?.state === "listening") state.heater.setState("idle");
  },
  // The transcript goes in the question box for the user to confirm or edit; nothing is asked yet.
  onTranscript: (text) => { ui.q.value = text; ui.q.focus(); micStatus.textContent = MIC.HEARD; },
  onStatus: (s) => { micStatus.textContent = s; },
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
if (voice.support.ok) {
  // Tap to start and tap to stop, or hold and release (held > 0.5 s). Recording stops at 30 s.
  let downAt = 0, startedHere = false;
  micBtn.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    downAt = performance.now();
    startedHere = !voice.isListening();
    if (startedHere) voice.start();                  // fallback speech: start() runs inside the gesture
  });
  micBtn.addEventListener("pointerup", () => {
    if (!downAt) return;
    const held = performance.now() - downAt;
    downAt = 0;
    if (!startedHere || held > 500) voice.stop();
  });
  micBtn.addEventListener("click", (e) => { if (e.detail === 0) voice.toggle(); });  // keyboard
} else {
  micBtn.hidden = true;
  micStatus.textContent = MIC.UNSUPPORTED;
}

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
  // The home view first: no network wait before it is drawn, and the board is fetched only when
  // opened. The evidence ledger loads in the background; a question waits for it (ledgerReady).
  setView("talk");
  ui.boardBtn.addEventListener("click", () => toggleView("board", openBoard));
  ui.ideasBtn.addEventListener("click", () => toggleView("ideas", openIdeas));
  // The tamper button: shown (Max's endpoints) unless ?tamper=0; ?tamper=mock for MOCK replies.
  ui.tamperBtn.hidden = TAMPER === "off";
  if (TAMPER === "mock") ui.tamperBtn.textContent = "Corrupt one byte (MOCK)";
  ui.tamperBtn.addEventListener("click", () => runTamper());
  ui.restoreBtn.addEventListener("click", () => runRestore());
  state.ledgerLoad = loadLedger().then((l) => {
    state.ledger = l;
    log(`ledger: ${l.entries.length} entries from ${l.source}`);
    return l;
  });
  state.ledgerLoad.catch(() => { /* reported by the first question that needs it */ });
  state.heater = await mount($("heater"), { state: "idle", hold: true });
  state.responsible = await loadResponsibleUse();
  if (!state.responsible) log("responsible_use.json not loaded: footer only");
  const p = await loadPersonality();
  if (p) { state.personality = p; state.personalitySource = "heater_personality.json"; }
  $("ask").addEventListener("submit", (e) => { e.preventDefault(); ask(ui.q.value); });
  // Space skips Heater and Frost's back-and-forth straight to the stamp (only while it runs).
  document.addEventListener("keydown", (e) => {
    if (!isSkipKey(e, { running: state.exchangeRunning })) return;
    e.preventDefault();
    skipToStamp();
  });
  ui.chips.forEach((c) => c.addEventListener("click", () => { ui.q.value = c.textContent; ask(c.textContent); }));
  if (DEBUG) ledgerReady().then(buildDebug, () => {});
  document.body.dataset.ready = "1";
  if (params.get("ask")) { ui.q.value = params.get("ask"); ask(params.get("ask")); }
  else if (params.get("board") === "1") openBoard();
  else if (params.get("ideas") === "1") openIdeas();
}

main().catch((e) => {
  ui.hint.textContent = `Could not start: ${e.message}`;
});
