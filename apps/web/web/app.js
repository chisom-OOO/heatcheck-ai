// HeatCheck-Experience client. Formats engine JSON; never computes probabilities, statistics or quote units.
// Untrusted text is always inserted with textContent (no innerHTML anywhere in this file).
import * as referee from "./referee.js";
import { createVoice } from "./voice.js";

const $ = (id) => document.getElementById(id);
const S = {
  session: null, revision: 0, interpSeq: 0, interp: null, plan: null, confirmation: null,
  currentRun: null, pollTimer: null, runViews: {}, uiState: "IDLE", market: null, latency: [],
};

// ------------------------------------------------------------------ helpers
function el(tag, attrs = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") n.className = v;
    else if (k === "text") n.textContent = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v === true ? "" : v);
  }
  for (const k of kids.flat()) if (k !== null && k !== undefined && k !== false) n.append(k instanceof Node ? k : document.createTextNode(String(k)));
  return n;
}
const svgNS = "http://www.w3.org/2000/svg";
function sv(tag, attrs = {}) { const n = document.createElementNS(svgNS, tag); for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v); return n; }
const fmt = (x, d = 3) => (x === null || x === undefined ? "—" : typeof x === "number" ? x.toFixed(d) : String(x));
const pct = (x, d = 1) => (x === null || x === undefined ? "—" : (100 * x).toFixed(d) + "%");
const reqId = () => "req-" + crypto.getRandomValues(new Uint32Array(3)).join("").slice(0, 20);
function announce(msg) { $("announce").textContent = ""; setTimeout(() => ($("announce").textContent = msg), 30); }
function setState(st) { S.uiState = st; const c = $("voice-state"); c.textContent = st; c.dataset.state = st; }

async function api(method, path, body, opts = {}) {
  const init = { method, headers: {} };
  if (body instanceof Blob || body instanceof ArrayBuffer) { init.body = body; Object.assign(init.headers, opts.headers || {}); }
  else if (body !== undefined) { init.body = JSON.stringify(body); init.headers["Content-Type"] = "application/json"; }
  const r = await fetch("/api/" + path, init);
  const ct = r.headers.get("Content-Type") || "";
  const data = ct.includes("json") ? await r.json() : await r.text();
  if (!r.ok) { const e = new Error((data && data.message) || r.statusText); e.code = data && data.error; e.status = r.status; e.data = data; throw e; }
  return data;
}
function modeBadge(m) { return el("span", { class: "mode " + m, title: "data mode carried by this artifact", text: m }); }
function decisionMeta(d) {
  return {
    SURVIVED_PROTOCOL: ["✓", "Survived every registered check"],
    NOT_SUPPORTED: ["✕", "Not supported by the planned checks"],
    INSUFFICIENT_EVIDENCE: ["?", "Not enough evidence to tell"],
    BLOCKED: ["■", "Blocked: could not run"],
    DATA_INVALID: ["!", "Data invalid"],
  }[d] || ["•", d];
}

// ------------------------------------------------------------------ tabs (keyboard: arrows)
const tabs = [...document.querySelectorAll('[role="tab"]')];
function selectTab(t) {
  for (const x of tabs) { const on = x === t; x.setAttribute("aria-selected", on); x.tabIndex = on ? 0 : -1; $(x.getAttribute("aria-controls")).hidden = !on; }
  t.focus();
  if (t.id === "tab-gates") loadGates();
  if (t.id === "tab-harness") loadHarness();
}
tabs.forEach((t, i) => {
  t.addEventListener("click", () => selectTab(t));
  t.addEventListener("keydown", (e) => {
    if (e.key === "ArrowRight") selectTab(tabs[(i + 1) % tabs.length]);
    if (e.key === "ArrowLeft") selectTab(tabs[(i - 1 + tabs.length) % tabs.length]);
  });
});

// ------------------------------------------------------------------ session + revision authority
function applySession(view) {
  const prevRev = S.revision;
  S.revision = view.revision;
  S.plan = view.plan; S.confirmation = view.confirmation; S.currentRun = view.current_run;
  if (view.revision !== prevRev && prevRev > 0 && view.log.some((l) => l.kind === "edit" && l.confirmation_revoked && l.revision === view.revision)) {
    $("revoked-banner").hidden = false; announce("Plan confirmation revoked because the claim or sources changed.");
  }
  renderSources(view.sources);
  renderPlan();
  renderHistory(view.runs);
}
async function refreshSession() { applySession(await api("GET", "session/" + S.session)); }
// sources attached from the extension arrive server-side; pick them up while the page is visible
setInterval(() => { if (S.session && !document.hidden && S.uiState !== "RUNNING") refreshSession().catch(() => {}); }, 4000);

// ------------------------------------------------------------------ 1-2 interpret / approve
async function interpret(text, origin = "typed") {
  const seq = ++S.interpSeq;              // late interpretations never overwrite newer ones
  const revAtSend = S.revision;
  if (origin === "voice") setState("TRANSCRIBING");
  let res;
  try { res = await api("POST", "interpret", { text }); }
  catch (e) { setState("ERROR"); announce("Interpretation failed: " + e.message); return; }
  if (seq !== S.interpSeq || revAtSend !== S.revision) return;   // stale: ignored
  if (res.status === "COMMAND") { setState("IDLE"); return runCommand(res.command, origin); }
  S.interp = res;
  renderInterp(res);
  setState(res.status === "REVIEWABLE" ? "REVIEWABLE" : res.status === "NEEDS_CLARIFICATION" ? "NEEDS_CLARIFICATION" : "ERROR");
  const spoken = res.status === "UNSUPPORTED" ? "I can't test that kind of claim yet. " + res.unresolved[0]
    : res.status === "NEEDS_CLARIFICATION" ? `That pattern looks interesting; I'll test whether it survives. First I need ${res.unresolved.length} definition${res.unresolved.length > 1 ? "s" : ""} from you.`
    : "Here is the exact definition. Approve it to continue.";
  say(spoken);
}

