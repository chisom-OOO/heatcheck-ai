// Demo page: every state in a grid, plus the full per-question sequence on a real
// evidence record. Records come from GET /api/evidence when the server verifies a ledger,
// otherwise from the byte-identical fixture copy of Max's committed ledger.

import { mount, playSequence, renderCard } from "./heater.js";
import { cardModel, parseJsonl } from "./heater-model.js";

const CELLS = [
  ["idle", "Waiting on the take", "Bounces on his toes, ball under the arm, flames low."],
  ["listening", "Listening", "Leans in, claw at his ear, visor dims; flames follow the mic level."],
  ["thinking", "Thinking", "Spins the ball on one finger, visor scans, sparks rise."],
  ["hot_take", "Hot take", "Jabs at you, flames 20% taller, mouth follows speech."],
  ["vindicated", "Vindicated", "SURVIVED_PROTOCOL: arms up, white-hot crest, ball slammed."],
  ["cooled", "Cooled", "NOT_SUPPORTED: flames die shard by shard, smoke, shoulders drop."],
  ["unsure", "Unsure", "INSUFFICIENT_EVIDENCE: uneven flicker, visor blinks, shrug."],
  ["blocked", "Blocked", "BLOCKED / DATA_INVALID: arms crossed, steam, flames frozen."],
  ["heat_check", "Heat check", "The Ref scans him: sliced glitch with violet and teal fringes."],
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

async function buildGrid() {
  const grid = document.getElementById("grid");
  for (const [state, title, desc] of CELLS) {
    const cell = document.createElement("article");
    cell.className = "cell";
    cell.innerHTML = `<div class="stage"><div></div></div><h3></h3><p></p>`;
    cell.querySelector("h3").textContent = title;
    const code = document.createElement("code");
    code.textContent = state;
    cell.querySelector("h3").append(code);
    cell.querySelector("p").textContent = desc;
    grid.append(cell);
    const h = await mount(cell.querySelector(".stage > div"), { state, hold: true });
    if (ONE_SHOT.has(state)) setInterval(() => h.setState(state, { restart: true }), state === "cooled" ? 4200 : 3000);
  }
}

async function buildSequence() {
  const heater = await mount(document.getElementById("seq-heater"), { state: "idle" });
  const card = document.getElementById("seq-card");
  renderCard(card, null);
  const sel = document.getElementById("rec");
  const phaseEl = document.getElementById("phase");
  const srcEl = document.getElementById("src");
  let ledger;
  try {
    ledger = await loadLedger();
  } catch (e) {
    phaseEl.textContent = `No evidence record available: ${e.message}`;
    document.getElementById("go").disabled = true;
    return;
  }
  srcEl.textContent = `Source: ${ledger.source}`;
  ledger.entries.forEach((e, i) => {
    const o = document.createElement("option");
    o.value = String(i);
    o.textContent = `${e.identity.claim.claim_id} · ${e.identity.decision}`;
    sel.append(o);
  });
  const form = document.getElementById("ask");
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const go = document.getElementById("go");
    go.disabled = true;
    const entry = ledger.entries[Number(sel.value)];
    try {
      await playSequence(heater, card, async () => ({ entry, verified: ledger.verified }), {
        voiceOn: document.getElementById("voice").checked,
        mic: document.getElementById("mic").checked,
        onPhase: (p) => { phaseEl.textContent = `Phase: ${p}`; },
      });
    } finally {
      go.disabled = false;
    }
  });
}

// ?shot=<state> renders one large rig for screenshots; ?shot=card&claim=HH-K2 renders the
// speech card in its verdict phase.
async function shotMode(params) {
  document.body.classList.add("shot");
  const box = document.createElement("div");
  box.id = "shot";
  document.body.append(box);
  const which = params.get("shot");
  if (which === "card") {
    const ledger = await loadLedger();
    const entry = ledger.entries.find((e) => e.identity.claim.claim_id === params.get("claim")) || ledger.entries[0];
    const model = cardModel(entry, { verified: ledger.verified });
    const wrap = document.createElement("div");
    wrap.id = "shot-card";
    box.style.width = "460px";
    box.append(wrap);
    const stage = document.createElement("div");
    stage.style.width = "150px";
    box.prepend(stage);
    renderCard(wrap, model, { phase: "verdict" });
    const h = await mount(stage, { state: model.endState, hold: true });
    h.setState(model.endState);
  } else {
    const label = document.createElement("p");
    label.className = "label";
    label.textContent = which.toUpperCase();
    const stage = document.createElement("div");
    box.append(label, stage);
    await mount(stage, { state: which, hold: true });
    if (params.get("freeze") === "1") {
      stage.classList.add("h-freeze");
      label.textContent += " (glitch frame 2 held for capture)";
    }
  }
  document.body.dataset.ready = "1";
}

const params = new URLSearchParams(location.search);
if (params.has("shot")) {
  shotMode(params);
} else {
  buildSequence();
  buildGrid();
}
