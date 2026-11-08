// Market board: loads tonight's games from Max's API and renders one card per game.
//
//   GET  /api/live-forecast        Research's forecast file, re-validated by Max's server
//   GET  /api/market-mappings      which venue mapping ids exist (Experience's UI server;
//                                  ids, labels and statuses only, no prices)
//   POST /api/investigate          one card: forecast vs quote, checks and verdict
//
// All URLs are relative (same origin). The UI server passes live-forecast and investigate
// through to Max's server unchanged.
//
// Each investigate call is appended to Max's investigation ledger, so a page view investigates
// each game once and keeps the answer. All text is set with textContent.

import { cardView, pickMapping } from "./board-model.js";
import { scenarioSlot } from "./scenario.js";

async function getJson(url, init = {}, timeoutMs = 35000) {
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), timeoutMs);
  try {
    const r = await fetch(url, { ...init, signal: ctl.signal, headers: { Accept: "application/json", ...(init.headers || {}) } });
    let body = null;
    try { body = await r.json(); } catch { /* non-JSON */ }
    return { status: r.status, body };
  } finally {
    clearTimeout(t);
  }
}

/** Load the board: {status: OK|UNAVAILABLE, reason, isSample, forecast, games: [{row, mapping, resp, error}]}. */
export async function loadBoard({ mappingsUrl = "/api/market-mappings", log = () => {} } = {}) {
  let fc;
  try {
    fc = await getJson("/api/live-forecast");
  } catch (e) {
    return { status: "UNAVAILABLE", reason: `Max's API is not reachable (${e.name === "AbortError" ? "timeout" : e.message})`, games: [] };
  }
  if (fc.status !== 200 || fc.body?.status !== "OK") {
    return { status: "UNAVAILABLE", reason: fc.body?.reason || `live forecast: HTTP ${fc.status}`, games: [] };
  }
  const forecast = fc.body.forecast;
  let mappings = [];
  let mappingNote = null;
  try {
    const m = await getJson(mappingsUrl);
    if (m.status === 200 && Array.isArray(m.body?.mappings)) mappings = m.body.mappings;
    else mappingNote = "No market prices are configured";
  } catch {
    mappingNote = "No market prices are configured";
  }
  const games = [];
  for (const row of forecast.games) {
    const pick = mappingNote ? { mapping: null, note: mappingNote } : pickMapping(mappings, row.game_id);
    let resp = null;
    let error = pick.note;
    if (pick.mapping) {
      try {
        const r = await getJson("/api/investigate", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ game_id: row.game_id, mapping_id: pick.mapping.mapping_id, message: "" }),
        });
        if (r.status === 200 && r.body?.verdict) resp = r.body;
        else error = r.body?.error ? `The comparison could not be run (${r.body.error})` : `The comparison could not be run (HTTP ${r.status})`;
      } catch (e) {
        error = `The comparison could not be run (${e.name === "AbortError" ? "timeout" : e.message})`;
      }
      log(`investigate ${row.game_id}: ${resp ? `${resp.verdict} (${resp.evidence_id?.slice(0, 8) || "no entry"})` : error}`);
    }
    games.push({ row, mapping: pick.mapping, resp, error });
  }
  return { status: "OK", isSample: fc.body.is_sample, forecast, games };
}

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}

/** Render the board into ``root``. ``onAsk(game)`` runs Heater and the Ref on one card;
 *  ``onScenario(game, scenario, data)`` does the same for one scenario ("What if…?"). */
export function renderBoard(root, board, { onAsk, onScenario, loadScenarios } = {}) {
  root.replaceChildren();
  const head = el("header", "board-head");
  head.append(el("h2", "board-title", "Tonight's games"));
  if (board.status !== "OK") {
    head.append(el("p", "board-note", `No live forecast: ${board.reason}.`));
    root.append(head);
    return;
  }
  if (board.isSample) head.append(el("p", "board-sample", "SAMPLE forecast: the forecast values are invented, not a real forecast."));
  head.append(el("p", "board-note", "Forecast vs. the market's quoted bid and ask. Descriptive only, never a betting tip."));
  root.append(head);
  if (!board.games.length) {
    root.append(el("p", "board-note", "The forecast file lists no games."));
    return;
  }
  const grid = el("div", "board-grid");
  for (const g of board.games) {
    const v = cardView(g.row, { resp: g.resp, error: g.error, forecast: board.forecast, isSample: board.isSample });
    const card = el("article", `mcard ${v.verdictKind}${v.sample ? " sample" : ""}`);
    if (card.dataset) card.dataset.gameId = g.row.game_id;
    const top = el("header", "mcard-top");
    top.append(el("h3", "mcard-title", v.title), el("span", "mcard-tip", v.tip));
    card.append(top);
    if (v.sample) card.append(el("span", "mcard-sample", "SAMPLE"));
    if (v.recorded) card.append(el("span", "mcard-sample mcard-recorded", "RECORDED"));
    const dl = el("dl", "mcard-grid");
    const row = (k, val, cls = "") => { dl.append(el("dt", "", k), el("dd", cls, val)); };
    row("Forecast", v.forecast);
    if (v.sample) row("", v.forecastNote, "mcard-flag");
    row("Market", v.price);
    row("Difference", v.diff, "mcard-diff");
    row("Forecast data to", v.cutoff);
    row("Price received", v.received);
    row("Inputs used", v.inputs);
    card.append(dl);
    card.append(el("p", `mcard-verdict ${v.verdictKind}`, v.verdict), el("p", "mcard-why", v.why));
    if (v.canAsk && onAsk) {
      const b = el("button", "mcard-ask", "Ask Heater about this game");
      b.type = "button";
      b.addEventListener("click", () => onAsk(g));
      card.append(b);
    }
    if (onScenario) card.append(scenarioSlot(g, { onAsk: onScenario, ...(loadScenarios ? { load: loadScenarios } : {}) }));
    grid.append(card);
  }
  root.append(grid);
}