const FIELD_SPECS = {
  hot_hand: [
    ["population", "Population", "text", null, (f) => f.population && f.population.label],
    ["streak_length", "Streak length (consecutive makes)", "select", ["", "2", "3", "4"]],
    ["setting", "Setting", "select", ["", "free throws only", "field goals", "both"]],
    ["comparator", "Comparator", "select", ["", "within-player permutation null", "shrunk talent baseline", "shot-difficulty-adjusted expectation"]],
    ["direction", "Direction", "select", ["", "positive", "negative", "two_sided"]],
  ],
  clutch: [
    ["population", "Population", "text", null, (f) => f.population && f.population.label],
    ["window_minutes", "Time window (minutes)", "select", ["", "2", "5"]],
    ["margin_points", "Score margin (points)", "select", ["", "3", "5"]],
    ["comparator", "Comparator", "select", ["", "same player non-clutch", "league baseline"]],
    ["statistic", "Statistic", "select", ["", "FG%", "eFG%", "TS%"]],
    ["direction", "Direction", "select", ["", "positive", "negative", "two_sided"]],
  ],
};
for (const k of ["home_court", "rest", "game_win"]) FIELD_SPECS[k] = [
  ["population", "Teams", "text", null, (f) => f.population && f.population.label],
  ["target", "Target", "select", ["", "team-win probability at a declared UTC cutoff"]],
  ...(k === "game_win" ? [["game", "Scheduled game (teams, tip date)", "text"]] : [["seasons", "Seasons", "text"]]),
  ["direction", "Direction", "select", ["", "positive", "negative", "two_sided"]],
];

function renderInterp(res) {
  $("interp-card").hidden = false;
  const p = $("interp-spans"); p.replaceChildren();
  const text = res.source_text || "";
  const spans = Object.entries(res.source_spans || {}).sort((a, b) => a[1][0] - b[1][0]);
  let i = 0;
  for (const [name, [a, b]] of spans) {
    if (a < i) continue;
    p.append(text.slice(i, a), el("mark", {}, text.slice(a, b), el("small", { text: name })));
    i = b;
  }
  p.append(text.slice(i));
  const form = $("fields-form"); form.replaceChildren();
  const ul = $("unresolved"); ul.replaceChildren(...(res.unresolved || []).map((u) => el("li", { text: u })));
  const kind = res.fields && res.fields.kind;
  if (!kind || !FIELD_SPECS[kind]) { $("btn-approve").disabled = true; return; }
  $("btn-approve").disabled = false;
  form.append(el("div", {}, el("label", { text: "Claim type" }), el("p", { class: "mono", text: `${kind} · ${res.fields.channel}` })));
  for (const [key, label, type, opts, getter] of FIELD_SPECS[kind]) {
    const val = getter ? getter(res.fields) : res.fields[key];
    const id = "f-" + key;
    const input = type === "select"
      ? el("select", { id, name: key }, ...opts.map((o) => el("option", { value: o, text: o || "— choose —" })))
      : el("input", { id, name: key, type: "text" });
    if (val !== undefined && val !== null) input.value = String(val);
    form.append(el("div", { class: val === undefined || val === null || val === "" ? "open" : "" }, el("label", { for: id, text: label }), input));
  }
}

async function approve() {
  const r = S.interp; if (!r) return;
  const fd = new FormData($("fields-form"));
  const f = { kind: r.fields.kind, channel: r.fields.channel, statement: r.source_text };
  for (const [k, v] of fd.entries()) {
    if (v === "") continue;
    f[k] = k === "population" ? { type: (r.fields.population || {}).type || "user_defined", label: v }
      : ["streak_length", "window_minutes", "margin_points"].includes(k) ? Number(v) : v;
  }
  try {
    const out = await api("POST", "claim", { session_id: S.session, fields: f });
    applySession(out.session);
    $("approve-msg").textContent = `Approved as revision ${out.session.revision}.`;
    S.plan = null; renderPlan();
    announce("Definition approved. Propose the plan next.");
  } catch (e) {
    $("approve-msg").textContent = e.message;
    setState("NEEDS_CLARIFICATION");
    say("I still need: " + ((e.data && e.data.missing) || []).join(", ").replaceAll("_", " "));
  }
}

// ------------------------------------------------------------------ 3 sources
function renderSources(list) {
  const ul = $("sources"); ul.replaceChildren();
  for (const s of list) {
    const head = el("div", {}, el("strong", { text: s.kind === "file" ? s.file_name : s.kind === "page" ? (s.title || s.url) : s.surface_label }),
      " ", el("span", { class: "chip", text: s.kind }), " ", el("span", { class: "chip", text: s.trust }));
    const kv = el("dl", { class: "kv" },
      el("dt", { text: "sha256" }), el("dd", { class: "mono", text: s.sha256 }),
      el("dt", { text: s.kind === "screen_frame" ? "captured" : "retrieved" }), el("dd", { text: s.retrieved_utc || s.captured_utc }),
      s.bytes !== undefined ? [el("dt", { text: "bytes" }), el("dd", { text: String(s.bytes) })] : null,
      s.url ? [el("dt", { text: "url" }), el("dd", { text: s.url })] : null);
    const li = el("li", {}, head, kv);
    if (s.preview && s.preview.kind === "csv") {
      const pv = s.preview;
      li.append(el("p", { class: "hint", text: `${pv.rows_total} rows · ${pv.columns.length} columns · ${pv.ragged_rows} ragged · ${pv.formula_like_cells} formula-like cells (neutralised on export)` }));
      const t = el("table", {}, el("thead", {}, el("tr", {}, ...pv.columns.map((c) => el("th", { text: c })))),
        el("tbody", {}, ...pv.sample.slice(0, 5).map((r) => el("tr", {}, ...r.map((c) => el("td", { text: c }))))));
      li.append(el("div", { class: "tablewrap" }, t));
      const miss = Object.entries(pv.missingness || {}).filter(([, n]) => n > 0);
      if (miss.length) li.append(el("p", { class: "hint", text: "Missing values: " + miss.map(([k, n]) => `${k} ${n}`).join(", ") }));
      li.append(el("p", { class: "hint", text: "Suggested column mapping (not applied until a Research test consumes this file): " + JSON.stringify(pv.suggested_mapping) }));
    } else if (s.preview && s.preview.kind === "json") li.append(el("pre", { text: JSON.stringify(s.preview).slice(0, 600) }));
    else if (s.preview && s.preview.kind === "text") li.append(el("pre", { text: s.preview.lines.join("\n").slice(0, 600) }));
    if (s.kind === "page") li.append(el("pre", { text: s.selected_text.slice(0, 600) }));
    if (s.note) li.append(el("p", { class: "hint", text: s.note }));
    ul.append(li);
  }
}

