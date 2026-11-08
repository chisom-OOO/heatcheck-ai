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
//
// Loading is in two steps so the board never sits on "Loading…" (rehearsal fix, 8 Nov 2026):
// loadForecast() reads the forecast and the mapping index within BOARD_TIMEOUT_MS and returns every
// card at once, pending; investigateGames() then runs the comparisons one at a time (Max's server
// takes one at a time anyway) and each card fills in as its answer arrives.

import { cardView, pickMapping } from "./board-model.js";
import { scenarioSlot } from "./scenario.js";

/** The board's own load (forecast + mapping index) must answer within this, or the board says why. */
export const BOARD_TIMEOUT_MS = 5000;
/** One comparison: Max's investigate can call the model for Heater's line (his doc: 30 s or more). */
export const INVESTIGATE_TIMEOUT_MS = 35000;

async function getJson(url, init = {}, timeoutMs = INVESTIGATE_TIMEOUT_MS) {
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

const secs = (ms) => `${Math.round(ms / 1000)} seconds`;

/** Step 1, at most ``timeoutMs``: the forecast and the mapping index, no comparison yet.
 *  Returns {status: OK|UNAVAILABLE, reason, isSample, forecast, games: [{row, mapping, resp, error, pending}]};
 *  a game with a mapping is ``pending`` until investigateGames() answers it. */
export async function loadForecast({ mappingsUrl = "/api/market-mappings", timeoutMs = BOARD_TIMEOUT_MS } = {}) {
  const started = Date.now();
  const left = () => Math.max(1, timeoutMs - (Date.now() - started));
  const down = (reason) => ({ status: "UNAVAILABLE", reason, games: [] });
  let fc;
  try {
    fc = await getJson("/api/live-forecast", {}, left());
  } catch (e) {
    return down(e.name === "AbortError" ? `Max's server did not answer within ${secs(timeoutMs)}`
      : `Max's server is not reachable (${e.message})`);
  }
  if (fc.status === 502 && fc.body?.error === "UPSTREAM_UNAVAILABLE") return down("Max's server is not answering");
  if (fc.status !== 200 || fc.body?.status !== "OK") {
    return down(fc.body?.reason || `live forecast: HTTP ${fc.status}`);
  }
  const forecast = fc.body.forecast;
  let mappings = [];
  let mappingNote = null;
  try {
    const m = await getJson(mappingsUrl, {}, left());
    if (m.status === 200 && Array.isArray(m.body?.mappings)) mappings = m.body.mappings;
    else mappingNote = "No market prices are configured";
  } catch {
    mappingNote = "No market prices are configured";
  }
  const games = forecast.games.map((row) => {
    const pick = mappingNote ? { mapping: null, note: mappingNote } : pickMapping(mappings, row.game_id);
    return { row, mapping: pick.mapping, resp: null, error: pick.note, pending: Boolean(pick.mapping) };
  });
  return { status: "OK", isSample: fc.body.is_sample, forecast, games };
}

/** What "Ask Heater about this game" sends: a non-empty message is what makes Max's server have the
 *  model voice the card (board load sends "" and gets his template, with no model call). */
export const ASK_MESSAGE = "Walk me through this game";

/** One POST /api/investigate for game ``g``. Returns {resp, error}; never throws. */
export async function investigateOne(g, message = "", { timeoutMs = INVESTIGATE_TIMEOUT_MS } = {}) {
  try {
    const r = await getJson("/api/investigate", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ game_id: g.row.game_id, mapping_id: g.mapping.mapping_id, message }),
    }, timeoutMs);
    if (r.status === 200 && r.body?.verdict) return { resp: r.body, error: null };
    return { resp: null, error: r.body?.error ? `The comparison could not be run (${r.body.error})` : `The comparison could not be run (HTTP ${r.status})` };
  } catch (e) {
    return { resp: null, error: `The comparison could not be run (${e.name === "AbortError" ? `no answer within ${secs(timeoutMs)}` : e.message})` };
  }
}

