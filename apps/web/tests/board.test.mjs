// Run from apps/web:  node --test tests/board.test.mjs
//
// The demo page's market board and the home-advantage answer, against a mock of Max's API. The
// mock answers with responses captured from Max's real server code (tests/fixtures/max_api/
// captures.json, written by tools/capture_max_api.py), plus the UI server's own mapping index.
// fetch is replaced by the mock, and every URL the page asks for must be relative (/api/...).
// A small DOM stand-in records what renderBoard builds; no browser is used.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import * as H from "../web/heater/heater-model.js";
import { loadBoard, renderBoard } from "../web/market/board.js";
import * as B from "../web/market/board-model.js";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const REPO = join(ROOT, "..", "..");
const CAP = JSON.parse(readFileSync(join(ROOT, "tests", "fixtures", "max_api", "captures.json"), "utf8"));
const ex = (name) => CAP.exchanges.find((e) => e.name === name);
const INDEX = JSON.parse(readFileSync(join(REPO, "data", "experience", "quotes", "20261107T222950Z", "board.mappings.json"), "utf8"));
const MAPPING_FIELDS = ["mapping_id", "game_id", "venue", "contract_id", "team_id", "label", "status", "two_sided"];

/** fetch stand-in: Max's captured answers; /api/market-mappings as server/app.py serves it. */
function mockFetch({ overrides = {} } = {}) {
  const calls = [];
  const f = async (url, init = {}) => {
    calls.push({ url, method: init.method || "GET", body: init.body });
    assert.match(url, /^\/api\//, `the page asked for a non-relative URL: ${url}`);
    const method = init.method || "GET";
    const req = init.body ? JSON.parse(init.body) : null;
    let status = 404, body = { error: "not found" };
    if (overrides[url]) ({ status, body } = overrides[url](req));
    else if (url === "/api/market-mappings") {
      status = 200;
      body = { format: INDEX.format, run: INDEX.run, captured: INDEX.captured,
        is_sample_game_list: INDEX.forecast_input.is_sample,
        mappings: INDEX.mappings.map((m) => Object.fromEntries(MAPPING_FIELDS.map((k) => [k, m[k]]))) };
    } else {
      const hit = CAP.exchanges.find((e) => !e.test_forecast && e.method === method && e.path === url
        && JSON.stringify(e.request) === JSON.stringify(req));
      if (hit) ({ status, body } = hit);
    }
    return { status, ok: status < 400, json: async () => JSON.parse(JSON.stringify(body)) };
  };
  return { f, calls };
}

async function withFetch(mock, fn) {
  const old = globalThis.fetch;
  globalThis.fetch = mock.f;
  try { return await fn(); } finally { globalThis.fetch = old; }
}

// --- a minimal DOM stand-in for renderBoard (createElement, append, textContent, events) ---
class El {
  constructor(tag) { this.tag = tag; this.children = []; this.className = ""; this._text = ""; this.listeners = {}; this.type = ""; }
  set textContent(v) { this._text = String(v); this.children = []; }
  get textContent() { return this._text + this.children.map((c) => c.textContent).join(" "); }
  append(...xs) { this.children.push(...xs); }
  replaceChildren(...xs) { this.children = xs; this._text = ""; }
  addEventListener(t, fn) { this.listeners[t] = fn; }
  all(pred, out = []) { if (pred(this)) out.push(this); this.children.forEach((c) => c.all(pred, out)); return out; }
}
globalThis.document = { createElement: (t) => new El(t) };
const byClass = (root, c) => root.all((e) => e.className.split(" ").includes(c));

test("the board loads tonight's games through relative URLs only", async () => {
  const m = mockFetch();
  const board = await withFetch(m, () => loadBoard());
  assert.equal(board.status, "OK");
  assert.equal(board.isSample, true);
  assert.equal(board.games.length, 6);
  assert.deepEqual(m.calls.map((c) => c.url), ["/api/live-forecast", "/api/market-mappings",
    ...Array(6).fill("/api/investigate")]);
  for (const g of board.games) {
    assert.equal(g.mapping.venue, "POLYMARKET", "bids-only Kalshi books are never chosen");
    assert.equal(g.resp.verdict, B.VERDICT_CANT);
    const sent = JSON.parse(m.calls.find((c) => c.body && JSON.parse(c.body).game_id === g.row.game_id).body);
    assert.deepEqual(Object.keys(sent), ["game_id", "mapping_id", "message"], "exactly Max's request shape");
  }
});

test("each card shows forecast, price, difference, both timestamps and inputs; SAMPLE and Can't compare plainly", async () => {
  const board = await withFetch(mockFetch(), () => loadBoard());
  const atl = board.games.find((g) => g.row.game_id === "nba:0022600190");
  const v = B.cardView(atl.row, { resp: atl.resp, forecast: board.forecast, isSample: board.isSample });
  assert.equal(v.title, "Brooklyn Nets at Atlanta Hawks");
  assert.equal(v.forecast, "Atlanta Hawks 50.0% to win");
  assert.equal(v.forecastNote, "SAMPLE: invented value");
  assert.equal(v.price, "Polymarket: bid 71.0% · ask 72.0%");
  assert.equal(v.diff, "SAMPLE");
  assert.equal(v.cutoff, "Nov 7, 22:00 UTC");
  assert.equal(v.received, B.fmtUtc(atl.resp.quote.received_utc, { seconds: true }));
  assert.match(v.received, /^Nov 7, 22:29:5\d UTC$/);
  assert.equal(v.inputs, "Elo rating (home), Elo rating (away), home court");
  assert.equal(v.verdict, "Can't compare");
  assert.equal(v.why, "the forecast is a SAMPLE with made-up numbers");  // Polymarket mappings are VERIFIED by Max
  assert.equal(B.marketStamp(atl.resp).text, "SAMPLE");
  assert.equal(B.marketEndState(atl.resp), "blocked");
  assert.equal(B.marketRefPlain(atl.resp), "Can't compare: the forecast is a SAMPLE with made-up numbers.");
});

test("renderBoard draws a SAMPLE banner and six cards, all text via textContent", async () => {
  const board = await withFetch(mockFetch(), () => loadBoard());
  const root = new El("section");
  const asked = [];
  renderBoard(root, board, { onAsk: (g) => asked.push(g.row.game_id) });
  assert.equal(byClass(root, "board-sample").length, 1);
  assert.match(byClass(root, "board-sample")[0].textContent, /SAMPLE forecast/);
  const cards = byClass(root, "mcard");
  assert.equal(cards.length, 6);
  for (const c of cards) {
    const text = c.textContent;
    for (const label of ["Forecast", "Market", "Difference", "Forecast data to", "Price received", "Inputs used"]) {
      assert.ok(text.includes(label), `card lacks ${label}`);
    }
    assert.ok(text.includes("SAMPLE"));
    assert.ok(text.includes("Can't compare"));
    assert.equal(byClass(c, "mcard-sample").length, 1);
  }
  const btn = byClass(cards[0], "mcard-ask")[0];
  btn.listeners.click();
  assert.deepEqual(asked, ["nba:0022600190"]);
});

test("a real (non-sample) comparison renders as Worth investigating with the gap against bid/ask", () => {
  const resp = ex("investigate_test_forecast_pm").body;   // Max's answer for a TEST forecast, not a forecast
  assert.equal(resp.is_sample, false);
  const row = ex("live_forecast_sample").body.forecast.games.find((g) => g.game_id === resp.game.game_id);
  const v = B.cardView(row, { resp });
  assert.equal(v.verdict, "Worth investigating · Edge unverified");
  assert.equal(v.verdictKind, "worth");
  assert.equal(v.diff, "21.0 pts below the bid");
  assert.equal(v.sample, false);
  assert.equal(B.marketStamp(resp).text, "EDGE UNVERIFIED");
  assert.equal(B.marketEndState(resp), "thinking");
  assert.match(B.marketRefPlain(resp), /^Worth investigating, edge unverified\./);
});

test("Kalshi bids-only, unknown game and a down API all say Can't compare plainly", async () => {
  const kx = ex("investigate_kalshi").body;
  const row = ex("live_forecast_sample").body.forecast.games[0];
  const v = B.cardView(row, { resp: kx });
  assert.equal(v.verdict, "Can't compare");
  assert.ok(B.failedReasons(kx).includes("the market shows only one side, so there's no price you could actually get"));

  const lost = mockFetch({ overrides: { "/api/investigate": () => ex("investigate_unknown_game") } });
  const board = await withFetch(lost, () => loadBoard());
  assert.match(board.games[0].error, /The comparison could not be run \(nba:\d+ is not in the live forecast file\)/);
  assert.equal(B.cardView(board.games[0].row, { error: board.games[0].error, isSample: true }).verdict, "Can't compare");

  const down = mockFetch({ overrides: { "/api/live-forecast": () => ({ status: 502, body: { error: "UPSTREAM_UNAVAILABLE",
    message: "Max's dialogue API at http://127.0.0.1:8770 did not answer (ConnectionRefusedError)" } }) } });
  const none = await withFetch(down, () => loadBoard());
  assert.equal(none.status, "UNAVAILABLE");
  const root = new El("section");
  renderBoard(root, none);
  assert.match(root.textContent, /No live forecast/);
});

test("Heater's market line names inputs in plain words", () => {
  const r = ex("investigate_nba:0022600190_pm").body;
  const t = B.heaterPlain(r.heater_text, r.forecast.inputs_used);
  assert.ok(!/elo_rating_|home_court/.test(t), t);
  assert.ok(r.forecast.inputs_used.every((n) => r.heater_text.includes(n)) ? t.includes("Elo rating (home)") : true);
});

test("'Do home teams win more?' -> CONF-HA SURVIVED: vindicated pose, SURVIVED stamp, never-seen season", () => {
  const api = ex("dialogue_home_advantage").body;
  assert.equal(api.claim_id, "CONF-HA");
  assert.equal(api.verdict, "SURVIVED_PROTOCOL");
  assert.equal(api.lane, "CONFIRMATORY");
  const ledger = H.parseJsonl(readFileSync(join(REPO, "evidence", "evidence.jsonl"), "utf8"));
  const entry = ledger.find((e) => e.evidence_id === api.evidence_record_id);
  assert.ok(entry, "the API's evidence_record_id is in the committed ledger the page reads");
  assert.equal(entry.identity.decision, "SURVIVED_PROTOCOL");
  assert.equal(H.stateForDecision(entry.identity.decision), "vindicated");
  const personality = JSON.parse(readFileSync(join(ROOT, "web", "heater", "heater_personality.json"), "utf8"));
  assert.equal(H.stampFor(entry.identity.decision, personality).text, "SURVIVED");
  assert.equal(H.stampFor(entry.identity.decision, personality).kind, "survived");
  const ref = H.refPlain(entry, personality);
  assert.equal(ref.plain, true);
  assert.ok(ref.text.includes("tested on a season the system had never seen"), ref.text);
  assert.ok(ref.text.includes("1,224 games in 2024-25"), ref.text);
  assert.ok(ref.text.includes(`${H.fmtPct(entry.identity.result.detail.home_win_rate)}`), ref.text);
  assert.equal(H.routeQuestion("Do home teams win more?"), "CONF-HA");  // offline routing agrees
});