async function attachFile(file) {
  if (!S.session) return;
  const buf = await file.arrayBuffer();
  try {
    const out = await api("POST", "file?session_id=" + S.session, buf, { headers: { "X-File-Name": file.name, "Content-Type": file.type || "application/octet-stream" } });
    applySession(out.session); announce(`Attached ${out.source.file_name}.`);
  } catch (e) { announce("File rejected: " + e.message); alertBox($("sources"), "File rejected: " + e.message); }
  $("file-input").value = "";
}
function alertBox(after, msg) {
  const b = el("div", { class: "banner block", role: "alert", text: msg });
  after.before(b); setTimeout(() => b.remove(), 9000);
}
async function attachPage() {
  try {
    const out = await api("POST", "page", { session_id: S.session, url: $("page-url").value, title: $("page-title").value, selected_text: $("page-text").value, origin: "paste" });
    applySession(out.session); announce("Page content attached as untrusted evidence.");
    $("page-text").value = "";
  } catch (e) { alertBox($("sources"), "Page not attached: " + e.message); }
}

// screen capture: explicit surface selection, visible indicator, explicit stop
let screenStream = null;
async function captureScreen() {
  if (!navigator.mediaDevices || !navigator.mediaDevices.getDisplayMedia) { alertBox($("sources"), "Screen capture is not available in this browser."); return; }
  try { screenStream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: false }); }
  catch (e) { alertBox($("sources"), "Screen capture was not started: " + e.name); return; }
  const track = screenStream.getVideoTracks()[0];
  $("btn-screen-stop").hidden = false; $("screen-status").hidden = false;
  $("screen-status").textContent = "● Capturing: " + track.label + ". Grabbing one frame…";
  track.addEventListener("ended", stopScreen);
  const video = el("video", { muted: true, playsinline: true }); video.srcObject = screenStream; await video.play();
  await new Promise((r) => setTimeout(r, 300));
  const c = document.createElement("canvas"); c.width = video.videoWidth; c.height = video.videoHeight;
  c.getContext("2d").drawImage(video, 0, 0);
  const blob = await new Promise((r) => c.toBlob(r, "image/png"));
  const digest = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", await blob.arrayBuffer()))).map((b) => b.toString(16).padStart(2, "0")).join("");
  const out = await api("POST", "screen", { session_id: S.session, pixel_sha256: digest, width: c.width, height: c.height, surface_label: track.label, captured_utc: new Date().toISOString() });
  applySession(out.session);
  $("screen-status").textContent = `● Capture active (${track.label}). Last frame ${new Date().toLocaleTimeString()} · ${c.width}×${c.height}. Pixels only: no text was extracted.`;
}
function stopScreen() {
  if (screenStream) screenStream.getTracks().forEach((t) => t.stop());
  screenStream = null; $("btn-screen-stop").hidden = true; $("screen-status").textContent = "Screen capture stopped.";
}

// ------------------------------------------------------------------ 4 plan / confirm / run
function renderPlan() {
  const v = $("plan-view");
  const p = S.plan;
  $("btn-confirm").disabled = !p || (S.confirmation && S.confirmation.plan_hash === p.canonical_plan_hash);
  $("btn-run").disabled = !(S.confirmation && p && S.confirmation.plan_hash === p.canonical_plan_hash && S.confirmation.revision === S.revision);
  $("blind").hidden = !(p && p.data_mode === "SYNTHETIC" && p.executable);
  if (!p) { v.hidden = true; return; }
  v.hidden = false; v.replaceChildren();
  v.append(el("div", { class: "row" }, modeBadge(p.data_mode), el("span", { class: "chip", text: "revision " + p.revision }), el("span", { class: "chip mono", text: "plan " + p.canonical_plan_hash.slice(0, 12) }),
    S.confirmation && S.confirmation.plan_hash === p.canonical_plan_hash ? el("span", { class: "chip", text: "✓ confirmed" }) : null));
  if (!p.executable) v.append(el("div", { class: "banner block", text: "■ This plan cannot run here: " + p.blocked_reason }));
  v.append(el("dl", { class: "kv" },
    el("dt", { text: "Estimand" }), el("dd", { text: p.estimand }),
    el("dt", { text: "Population" }), el("dd", { text: p.population.label + (p.population.user_population_note ? ` (your population "${p.population.user_population_note.label}" applies to real-data runs only)` : "") }),
    el("dt", { text: "Units" }), el("dd", { text: p.effect_units }),
    el("dt", { text: "Practical floor" }), el("dd", { text: String(p.practical_effect_floor) }),
    el("dt", { text: "Mandatory checks" }), el("dd", { text: p.mandatory_attacks.join(", ") }),
    el("dt", { text: "Budget" }), el("dd", { text: `${p.compute_budget.permutations} permutations, ${p.compute_budget.bootstrap} bootstrap, ${p.compute_budget.timeout_seconds}s` }),
    el("dt", { text: "Sources bound" }), el("dd", { text: p.sources.length ? p.sources.map((h) => h.slice(0, 10)).join(", ") : "none" }),
    el("dt", { text: "Interpreter" }), el("dd", { text: p.creator_model_prompt.interpreter }),
    el("dt", { text: "Epoch" }), el("dd", { text: p.plan_note })));
}
async function proposePlan() {
  try {
    const out = await api("POST", "plan", { session_id: S.session, data_mode: $("data-mode").value });
    applySession(out.session); $("revoked-banner").hidden = true;
    say(out.plan.executable ? "Here is the research plan. Confirm it to run." : "This plan can't run here. " + out.plan.blocked_reason);
  } catch (e) { alertBox($("plan-view"), e.message); }
}
async function confirmPlan() {
  const p = S.plan; if (!p) return;
  try { const out = await api("POST", "confirm", { session_id: S.session, revision: p.revision, plan_hash: p.canonical_plan_hash }); applySession(out.session); setState("CONFIRMED"); announce("Plan confirmed."); }
  catch (e) { alertBox($("plan-view"), "Confirmation refused: " + e.message); await refreshSession(); }
}
let pendingRunReq = null;
async function runLoop() {
  if (!pendingRunReq) pendingRunReq = reqId();          // double clicks reuse the same request id
  const blind = document.querySelector('input[name="blind-mode"]:checked').value === "random"
    ? { random: true } : { random: false, family: $("blind-family").value, effect: $("blind-effect").value };
  try {
    const out = await api("POST", "run", { session_id: S.session, request_id: pendingRunReq, blind });
    $("blind-family").selectedIndex = 0; $("blind-effect").selectedIndex = 0;   // selection does not stay on screen
    $("blind-sealed").hidden = false;
    setState("RUNNING"); $("btn-cancel").disabled = false; $("btn-run").disabled = true;
    $("trace").replaceChildren(); $("verdict-card").hidden = true; $("reveal-view").replaceChildren();
    say("Running the planned checks.");
    poll(out.run.run_id);
  } catch (e) { alertBox($("plan-view"), "Run refused: " + e.message); pendingRunReq = null; }
}
const WHO = { fetching: "Custodian", validating: "Discoverer", estimating: "Discoverer", challenging: "Challenger", referee: "Referee", complete: "Referee" };
function poll(runId) {
  clearTimeout(S.pollTimer);
  const tick = async () => {
    let r;
    try { r = await api("GET", `run/${runId}?session_id=${S.session}`); } catch { S.pollTimer = setTimeout(tick, 1000); return; }
    const ol = $("trace"); ol.replaceChildren(...r.events.map((e) => el("li", {},
      el("span", { class: "t", text: e.t.slice(11, 19) }), el("span", { class: "who " + (WHO[e.stage] || ""), text: WHO[e.stage] || e.stage }), el("span", { text: e.detail || e.stage }))));
    if (r.status === "RUNNING") { S.pollTimer = setTimeout(tick, 400); return; }
    pendingRunReq = null; $("btn-cancel").disabled = true; $("blind-sealed").hidden = true;
    await refreshSession();
    if (r.status === "CANCELLED" || r.status === "SUPERSEDED") {
      ol.append(el("li", {}, el("span", { class: "t", text: "" }), el("span", { class: "who", text: "Orchestrator" }), el("span", { text: `Run ${r.status.toLowerCase()}; any late result is kept as historical evidence only.` })));
      setState("STOPPED"); return;
    }
    S.runViews[runId] = r; renderVerdict(r); setState("IDLE");
    const d = r.result.decision;
    say(d === "SURVIVED_PROTOCOL" ? "In this synthetic league, the claim survived every planned check."
      : d === "NOT_SUPPORTED" ? "This claim did not survive the planned checks in this synthetic league."
      : d === "INSUFFICIENT_EVIDENCE" ? "We do not have enough evidence to tell." : "The run could not produce a decision. " + r.result.reason);
  };
  tick();
}
async function cancelRun() {
  try { await api("POST", "cancel", { session_id: S.session }); announce("Cancel requested."); } catch (e) { announce(e.message); }
}

