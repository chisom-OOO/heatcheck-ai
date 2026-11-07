// Demo page: every state in its own self-contained cell (pose large, card beside it on wide
// screens and below it on narrow ones), plus the full per-question sequence on a real
// evidence record. Records come from GET /api/evidence when the server verifies a ledger,
// otherwise from the byte-identical fixture copy of Max's committed ledger.

import { loadLines, mount, playSequence, renderCard } from "./heater.js";
import { POSE_FOR_STATE, cardModel, parseJsonl } from "./heater-model.js";

// state, title, what the motion does, and which committed record (if any) the card shows
const CELLS = [
  ["idle", "Waiting on the take", "Slow bob; sparks drift up from the head.", null],
  ["listening", "Listening", "Brightness follows the mic level while you ask.", null],
  ["thinking", "Thinking", "Slight sway while the record loads.", null],
  ["hot_take", "Hot take", "Squash-bounce on every spoken word, ±3 px shake on CAPS words.", ["HH-K2", "take"]],
  ["heat_check", "Heat check", "The Ref scans him: 0.6 s slice-glitch with teal and violet fringes.", ["HH-K2", "ref"]],
  ["vindicated", "Vindicated", "SURVIVED_PROTOCOL: scale-pop and glow.", "none"],
  ["cooled", "Cooled", "NOT_SUPPORTED: slow sink, desaturate, fewer sparks.", ["HH-K2", "verdict"]],
  ["unsure", "Unsure", "INSUFFICIENT_EVIDENCE: wobble, half the sparks.", ["HH-K3", "verdict"]],
  ["blocked", "Blocked", "BLOCKED / DATA_INVALID: muted colour, no sparks.", ["GP-REST", "verdict"]],
];
const ONE_SHOT = new Set(["vindicated", "cooled", "heat_check"]);
const FIXTURE = new URL("./fixtures/evidence_real_game.jsonl", import.meta.url);

async function loadLedger() {
  try {
    const r = await fetch("/api/evidence", { headers: { Accept: "application/json" } });
    if (r.ok) {
      const body = await r.json();
      if (Array.isArray(body.entries) && body.entries.length) {
        return { entries: body.entries, verified: true, source: `${body.ledger} (verified by ${body.verified_by})` };
      }
    }
  } catch { /* no evidence endpoint on this server: use the fixture */ }
  const r = await fetch(FIXTURE);
  if (!r.ok) throw new Error(`fixture ledger: HTTP ${r.status}`);
  return {
    entries: parseJsonl(await r.text()),
    verified: false,
    source: "fixtures/evidence_real_game.jsonl: byte copy of reports/max/logs/2026-11-07-loop/evidence_real_game.jsonl (hashes not verified in the browser)",
  };
}

const byClaim = (ledger, id) => ledger.entries.find((e) => e.identity.claim.claim_id === id);

function modelFor(ctx, claimId) {
  const entry = byClaim(ctx.ledger, claimId);
  if (!entry) return null;
  const m = cardModel(entry, { verified: ctx.ledger.verified, lines: ctx.lines.table });
  m.linesSource = ctx.lines.source;
  return m;
}

/** One self-contained cell: pose on the left (>= 440 px tall), text and card on the right. */
async function buildCell(state, ctx, { replay = true } = {}) {
  const [, title, desc, rec] = CELLS.find((c) => c[0] === state);
  const cell = document.createElement("article");
  cell.className = "cell";
  cell.innerHTML = `<div class="cell-in"><div class="cell-fig"><div></div></div>
    <div class="cell-side"><h3></h3><p class="desc"></p><p class="pose"></p><div class="cell-card"></div></div></div>`;
  const h3 = cell.querySelector("h3");
  h3.textContent = title;
  const code = document.createElement("code");
  code.textContent = state;
  h3.append(code);
  cell.querySelector(".desc").textContent = desc;
  const pose = POSE_FOR_STATE[state];
  cell.querySelector(".pose").textContent = pose === state
    ? `Pose: poses/${pose}.webp`
    : `Pose: poses/${pose}.webp (stand-in until its own image arrives)`;
  const slot = cell.querySelector(".cell-card");
  if (rec === "none") {
    slot.className = "cell-card empty";
    slot.textContent = "No committed record has the verdict SURVIVED_PROTOCOL, so this state is shown without a card. Nothing is invented.";
  } else if (Array.isArray(rec)) {
    const model = modelFor(ctx, rec[0]);
    if (model) renderCard(slot, model, { phase: rec[1] });
    else { slot.className = "cell-card empty"; slot.textContent = `Record ${rec[0]} not in this ledger.`; }
  } else {
    slot.remove();
  }
  const h = await mount(cell.querySelector(".cell-fig > div"), { state, hold: true });
  if (replay && ONE_SHOT.has(state)) setInterval(() => h.setState(state, { restart: true }), state === "cooled" ? 4200 : 3000);
  return { cell, heater: h };
}

async function buildGrid(ctx) {
  const grid = document.getElementById("grid");
  for (const [state] of CELLS) {
    const { cell } = await buildCell(state, ctx);
    grid.append(cell);
  }
}

async function buildSequence(ctx) {
  const heater = await mount(document.getElementById("seq-heater"), { state: "idle" });
  const card = document.getElementById("seq-card");
  renderCard(card, null);
  const sel = document.getElementById("rec");
  const phaseEl = document.getElementById("phase");
  document.getElementById("src").textContent = `Source: ${ctx.ledger.source}. Heater's lines: ${ctx.lines.source}.`;
  ctx.ledger.entries.forEach((e, i) => {
    const o = document.createElement("option");
    o.value = String(i);
    o.textContent = `${e.identity.claim.claim_id} · ${e.identity.decision}`;
    sel.append(o);
  });
  let turn = 0;
  document.getElementById("ask").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const go = document.getElementById("go");
    go.disabled = true;
    const entry = ctx.ledger.entries[Number(sel.value)];
    try {
      await playSequence(heater, card, async () => ({ entry, verified: ctx.ledger.verified, lines: ctx.lines, turn: turn++ }), {
        voiceOn: document.getElementById("voice").checked,
        mic: document.getElementById("mic").checked,
        onPhase: (p) => { phaseEl.textContent = `Phase: ${p}`; },
      });
    } finally {
      go.disabled = false;
    }
  });
}

// ?shot=<state>[&freeze=1] renders that state's cell alone for screenshots;
// ?shot=card&claim=HH-K2 renders the cell of that record's end state.
async function shotMode(params, ctx) {
  document.body.classList.add("shot");
  const box = document.createElement("div");
  box.id = "shot";
  document.body.append(box);
  let state = params.get("shot");
  if (state === "card") {
    const m = modelFor(ctx, params.get("claim"));
    state = m ? m.endState : "idle";
  }
  const { cell, heater } = await buildCell(state, ctx, { replay: false });
  box.append(cell);
  if (params.get("freeze") === "1") {
    heater.root.classList.add("h-freeze");
    cell.querySelector(".desc").textContent += " (one glitch frame held for capture)";
  }
  await Promise.all([...cell.querySelectorAll("img")].map((i) => i.decode().catch(() => null)));
  document.body.dataset.ready = "1";
}

async function main() {
  const params = new URLSearchParams(location.search);
  let ledger;
  try {
    ledger = await loadLedger();
  } catch (e) {
    document.getElementById("phase").textContent = `No evidence record available: ${e.message}`;
    document.getElementById("go").disabled = true;
    return;
  }
  const ctx = { ledger, lines: await loadLines() };
  if (params.has("shot")) return shotMode(params, ctx);
  await buildSequence(ctx);
  await buildGrid(ctx);
}

main();