/** Step 2: one comparison at a time, in card order; ``onCard(game)`` after each answer. Never throws. */
export async function investigateGames(board, { log = () => {}, onCard = () => {}, timeoutMs = INVESTIGATE_TIMEOUT_MS } = {}) {
  for (const g of board.games || []) {
    if (!g.pending) continue;
    const { resp, error } = await investigateOne(g, "", { timeoutMs });
    if (resp) { g.resp = resp; g.error = null; } else g.error = error;
    g.pending = false;
    log(`investigate ${g.row.game_id}: ${g.resp ? `${g.resp.verdict} (${g.resp.evidence_id?.slice(0, 8) || "no entry"})` : g.error}`);
    try { onCard(g); } catch { /* a drawing problem never stops the other cards */ }
  }
  return board;
}

/** Both steps, waiting for every comparison: {status, reason, isSample, forecast, games: [{row, mapping, resp, error}]}. */
export async function loadBoard({ mappingsUrl = "/api/market-mappings", log = () => {} } = {}) {
  const board = await loadForecast({ mappingsUrl });
  if (board.status === "OK") await investigateGames(board, { log });
  return board;
}

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}

/** Fill one card element (new or already on the page) for game ``g``. ``slot`` is the card's
 *  "What if…?" block, kept across refills so an open scenario list stays open. */
function fillCard(card, g, board, { onAsk }, slot) {
  const v = cardView(g.row, { resp: g.resp, error: g.error, forecast: board.forecast, isSample: board.isSample, pending: g.pending });
  card.className = `mcard ${v.verdictKind}${v.sample ? " sample" : ""}`;
  if (card.dataset) card.dataset.gameId = g.row.game_id;
  if (card.setAttribute) card.setAttribute("aria-busy", String(Boolean(v.pending)));
  card.replaceChildren();
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
  for (const c of v.caveats || []) card.append(el("p", "mcard-caveat", c));
  if (v.canAsk && onAsk) {
    const b = el("button", "mcard-ask", "Ask Heater about this game");
    b.type = "button";
    b.addEventListener("click", () => onAsk(g));
    card.append(b);
  }
  if (slot) card.append(slot);
}

/** Render the board into ``root``. ``onAsk(game)`` runs Heater and the Ref on one card;
 *  ``onScenario(game, scenario, data)`` does the same for one preset scenario ("What if…?");
 *  ``onOwnScenario(game, text)`` takes the card's "Your own scenario" box into the free-text flow;
 *  ``onRetry()`` adds a "Try again" button when the board could not load.
 *  ``notice``: the full safer-gambling text (Max's responsible_use.json), shown in the header above
 *  the cards whenever prices are shown.
 *  Returns {update(game)}: redraws that game's card in place once its comparison has answered. */
export function renderBoard(root, board, { onAsk, onScenario, onOwnScenario, loadScenarios, onRetry, notice } = {}) {
  root.replaceChildren();
  const none = { update: () => false };
  const head = el("header", "board-head");
  head.append(el("h2", "board-title", "Tonight's games"));
  if (board.status !== "OK") {
    head.append(el("p", "board-note board-error", `No live forecast: ${board.reason}.`));
    if (onRetry) {
      const b = el("button", "mcard-ask board-retry", "Try again");
      b.type = "button";
      b.addEventListener("click", () => onRetry());
      head.append(b);
    }
    root.append(head);
    return none;
  }
  if (board.isSample) head.append(el("p", "board-sample", "SAMPLE forecast: the forecast values are invented, not a real forecast."));
  head.append(el("p", "board-note", "Forecast vs. the market's quoted bid and ask. Descriptive only, never a betting tip."));
  if (typeof notice === "string" && notice.trim()) {
    const n = el("p", "board-notice", notice);
    if (n.setAttribute) n.setAttribute("role", "note");
    head.append(n);
  }
  root.append(head);
  if (!board.games.length) {
    root.append(el("p", "board-note", "The forecast file lists no games."));
    return none;
  }
  const grid = el("div", "board-grid");
  const cards = new Map();
  for (const g of board.games) {
    const card = el("article", "mcard");
    const slot = onScenario
      ? scenarioSlot(g, { onAsk: onScenario, onOwn: onOwnScenario, ...(loadScenarios ? { load: loadScenarios } : {}) })
      : null;
    fillCard(card, g, board, { onAsk }, slot);
    cards.set(g, { card, slot });
    grid.append(card);
  }
  root.append(grid);
  return {
    update(g) {
      const c = cards.get(g);
      if (!c) return false;
      fillCard(c.card, g, board, { onAsk }, c.slot);
      return true;
    },
  };
}