// ------------------------------------------------------------------ 6 verdict
// Renders the Referee evidence view (web/referee.js). Today's runs come from the stand-in engine and
// are labelled so; a record opened from disk is rendered through the same view. PROVISIONAL until
// Max's Referee evidence record format is delivered.
const OUTCOME_CELL = { PASSED: ["pass", "✓ passed"], FAILED: ["fail", "✕ failed"], NOT_RUN: ["not-run", "– not run"],
  ERROR: ["fail", "! error"], UNRECOGNISED: ["fail", "? unrecognised outcome"] };
function valueEl(tag, v, attrs = {}) {
  return el(tag, { ...attrs, class: [attrs.class, v && v.available ? null : "unavailable"].filter(Boolean).join(" ") || null, text: referee.show(v) });
}
function renderRefereeView(vm, { historical = false } = {}) {
  $("verdict-card").hidden = false;
  const src = vm.source === "STAND_IN_ENGINE"
    ? el("div", { class: "banner warn" }, el("strong", { text: "Stand-in engine output, not a Referee record. " }),
        "Shown in the Referee evidence layout so the screen is ready for the real record. ", el("span", { class: "hint", text: vm.format_status }))
    : el("div", { class: "banner info" }, el("strong", { text: "Referee evidence record opened from a file. " }), el("span", { class: "hint", text: vm.format_status }));
  $("ref-source").replaceChildren(src, el("div", { class: "row" }, vm.data_mode ? modeBadge(vm.data_mode) : el("span", { class: "chip", text: "data mode not recognised" }),
    historical ? el("span", { class: "chip", text: "historical: claim changed since" }) : null));

  const c = vm.claim;
  $("ref-claim").replaceChildren(...(c ? [["Statement", c.statement], ["Claim ID", c.claim_id], ["Plan hash", c.plan_hash], ["Revision", c.revision]]
    .flatMap(([k, v]) => [el("dt", { text: k }), valueEl("dd", v, { class: k === "Plan hash" ? "mono" : null })])
    : [el("dt", { text: "Claim" }), el("dd", { class: "unavailable", text: "unavailable: no claim in this record" })]));

  const tb = $("attacks").tBodies[0];
  tb.replaceChildren(...(vm.attacks.length ? vm.attacks.map((a) => {
    const [cls, label] = OUTCOME_CELL[a.outcome] || OUTCOME_CELL.UNRECOGNISED;
    return el("tr", {}, valueEl("td", a.test_id, { class: "mono" }), el("td", { class: cls, text: label }),
      valueEl("td", a.statistic, { class: "num" }), valueEl("td", a.p_value, { class: "num" }),
      el("td", {}, valueEl("span", a.method), a.reason ? el("span", { class: "hint", text: " " + a.reason }) : null));
  }) : [el("tr", {}, el("td", { colspan: "5", class: "unavailable", text: "No attacks reported." }))]));

  const vd = vm.verdict;
  $("verdict").replaceChildren(el("div", { class: `decision ${vd.recognised ? vd.decision : "UNRECOGNISED"}${historical ? " historical" : ""}` },
    el("span", { class: "icon", "aria-hidden": "true", text: vd.icon }),
    el("div", {}, el("div", { class: "label", text: vd.decision }), el("div", { text: vd.plain }),
      vd.reason ? el("p", { class: "why hint", text: vd.reason }) : null,
      el("p", { class: "hint", text: "A claim that does not survive is not proof of luck: it did not survive this protocol on this data." }))));

  $("ref-evidence").replaceChildren(...(vm.evidence.length ? vm.evidence.map((e) => el("li", {}, el("span", { class: "k", text: e.label }), valueEl("span", e.value, { class: "v" })))
    : [el("li", { class: "unavailable", text: "No evidence items in this record." })]));
  $("ref-problems-count").textContent = `(${vm.problems.length})`;
  $("ref-problems").replaceChildren(...vm.problems.map((p) => el("li", { text: p })));
  $("ref-problems-wrap").hidden = !vm.problems.length;
  announce(`Referee view: ${vd.decision}. ${vm.attacks.length} attacks listed.`);
}
async function openRefereeFile(file) {
  let rec;
  try { rec = JSON.parse(await file.text()); } catch (e) { rec = null; announce("That file is not valid JSON."); }
  const vm = referee.fromRecord(rec);
  if (rec === null) vm.problems.unshift(`${file.name}: not valid JSON`);
  renderRefereeView(vm);
  $("btn-reveal").hidden = true; $("standin-extras").hidden = true;
  for (const id of ["dl-json", "dl-csv"]) { $(id).removeAttribute("href"); $(id).hidden = true; }   // a file record is not a server run
}
function renderVerdict(r) {
  const res = r.result;
  const plan = S.plan && S.plan.canonical_plan_hash === r.plan_hash ? S.plan : null;   // never show another revision's claim
  renderRefereeView(referee.fromStandInRun(r, plan), { historical: r.revision !== S.revision });
  $("standin-extras").hidden = false; $("dl-json").hidden = false; $("dl-csv").hidden = false;
  $("dl-json").href = `/api/export/${r.run_id}?session_id=${S.session}`;
  $("dl-csv").href = `/api/export/${r.run_id}?session_id=${S.session}&format=csv`;
  $("btn-reveal").hidden = !(res.data_mode === "SYNTHETIC" && res.attacks && res.attacks.length);
  $("btn-reveal").dataset.run = r.run_id;
  if (r.reveal) renderReveal(r.reveal);
  if (res.talent) renderTalent(res.talent); else { $("talent-chart").replaceChildren(el("p", { class: "hint", text: "Talent estimates unavailable for this run." })); $("talent-table").replaceChildren(); }
}
async function reveal() {
  const rid = $("btn-reveal").dataset.run;
  try { renderReveal(await api("POST", "reveal", { session_id: S.session, run_id: rid })); }
  catch (e) { alertBox($("reveal-view"), e.message); }
}
function renderReveal(m) {
  const good = m.outcome === "TRUE_DISCOVERY" || m.outcome === "CORRECT_REJECTION";
  const words = { TRUE_DISCOVERY: "a real planted effect was kept", FALSE_DISCOVERY: "a false discovery: no real effect, but it survived",
    MISSED_EFFECT: "a missed effect: a real effect was planted but not kept", CORRECT_REJECTION: "a correct rejection: no real effect, and it was not kept", NO_DECISION: "no decision to score" }[m.outcome];
  $("reveal-view").replaceChildren(el("div", { class: "banner " + (good ? "info" : "warn") },
    el("strong", { text: "Truth revealed after the decision. " }),
    `Family ${m.family}${m.held_out_family ? " (held-out family)" : ""}, effect ${m.effect} (size ${m.effect_size}). Decision ${m.decision_at_reveal}: ${words}.`));
  $("btn-reveal").hidden = true;
}

