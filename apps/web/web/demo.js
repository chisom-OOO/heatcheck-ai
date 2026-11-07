// HeatCheck demo page: ask a question, Heater gives a hot take, the Ref checks it against a
// real evidence record, and the verdict stamp lands as Heater changes pose.
//
// Answer source, in order:
//   1. Max's dialogue API (POST http://127.0.0.1:8770/api/dialogue) for Heater's line, the
//      claim and the evidence id;
//   2. offline: question -> claim by keywords, Heater's line from heater_personality.json.
// The Ref's words and every number always come from the evidence record (GET /api/evidence,
// or the byte-copy fixture of Max's ledger). ?debug=1 opens a drawer with the internals.

import { loadPersonality, mount } from "./heater/heater.js";
import {
  CLAIM_TITLES, DEFAULT_PERSONALITY, TIMING, fmtP, latestFor, parseJsonl, reactFor, refPlain,
  routeQuestion, stampFor, stateForDecision, takeFor,
} from "./heater/heater-model.js";
import { createVoice } from "./voice.js";

const params = new URLSearchParams(location.search);
const DEBUG = params.get("debug") === "1";
const DIALOGUE_URL = params.get("dialogue") || "http://127.0.0.1:8770/api/dialogue";
const FIXTURE = new URL("./heater/fixtures/evidence_real_game.jsonl", import.meta.url);
const $ = (id) => document.getElementById(id);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const ui = {
  bubble: $("bubble"), take: $("take"), react: $("react"), ref: $("ref"), refTitle: $("ref-title"),
  refText: $("ref-text"), stamp: $("stamp"), evidence: $("evidence"), evidenceBody: $("evidence-body"),
  hint: $("hint"), q: $("q"), go: $("go"), chips: [...document.querySelectorAll(".chip")],
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
  const t = setTimeout(() => ctl.abort(), 9000);
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
  const take = (!forced && api?.heater_text) || takeFor(claimId, state.personality, state.turn);
  return { claimId, entry, take, takeSource: !forced && api?.heater_text ? "dialogue API" : state.personalitySource };
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
  row("Claim", id.claim.plan?.statement || id.claim.claim_id);
  row("Verdict", `${id.decision}: ${id.reason || ""}`);
  const perm = id.attack_results.find((a) => String(a.test_id_version).startsWith("A-PERMUTATION-NULL@"));
  if (perm && typeof perm.effect_estimate === "number") {
    row("Effect", `${perm.effect_estimate >= 0 ? "+" : ""}${perm.effect_estimate.toFixed(4)} (bias-corrected; p = ${fmtP(perm.p_value)}, ${perm.details?.B_effective ?? "?"} permutations)`);
  }
  const d = id.data || {};
  if (d.data_mode) row("Data", `${String(d.data_mode).toLowerCase().replaceAll("_", " ")} · ${d.n_attempts ?? "?"} shots · ${d.n_games ?? "?"} game(s)`);
  const ul = document.createElement("ul");
  for (const a of id.attack_results) {
    const li = document.createElement("li");
    li.textContent = `${String(a.test_id_version).replace(/@\d+$/, "")}: ${a.status} — ${a.reason || ""}`;
    ul.append(li);
  }
  row(`Attacks (${id.attack_results.length})`, id.attack_results.length ? ul : "none run");
  const code = (s) => { const c = document.createElement("code"); c.textContent = s; return c; };
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
  state.busy = true;
  setBusy(true);
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
  const decision = a.entry ? a.entry.identity.decision : null;
  const refLine = a.entry
    ? refPlain(a.entry, state.personality).text
    : "No ruling yet. We haven't run a test for this one, so there's nothing to report.";
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
  if (DEBUG) buildDebug();
  document.body.dataset.ready = "1";
  if (params.get("ask")) { ui.q.value = params.get("ask"); ask(params.get("ask")); }
}

main().catch((e) => {
  ui.hint.textContent = `Could not start: ${e.message}`;
});
