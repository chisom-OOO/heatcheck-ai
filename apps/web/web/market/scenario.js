// Scenario view on a game card: "What if…?" loads GET /api/scenario?game_id=... (relative URL;
// the UI server passes it through to Max's server unchanged) and shows each scenario as the
// forecast now beside the scenario's estimate, the range as a bar, n and caveats under it, and an
// ESTIMATE label. All text is set with textContent; bar positions are set through the CSSOM.

import { readScenarios, scenarioView } from "./scenario-model.js";

/** Fetch and check the scenarios for one card. Never throws. */
export async function loadScenarios(gameId, { resp = null, timeoutMs = 35000 } = {}) {
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), timeoutMs);
  try {
    const r = await fetch(`/api/scenario?game_id=${encodeURIComponent(gameId)}`,
      { signal: ctl.signal, headers: { Accept: "application/json" } });
    let body = null;
    try { body = await r.json(); } catch { /* non-JSON */ }
    return readScenarios({ status: r.status, body }, { gameId, resp });
  } catch (e) {
    return { status: "UNAVAILABLE", reason: `Max's server is not answering (${e.name === "AbortError" ? "timeout" : e.message})`,
      scenarios: [], refused: [] };
  } finally {
    clearTimeout(t);
  }
}

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}

const at = (x) => `${(Math.max(0, Math.min(1, x)) * 100).toFixed(2)}%`;

/** The range bar on a 0–100% track: the range as a band, the scenario as a dot, the forecast now
 *  as a line. */
export function rangeBar(v) {
  const track = el("div", "scen-bar");
  track.setAttribute("role", "img");
  track.setAttribute("aria-label", v.barLabel);
  const band = el("span", "scen-range");
  band.style.left = at(v.bar.low);
  band.style.width = at(v.bar.high - v.bar.low);
  const base = el("span", "scen-base");
  base.style.left = at(v.bar.base);
  const dot = el("span", `scen-point ${v.dir}`);
  dot.style.left = at(v.bar.p);
  track.append(band, base, dot);
  const scale = el("div", "scen-scale");
  scale.append(el("span", "", "0%"), el("span", "scen-key", "band: range · line: now · dot: scenario"), el("span", "", "100%"));
  const wrap = el("div", "scen-barwrap");
  wrap.append(track, scale);
  return wrap;
}

/** Render a loadScenarios() result into ``slot``. ``onAsk(scenario, data)`` runs Heater and the Ref. */
export function renderScenarios(slot, data, { onAsk } = {}) {
  slot.replaceChildren();
  if (data.status !== "OK") {
    slot.append(el("p", "scen-note", `No scenarios: ${data.reason}.`));
    return;
  }
  if (!data.scenarios.length) slot.append(el("p", "scen-note", "No scenarios for this game."));
  for (const s of data.scenarios) {
    const v = scenarioView(s, data);
    const box = el("section", `scen${v.sample ? " sample" : ""}`);
    const head = el("header", "scen-head");
    head.append(el("h4", "scen-title", v.title), el("span", "scen-label", v.label));
    if (v.sample) head.append(el("span", "mcard-sample scen-sample", "SAMPLE"));
    box.append(head);
    const pair = el("div", "scen-pair");
    for (const [cell, cls] of [[v.baseline, "now"], [v.scenario, "if"]]) {
      const c = el("div", `scen-cell ${cls}`);
      c.append(el("span", "scen-cell-head", cell.head), el("span", "scen-cell-value", cell.value));
      pair.append(c);
    }
    const ch = el("div", `scen-change ${v.dir}`, v.change);
    pair.append(ch);
    box.append(pair, rangeBar(v));
    const meta = el("p", "scen-meta", `${v.range} · ${v.n}`);
    box.append(meta);
    if (v.sampleNote) box.append(el("p", "mcard-flag", v.sampleNote));
    const ul = el("ul", "scen-caveats");
    v.caveats.forEach((c) => ul.append(el("li", "", c)));
    box.append(el("p", "scen-caveats-head", "Caveats"), ul);
    if (onAsk) {
      const b = el("button", "mcard-ask scen-ask", "Ask Heater about this scenario");
      b.type = "button";
      b.addEventListener("click", () => onAsk(s, data));
      box.append(b);
    }
    slot.append(box);
  }
  for (const r of data.refused) slot.append(el("p", "scen-note", `Not shown "${r.text}": ${r.reason}.`));
  if (data.source) slot.append(el("p", "scen-source", `Source: ${data.source}`));
}

/** "Your own scenario": a free-text box on the card. The text goes, with this card's game id, into
 *  Max's free-text what-if flow (POST /api/scenario, read back, confirm, /api/scenario/estimate),
 *  so typed and preset scenarios share one backend. The box itself sends nothing. */
export function ownScenarioForm(g, onOwn) {
  const form = el("form", "scen-own");
  const id = `scen-own-${String(g.row.game_id).replace(/[^A-Za-z0-9_-]/g, "-")}`;
  const label = el("label", "scen-own-label", "Your own scenario");
  label.setAttribute("for", id);
  const input = el("input", "scen-own-input");
  input.id = id;
  input.type = "text";
  input.maxLength = 200;
  input.autocomplete = "off";
  input.placeholder = `e.g. What if ${g.row.home_team} were without their top scorer?`;
  const go = el("button", "mcard-ask scen-own-go", "Ask Heater");
  go.type = "submit";
  form.append(label, input, go);
  form.addEventListener("submit", (ev) => {
    ev?.preventDefault?.();
    const text = String(input.value || "").trim();
    if (!text) return;
    onOwn(g, text);
  });
  return form;
}

/** The card's "What if…?" button and the slot it fills. Loads once per card. ``onOwn(game, text)``
 *  adds the "Your own scenario" box under the preset list. */
export function scenarioSlot(g, { onAsk, onOwn, load = loadScenarios } = {}) {
  const wrap = el("div", "scen-wrap");
  const b = el("button", "mcard-whatif", "What if…?");
  b.type = "button";
  b.setAttribute("aria-expanded", "false");
  const slot = el("div", "scen-slot");
  slot.hidden = true;
  let loaded = null;
  b.addEventListener("click", async () => {
    const open = slot.hidden;
    slot.hidden = !open;
    b.setAttribute("aria-expanded", String(open));
    if (!open || loaded) return;
    slot.replaceChildren(el("p", "scen-note", "Loading scenarios…"));
    b.disabled = true;
    try {
      loaded = await load(g.row.game_id, { resp: g.resp });
      renderScenarios(slot, loaded, { onAsk: onAsk && ((s, data) => onAsk(g, s, data)) });
      if (onOwn) slot.append(ownScenarioForm(g, onOwn));
    } finally {
      b.disabled = false;
    }
  });
  wrap.append(b, slot);
  return wrap;
}