function tooltip(evt, text) {
  const t = $("tooltip"); t.textContent = text; t.hidden = false;
  t.style.left = Math.min(evt.clientX + 12, innerWidth - 270) + "px"; t.style.top = evt.clientY + 12 + "px";
}
function hideTip() { $("tooltip").hidden = true; }

function renderTalent(t) {
  const rows = [...t.rows].sort((a, b) => a.raw - b.raw);
  const W = 640, rowH = 14, top = 26, left = 52, right = 14, H = top + rows.length * rowH + 24;
  const lo = Math.min(...rows.map((r) => Math.min(r.raw, r.interval[0]))), hi = Math.max(...rows.map((r) => Math.max(r.raw, r.interval[1])));
  const x0 = Math.floor(lo * 20) / 20, x1 = Math.ceil(hi * 20) / 20;
  const X = (v) => left + ((v - x0) / (x1 - x0)) * (W - left - right);
  const svg = sv("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": `Raw and shrunk make rates for ${rows.length} anonymised shooters` });
  const g = sv("g", { class: "grid" });
  for (let v = x0; v <= x1 + 1e-9; v += 0.05) {
    g.append(sv("line", { x1: X(v), x2: X(v), y1: top - 6, y2: H - 22 }));
    const tx = sv("text", { x: X(v), y: H - 6, "text-anchor": "middle" }); tx.textContent = (v * 100).toFixed(0) + "%";
    const ax = sv("g", { class: "axis" }); ax.append(tx); svg.append(ax);
  }
  svg.prepend(g);
  rows.forEach((r, i) => {
    const y = top + i * rowH + rowH / 2;
    const lab = sv("text", { x: left - 6, y: y + 4, "text-anchor": "end", class: "lbl" }); lab.textContent = r.shooter; svg.append(lab);
    svg.append(sv("line", { x1: X(r.interval[0]), x2: X(r.interval[1]), y1: y, y2: y, stroke: "var(--series-2)", "stroke-width": 2, "stroke-linecap": "round", opacity: .55 }));
    svg.append(sv("circle", { cx: X(r.raw), cy: y, r: 4, fill: "var(--series-1)", stroke: "var(--surface)", "stroke-width": 2 }));
    svg.append(sv("circle", { cx: X(r.shrunk), cy: y, r: 4, fill: "var(--series-2)", stroke: "var(--surface)", "stroke-width": 2 }));
    const hit = sv("rect", { x: left, y: y - rowH / 2, width: W - left - right, height: rowH, fill: "transparent" });
    hit.addEventListener("mousemove", (e) => tooltip(e, `${r.shooter}: raw ${pct(r.raw)} (${r.makes}/${r.attempts}) · shrunk ${pct(r.shrunk)} · 90% ${pct(r.interval[0])}–${pct(r.interval[1])}`));
    hit.addEventListener("mouseleave", hideTip);
    svg.append(hit);
  });
  const legend = el("div", { class: "legend" }, el("span", {}, el("i", { class: "sw1" }), "Raw make rate"),
    el("span", {}, el("i", { class: "sw2" }), "Shrunk estimate and 90% interval"));
  $("talent-chart").replaceChildren(legend, svg,
    el("p", { class: "hint", text: `${t.method}. Prior Beta(${t.prior.a.toFixed(1)}, ${t.prior.b.toFixed(1)}). Reliability (talent share of observed variance) ${fmt(t.reliability, 2)}.` }));
  $("talent-table").replaceChildren(el("thead", {}, el("tr", {}, ...["Shooter", "Makes", "Attempts", "Raw", "Shrunk", "90% interval"].map((h) => el("th", { text: h })))),
    el("tbody", {}, ...rows.map((r) => el("tr", {}, el("td", { text: r.shooter }), el("td", { class: "num", text: r.makes }), el("td", { class: "num", text: r.attempts }),
      el("td", { class: "num", text: pct(r.raw) }), el("td", { class: "num", text: pct(r.shrunk) }), el("td", { class: "num", text: `${pct(r.interval[0])}–${pct(r.interval[1])}` })))));
}

function renderHistory(runs) {
  const ul = $("history"); ul.replaceChildren();
  for (const r of [...runs].reverse()) {
    ul.append(el("li", {}, el("span", { class: "chip mono", text: r.run_id.slice(0, 8) }), el("span", { class: "chip", text: "rev " + r.revision }),
      el("strong", { text: r.status }), r.decision ? el("span", { class: "mono", text: decisionMeta(r.decision)[0] + " " + r.decision }) : null, r.authority === "none" ? el("span", { class: "hint", text: "historical: no current authority" }) : null,
      r.has_result ? el("button", { class: "ghost", text: "Open", onclick: async () => { const v = await api("GET", `run/${r.run_id}?session_id=${S.session}`); renderVerdict(v); } }) : null));
  }
}

// ------------------------------------------------------------------ commands + voice
const voice = createVoice({
  onState: setState,
  onTranscript: (text, metrics) => {
    $("claim-text").value = text;
    const t0 = performance.now();
    interpret(text, "voice").then(() => { metrics.feedback_ms = Math.round(performance.now() - t0); S.latency.push(metrics); renderLatency(); });
  },
  onStatus: (msg) => ($("mic-status").textContent = msg),
  onError: (msg) => { $("mic-status").textContent = msg; S.latency.push({ provider: $("voice-provider").value, result: "error: " + msg }); renderLatency(); },
  provider: () => $("voice-provider").value,
});
function say(text) { if (!$("voice-mute").checked) voice.speak(text); }
function renderLatency() {
  $("latency").tBodies[0].replaceChildren(...S.latency.map((m) => el("tr", {}, el("td", { text: m.provider }), el("td", { class: "num", text: m.transcript_ms ?? "—" }),
    el("td", { class: "num", text: m.feedback_ms ?? "—" }), el("td", { text: m.result || "ok" }))));
}
async function runCommand(cmd) {
  announce("Command: " + cmd.replaceAll("_", " "));
  if (cmd === "stop") { voice.stopAll(); if (S.currentRun) await cancelRun(); setState("STOPPED"); return; }
  if (cmd === "challenge") { if (!$("btn-run").disabled) return runLoop(); say("Confirm the exact plan first."); return; }
  if (cmd === "attach_evidence") { $("file-input").closest(".card").scrollIntoView(); document.querySelector('label[for="file-input"]').focus(); say("Choose a file. The browser needs you to click to pick it."); return; }
  if (cmd === "show_rejected") { $("verdict-card").scrollIntoView(); $("attacks").focus?.(); return; }
  if (cmd === "compare_market" || cmd === "compare_forecast") { selectTab($(cmd === "compare_market" ? "tab-market" : "tab-forecast")); return; }
  if (cmd === "export") { const a = $("dl-json"); if (a.href) a.click(); else say("There is no run to export yet."); }
}

// ------------------------------------------------------------------ market
async function initMarket() {
  const d = await api("GET", "market-scenarios");
  S.market = d;
  const sel = $("mk-source");
  sel.replaceChildren(el("optgroup", { label: "Authored SYNTHETIC fixtures (offline)" }, ...d.scenarios.map((s) => el("option", { value: "fixture:" + s.id, text: `${s.venue}: ${s.description}` }))),
    el("optgroup", { label: "Live public data" }, el("option", { value: "live", text: "Live read-only fetch (needs network access to the venue)" })));
  sel.addEventListener("change", () => ($("mk-live").hidden = sel.value !== "live"));
  const f = d.forecast, g = d.game;
  const card = () => el("div", { class: "banner info" }, el("div", { class: "row" }, modeBadge(f.data_mode), el("strong", { text: `${g.away_team} at ${g.home_team}` }), el("span", { class: "hint", text: "tip " + g.scheduled_tip_utc })),
    el("dl", { class: "kv" }, el("dt", { text: "Forecast" }), el("dd", { text: `P(${f.team} wins, incl. overtime) = ${f.probability}` }),
      el("dt", { text: "Cutoff" }), el("dd", { text: f.cutoff_utc }), el("dt", { text: "Model" }), el("dd", { text: f.model }),
      el("dt", { text: "Calibration" }), el("dd", { text: f.calibration_scope }),
      el("dt", { text: "Freshness rule" }), el("dd", { text: `historical quote must be observed ≤ ${d.freshness_seconds.historical}s before the cutoff; live ≤ ${d.freshness_seconds.live}s old` })));
  $("mk-forecast").replaceChildren(card());
  $("forecast-view").replaceChildren(card());
}
let proposal = null;
async function marketPropose() {
  const src = $("mk-source").value;
  $("mk-result-card").hidden = true;
  proposal = null; $("btn-mk-compare").disabled = true;
  $("mk-spec-card").hidden = false; $("mk-approve").hidden = true;
  $("mk-spec").replaceChildren(el("p", { class: "hint", text: "Fetching market metadata…" }));
  const out = await api("POST", "market-propose", { source: src, venue: $("mk-venue").value, ref: $("mk-ref").value.trim() });
  proposal = out; $("mk-spec-card").hidden = false;
  const box = $("mk-spec"); box.replaceChildren();
  if (!out.spec) {
    box.append(el("div", { class: "banner block" }, el("span", { class: "status-pill bad", text: out.status }), " ", out.reason));
    $("mk-approve").hidden = true; say("No comparable market: " + out.reason); return;
  }
  $("mk-approve").hidden = false;
  const s = out.spec, m = out.mapping;
  box.append(el("div", { class: "row" }, modeBadge(s.data_mode), el("strong", { text: s.venue }), el("span", { text: s.title })),
    el("dl", { class: "kv" },
      el("dt", { text: "Market" }), el("dd", { class: "mono", text: s.market_id }),
      el("dt", { text: "Outcomes" }), el("dd", { text: s.outcome_contract_ids.map((o) => `${o.label} → ${o.contract_id}${o.yes_means ? " (YES means " + o.yes_means + ")" : ""}`).join("; ") }),
      el("dt", { text: "Rules hash" }), el("dd", { class: "mono", text: s.rules_hash.slice(0, 16) }),
      el("dt", { text: "Retrieved" }), el("dd", { text: `${s.provenance.received_at_utc} · raw ${s.provenance.raw_hash.slice(0, 12)} · ${s.provenance.transport}` })),
    el("details", {}, el("summary", { text: "Contract rules text" }), el("pre", { class: "mono", text: s.rules_text })));
  const ok = m.status === "PROPOSED";
  box.append(el("h3", { text: "Automated checks (cannot approve)" }),
    el("ul", { class: "checks" },
      el("li", { text: `Teams: ${m.participants_date.away} at ${m.participants_date.home}; market start ${m.participants_date.market_game_start || "not stated"}` }),
      el("li", { text: `Outcome meaning ${m.outcome_direction.target_team} wins → ${m.outcome_direction.contract_id || "not identified"}` }),
      el("li", { text: `Overtime: ${m.regulation_overtime_convention}` }),
      el("li", { text: `Postponement/cancellation: ${m.cancel_postpone_convention.stated ? m.cancel_postpone_convention.excerpt : "not stated"}` })),
    el("div", { class: "banner " + (ok ? "info" : "block") }, el("span", { class: "status-pill " + (ok ? "neutral" : "bad"), text: m.status }), " ", m.reason));
  $("btn-mk-compare").disabled = false;
}
async function marketCompare() {
  if (!proposal) return;
  if (!$("mk-attest").checked) { alertBox($("btn-mk-compare"), "Tick the review attestation first."); return; }
  let env;
  try { env = await api("POST", "market-compare", { proposal_id: proposal.proposal_id, reviewer: $("mk-reviewer").value, quote_type: $("mk-qtype").value }); }
  catch (e) { env = { status: e.code || "ERROR", blocked_reasons: [e.message], data_mode: "SYNTHETIC" }; }
  $("mk-result-card").hidden = false;
  const box = $("mk-result"); box.replaceChildren();
  const ok = env.status === "OK";
  box.append(el("div", { class: "row" }, el("span", { class: "status-pill " + (ok ? "ok" : "bad"), text: env.status }), modeBadge(env.data_mode), env.venue ? el("span", { class: "chip", text: env.venue }) : null));
  if (ok) {
    const d = Number(env.signed_probability_difference);
    box.append(el("div", { class: "diff", text: (d >= 0 ? "+" : "") + (100 * d).toFixed(1) + " pp" }),
      el("p", { text: `Forecast ${env.forecast_probability} minus ${env.quote_type_unit.type} ${env.observed_quote}${env.quote_type_unit.derived ? " (YES ask derived from the NO bid)" : ""}.` }),
      el("p", { class: "hint", text: env.note }));
  } else {
    box.append(el("p", { text: "No numerical comparison." }), el("ul", {}, ...(env.blocked_reasons || []).map((r) => el("li", { text: typeof r === "string" ? r : JSON.stringify(r) }))));
  }
  if (env.timestamps_freshness) {
    const f = env.timestamps_freshness;
    box.append(el("dl", { class: "kv" }, el("dt", { text: "Forecast cutoff" }), el("dd", { text: env.forecast.cutoff_utc }),
      el("dt", { text: "Quote observed" }), el("dd", { text: f.observed_at || "unknown" }),
      el("dt", { text: "Freshness" }), el("dd", { text: `${f.status} · age ${Math.round(f.age_seconds)}s at ${f.basis}${f.threshold_seconds ? " · threshold " + f.threshold_seconds + "s" : ""}` })));
  }
  if (env.book) {
    const b = env.book;
    const side = (levels, label) => el("div", {}, el("h3", { text: label }), el("table", {}, el("thead", {}, el("tr", {}, el("th", { text: "Price" }), el("th", { text: "Quantity" }), el("th", { text: "Source" }))),
      el("tbody", {}, ...(levels.length ? levels.slice(0, 5).map((l) => el("tr", {}, el("td", { class: "num", text: l.price }), el("td", { class: "num", text: l.qty }), el("td", { text: l.derived ? "derived from NO bid" : l.raw_side }))) : [el("tr", {}, el("td", { colspan: 3, text: "none: side unavailable (not zero)" }))]))));
    box.append(el("div", { class: "ladder" }, side(b.levels.bids, "Bids (YES / outcome token)"), side(b.levels.asks, "Asks")),
      el("p", { class: "hint", text: `Spread ${b.spread ?? "unavailable"} · midpoint ${b.midpoint ?? "unavailable (" + b.midpoint_unavailable_reason + ")"} · raw ${b.raw_hash.slice(0, 12)} · adapter ${b.adapter_version}. ${b.clock_uncertainty}.` }));
  }
  say(ok ? "Comparison ready. The difference is descriptive only." : "No comparison: " + env.status.replaceAll("_", " ").toLowerCase());
}

// ------------------------------------------------------------------ harness + gates
async function loadHarness() {
  const h = await api("GET", "harness");
  const [d, t] = h.progress || [0, 0];
  $("h-progress").textContent = h.status === "RUNNING" ? `running ${d}/${t} leagues` : h.status === "ERROR" ? "error: " + h.error : h.result ? `last run ${h.result.generated_at_utc || ""}${h.cached ? " (loaded from evidence/harness_batch.json)" : ""}` : "";
  if (h.status === "RUNNING") setTimeout(loadHarness, 1000);
  if (h.result) renderHarness(h.result);
}
async function startHarness() {
  try { await api("POST", "harness", { leagues_per_cell: Number($("h-n").value) }); loadHarness(); } catch (e) { $("h-progress").textContent = e.message; }
}
function renderHarness(r) {
  const v = $("harness-view"); v.replaceChildren();
  const summary = (label, s) => el("div", { class: "card" }, el("h3", { text: label }),
    el("dl", { class: "kv" },
      el("dt", { text: "Null leagues kept (false survivals)" }), el("dd", { text: `${s.false_survivals} of ${s.null_leagues} · rate ${pct(s.false_survival_rate)} (95% ${pct(s.false_survival_interval95?.[0])}–${pct(s.false_survival_interval95?.[1])})` }),
      el("dt", { text: "Effect leagues kept (power)" }), el("dd", { text: `${s.true_survivals} of ${s.effect_leagues} · ${pct(s.power)} (95% ${pct(s.power_interval95?.[0])}–${pct(s.power_interval95?.[1])})` }),
      el("dt", { text: "Share of survivors that were false" }), el("dd", { text: s.survived_total ? `${pct(s.false_discovery_proportion)} of ${s.survived_total}` : "no survivors" })));
  v.append(el("div", { class: "row" }, modeBadge(r.data_mode), el("span", { class: "chip mono", text: r.engine }), el("span", { class: "hint", text: r.scope })),
    el("div", { class: "grid" }, summary(`Tuning families (${r.tuning_families.join(", ")})`, r.tuning_summary), summary(`Held-out family (${r.held_out_family})`, r.held_out_summary)));
  const decs = ["SURVIVED_PROTOCOL", "NOT_SUPPORTED", "INSUFFICIENT_EVIDENCE", "BLOCKED", "DATA_INVALID"];
  v.append(el("h3", { text: "Decisions by planted truth (counts)" }), el("div", { class: "tablewrap" }, el("table", {},
    el("thead", {}, el("tr", {}, el("th", { text: "Family" }), el("th", { text: "Planted" }), ...decs.slice(0, 3).map((d) => el("th", { text: d })))),
    el("tbody", {}, ...Object.values(r.cells).map((c) => el("tr", {}, el("td", { text: c.family + (c.held_out ? " (held-out)" : "") }), el("td", { text: c.effect }),
      ...decs.slice(0, 3).map((d) => el("td", { class: "num", text: `${c.decisions[d] || 0}/${c.n}` }))))))));
  // detectability: survival rate vs planted effect size with Wilson intervals (single series)
  const pts = Object.values(r.detectability).sort((a, b) => a.effect_size - b.effect_size);
  const W = 560, H = 230, L = 46, R = 14, T = 12, B = 34;
  const xmax = Math.max(...pts.map((p) => p.effect_size)) || 1;
  const X = (x) => L + (x / xmax) * (W - L - R), Y = (y) => T + (1 - y) * (H - T - B);
  const svg = sv("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Share of leagues where the claim survived, by planted effect size" });
  const ax = sv("g", { class: "axis" });
  for (const y of [0, 0.25, 0.5, 0.75, 1]) { ax.append(sv("line", { x1: L, x2: W - R, y1: Y(y), y2: Y(y) })); const t = sv("text", { x: L - 6, y: Y(y) + 4, "text-anchor": "end" }); t.textContent = y * 100 + "%"; ax.append(t); }
  for (const p of pts) { const t = sv("text", { x: X(p.effect_size), y: H - 14, "text-anchor": "middle" }); t.textContent = (p.effect_size * 100).toFixed(0) + "pp"; ax.append(t); }
  const xt = sv("text", { x: (L + W - R) / 2, y: H - 1, "text-anchor": "middle" }); xt.textContent = "planted hot-hand effect (make probability after 3 makes)"; ax.append(xt);
  svg.append(ax);
  svg.append(sv("polyline", { points: pts.map((p) => `${X(p.effect_size)},${Y(p.rate)}`).join(" "), fill: "none", stroke: "var(--series-1)", "stroke-width": 2 }));
  for (const p of pts) {
    svg.append(sv("line", { x1: X(p.effect_size), x2: X(p.effect_size), y1: Y(p.interval95[0]), y2: Y(p.interval95[1]), stroke: "var(--series-1)", "stroke-width": 2, opacity: .45, "stroke-linecap": "round" }));
    const c = sv("circle", { cx: X(p.effect_size), cy: Y(p.rate), r: 5, fill: "var(--series-1)", stroke: "var(--surface)", "stroke-width": 2 });
    const hit = sv("circle", { cx: X(p.effect_size), cy: Y(p.rate), r: 14, fill: "transparent" });
    hit.addEventListener("mousemove", (e) => tooltip(e, `effect ${(p.effect_size * 100).toFixed(0)}pp: survived ${p.survived}/${p.n} (${pct(p.rate)}), 95% ${pct(p.interval95[0])}–${pct(p.interval95[1])}`));
    hit.addEventListener("mouseleave", hideTip);
    svg.append(c, hit);
  }
  v.append(el("h3", { text: "Detectability: how often a planted effect survives (parametric family)" }), el("div", { class: "viz-root chart" }, svg),
    el("details", {}, el("summary", { text: "Detectability table" }), el("table", {}, el("thead", {}, el("tr", {}, ...["Effect", "Survived", "Leagues", "Rate", "95% interval"].map((h) => el("th", { text: h })))),
      el("tbody", {}, ...pts.map((p) => el("tr", {}, el("td", { class: "num", text: p.effect_size }), el("td", { class: "num", text: p.survived }), el("td", { class: "num", text: p.n }), el("td", { class: "num", text: pct(p.rate) }), el("td", { class: "num", text: `${pct(p.interval95[0])}–${pct(p.interval95[1])}` })))))),
    el("p", { class: "hint", text: r.caveat }));
}
async function loadGates() {
  const g = await api("GET", "gates");
  $("gates").tBodies[0].replaceChildren(...g.gates.map((x) => el("tr", {}, el("td", {}, el("strong", { text: x.id }), " ", x.name), el("td", { text: x.owner }),
    el("td", { class: "mono", text: x.status }), el("td", { text: (x.evidence || []).map((e) => typeof e === "string" ? e : e.summary || JSON.stringify(e)).join(" · ") || x.required_evidence }))));
}

// ------------------------------------------------------------------ boot
async function boot() {
  const h = await api("GET", "health");
  $("engine-chip").textContent = `research engine: ${h.research_engine ? "connected" : "not connected"} · fixture ${h.engine}`;
  $("code-hash").textContent = "code " + h.code_hash.slice(0, 12);
  const s = await api("POST", "session", {}); S.session = s.session_id; applySession(s);
  $("pair-code").textContent = s.session_id;
  for (const f of ["parametric_beta_binomial", "heavy_tailed_talent", "ar1_drift"]) $("blind-family").append(el("option", { value: f, text: f }));
  for (const e of ["null", "weak", "planted", "confounded"]) $("blind-effect").append(el("option", { value: e, text: e }));
  document.querySelectorAll('input[name="blind-mode"]').forEach((r) => r.addEventListener("change", () => ($("blind-choose").hidden = r.value !== "choose" || !r.checked)));
  $("btn-interpret").addEventListener("click", () => interpret($("claim-text").value));
  $("claim-text").addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) interpret($("claim-text").value); });
  $("claim-text").addEventListener("input", () => { S.interpSeq++; });   // typing invalidates in-flight interpretations
  $("btn-approve").addEventListener("click", approve);
  $("file-input").addEventListener("change", (e) => e.target.files[0] && attachFile(e.target.files[0]));
  $("btn-page").addEventListener("click", attachPage);
  $("btn-screen").addEventListener("click", captureScreen);
  $("btn-screen-stop").addEventListener("click", stopScreen);
  $("btn-plan").addEventListener("click", proposePlan);
  $("btn-confirm").addEventListener("click", confirmPlan);
  $("btn-run").addEventListener("click", runLoop);
  $("btn-cancel").addEventListener("click", cancelRun);
  $("btn-reveal").addEventListener("click", reveal);
  $("ref-file").addEventListener("change", (e) => { const f = e.target.files[0]; if (f) openRefereeFile(f); e.target.value = ""; });
  $("btn-mic").addEventListener("click", () => voice.toggle());
  $("btn-stop-speak").addEventListener("click", () => voice.stopSpeaking());
  $("btn-mk-propose").addEventListener("click", marketPropose);
  $("btn-mk-compare").addEventListener("click", marketCompare);
  $("btn-harness").addEventListener("click", startHarness);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") { voice.stopAll(); } });
  await initMarket();
  window.__heatcheck = { S };   // test hook (read-only inspection)
}
boot().catch((e) => { setState("ERROR"); document.body.prepend(el("div", { class: "banner block", role: "alert", text: "Could not reach the HeatCheck server: " + e.message })); });
