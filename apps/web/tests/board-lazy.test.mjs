// Run from apps/web:  node --test tests/board-lazy.test.mjs
//
// Rehearsal fix (8 Nov 2026): the board sat on "Loading tonight's games…" for ~15 s because the page
// waited for every POST /api/investigate (one per game, one at a time on Max's server, ~0.6 s each
// with no model call) before drawing anything. Now: nothing is fetched until the board is opened;
// opening it waits at most 5 s for the forecast, then draws every card (pending) and fills each one in
// as its comparison answers. Against a mock of Max's API (captured answers, as in board.test.mjs);
// no browser is used.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { mock, test } from "node:test";
import { fileURLToPath } from "node:url";

import * as B from "../web/market/board-model.js";
import { BOARD_TIMEOUT_MS, investigateGames, loadBoard, loadForecast, renderBoard } from "../web/market/board.js";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const REPO = join(ROOT, "..", "..");
const CAP = JSON.parse(readFileSync(join(ROOT, "tests", "fixtures", "max_api", "captures.json"), "utf8"));
const INDEX = JSON.parse(readFileSync(join(REPO, "data", "experience", "quotes", "20261107T222950Z", "board.mappings.json"), "utf8"));
const MAPPING_FIELDS = ["mapping_id", "game_id", "venue", "contract_id", "team_id", "label", "status", "two_sided"];
const DEMO = readFileSync(join(ROOT, "web", "demo.js"), "utf8");

/** fetch stand-in: Max's captured answers; ``hold`` delays /api/investigate until released. */
function mockFetch({ overrides = {}, hold = false } = {}) {
  const calls = [];
  const held = [];
  let inFlight = 0;
  let maxInFlight = 0;
  const answer = (url, init) => {
    const method = init.method || "GET";
    const req = init.body ? JSON.parse(init.body) : null;
    let status = 404, body = { error: "not found" };
    if (overrides[url]) ({ status, body } = overrides[url](req));
    else if (url === "/api/market-mappings") {
      status = 200;
      body = { format: INDEX.format, mappings: INDEX.mappings.map((m) => Object.fromEntries(MAPPING_FIELDS.map((k) => [k, m[k]]))) };
    } else {
      const hit = CAP.exchanges.find((e) => !e.test_forecast && e.method === method && e.path === url
        && JSON.stringify(e.request) === JSON.stringify(req));
      if (hit) ({ status, body } = hit);
    }
    return { status, ok: status < 400, json: async () => JSON.parse(JSON.stringify(body)) };
  };
  const f = async (url, init = {}) => {
    calls.push({ url, method: init.method || "GET" });
    assert.match(url, /^\/api\//, `the page asked for a non-relative URL: ${url}`);
    if (hold && url === "/api/investigate") {
      inFlight += 1;
      maxInFlight = Math.max(maxInFlight, inFlight);
      await new Promise((release) => held.push(release));
      inFlight -= 1;
    }
    return answer(url, init);
  };
  return { f, calls, held, maxInFlight: () => maxInFlight };
}

async function withFetch(m, fn) {
  const old = globalThis.fetch;
  globalThis.fetch = m.f;
  try { return await fn(); } finally { globalThis.fetch = old; }
}

const flush = () => new Promise((r) => setImmediate(r));

class El {
  constructor(tag) { this.tag = tag; this.children = []; this.className = ""; this._text = ""; this.listeners = {}; this.attrs = {}; this.dataset = {}; }
  set textContent(v) { this._text = String(v); this.children = []; }
  get textContent() { return this._text + this.children.map((c) => c.textContent).join(" "); }
  append(...xs) { this.children.push(...xs); }
  replaceChildren(...xs) { this.children = xs; this._text = ""; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return this.attrs[k] ?? null; }
  addEventListener(t, fn) { this.listeners[t] = fn; }
  all(pred, out = []) { if (pred(this)) out.push(this); this.children.forEach((c) => c.all?.(pred, out)); return out; }
}
globalThis.document = { createElement: (t) => new El(t) };
const byClass = (root, c) => root.all((e) => String(e.className).split(" ").includes(c));

test("opening the board asks only for the forecast and the mappings, then draws every card, pending", async () => {
  const m = mockFetch();
  const board = await withFetch(m, () => loadForecast());
  assert.deepEqual(m.calls.map((c) => c.url), ["/api/live-forecast", "/api/market-mappings"], "no comparison before the cards are drawn");
  assert.equal(board.status, "OK");
  assert.equal(board.games.length, 6);
  assert.ok(board.games.every((g) => g.pending && g.mapping && !g.resp));
  const root = new El("section");
  renderBoard(root, board, { onAsk: () => {}, onScenario: () => {} });
  const cards = byClass(root, "mcard");
  assert.equal(cards.length, 6);
  for (const c of cards) {
    assert.ok(c.textContent.includes(B.VERDICT_CHECKING), "a pending card says it is checking");
    assert.ok(!c.textContent.includes(B.VERDICT_CANT) && !c.textContent.includes(B.VERDICT_WORTH), "no verdict before Max's answer");
    assert.equal(byClass(c, "mcard-ask").filter((b) => b.textContent === "Ask Heater about this game").length, 0, "nothing to ask about yet");
    assert.equal(c.attrs["aria-busy"], "true");
    assert.ok(c.textContent.includes("SAMPLE"), "the SAMPLE label is there from the first draw");
  }
});

test("comparisons run one at a time in card order and fill each card in place as they answer", async () => {
  const m = mockFetch({ hold: true });
  const board = await withFetch(m, () => loadForecast());
  const root = new El("section");
  const view = renderBoard(root, board, { onAsk: () => {}, onScenario: () => {} });
  const cardsBefore = byClass(root, "mcard");
  const slotsBefore = cardsBefore.map((c) => byClass(c, "scen-wrap")[0]);
  const filled = [];
  const done = withFetch(m, () => investigateGames(board, { onCard: (g) => { filled.push(g.row.game_id); view.update(g); } }));
  for (let i = 0; i < 6; i += 1) {
    while (m.held.length === 0) await flush();
    assert.equal(filled.length, i, "a card fills only when its own answer arrives");
    const pendingNow = byClass(root, "mcard").filter((c) => c.textContent.includes(B.VERDICT_CHECKING)).length;
    assert.equal(pendingNow, 6 - i);
    m.held.shift()();
    await flush();
  }
  await done;
  assert.equal(m.maxInFlight(), 1, "never two comparisons at once (Max's server takes one at a time)");
  assert.deepEqual(filled, board.games.map((g) => g.row.game_id), "card order");
  const cardsAfter = byClass(root, "mcard");
  assert.deepEqual(cardsAfter, cardsBefore, "the same card elements, redrawn in place");
  assert.deepEqual(cardsAfter.map((c) => byClass(c, "scen-wrap")[0]), slotsBefore, "an open What if…? list is kept");
  for (const c of cardsAfter) {
    assert.ok(c.textContent.includes(B.VERDICT_CANT));
    assert.ok(!c.textContent.includes(B.VERDICT_CHECKING));
    assert.equal(byClass(c, "mcard-ask").filter((b) => b.textContent === "Ask Heater about this game").length, 1);
    assert.equal(c.attrs["aria-busy"], "false");
  }
});

test("loadBoard (both steps) still returns every comparison, as before", async () => {
  const m = mockFetch();
  const board = await withFetch(m, () => loadBoard());
  assert.deepEqual(m.calls.map((c) => c.url), ["/api/live-forecast", "/api/market-mappings", ...Array(6).fill("/api/investigate")]);
  assert.ok(board.games.every((g) => !g.pending && g.resp?.verdict === B.VERDICT_CANT));
});

test("the board says why after 5 s when Max's server does not answer, with a Try again button", async () => {
  assert.equal(BOARD_TIMEOUT_MS, 5000);
  mock.timers.enable({ apis: ["setTimeout", "Date"] });
  try {
    const hang = { f: (url, init = {}) => new Promise((_, reject) => {
      init.signal?.addEventListener("abort", () => reject(Object.assign(new Error("aborted"), { name: "AbortError" })));
    }) };
    let result = null;
    const p = withFetch(hang, () => loadForecast()).then((r) => { result = r; });
    await flush();
    mock.timers.tick(4999);
    await flush();
    assert.equal(result, null, "still waiting at 4.999 s");
    mock.timers.tick(1);
    await p;
    assert.equal(result.status, "UNAVAILABLE");
    assert.equal(result.reason, "Max's server did not answer within 5 seconds");
    const root = new El("section");
    let retried = 0;
    renderBoard(root, result, { onRetry: () => { retried += 1; } });
    assert.match(root.textContent, /No live forecast: Max's server did not answer within 5 seconds\./);
    const retry = byClass(root, "board-retry")[0];
    assert.equal(retry.textContent, "Try again");
    retry.listeners.click();
    assert.equal(retried, 1);
  } finally {
    mock.timers.reset();
  }
});

test("a server that is down, and a card whose comparison never answers, both say so plainly", async () => {
  const down = mockFetch({ overrides: { "/api/live-forecast": () => ({ status: 502, body: { error: "UPSTREAM_UNAVAILABLE",
    message: "Max's dialogue API at http://127.0.0.1:8770 did not answer (ConnectionRefusedError)" } }) } });
  const none = await withFetch(down, () => loadForecast());
  assert.deepEqual([none.status, none.reason], ["UNAVAILABLE", "Max's server is not answering"]);

  const m = mockFetch();
  const board = await withFetch(m, () => loadForecast());
  const first = board.games[0].row.game_id;
  const slow = { f: (url, init = {}) => (url === "/api/investigate" && JSON.parse(init.body).game_id === first
    ? new Promise((_, reject) => init.signal.addEventListener("abort", () => reject(Object.assign(new Error("aborted"), { name: "AbortError" }))))
    : m.f(url, init)) };
  await withFetch(slow, () => investigateGames(board, { timeoutMs: 20 }));
  assert.match(board.games[0].error, /^The comparison could not be run \(no answer within 0 seconds\)$/);
  assert.equal(B.cardView(board.games[0].row, { error: board.games[0].error, isSample: true }).verdict, B.VERDICT_CANT);
  assert.ok(board.games.slice(1).every((g) => g.resp?.verdict === B.VERDICT_CANT), "the other cards still answer");
});

/** The source of one top-level function in demo.js. */
function fnSource(name) {
  const start = DEMO.search(new RegExp(`^(async )?function ${name}\\(`, "m"));
  assert.ok(start >= 0, `demo.js has no function ${name}`);
  const rest = DEMO.slice(start + 1);
  const end = rest.search(/^(async function |function |const |let |\/\/ -{10})/m);
  return DEMO.slice(start, end < 0 ? undefined : start + 1 + end);
}

test("demo.js: the home view is drawn before any network wait; the board loads only when opened", () => {
  const main = fnSource("main");
  const firstAwait = main.indexOf("await ");
  assert.ok(main.indexOf('setView("talk")') >= 0 && main.indexOf('setView("talk")') < firstAwait, "home view before the first await");
  assert.ok(main.indexOf('toggleView("board", openBoard)') < firstAwait, "the board button works before Heater has loaded");
  assert.ok(!/await loadLedger\(\)/.test(main), "the ledger loads in the background");
  assert.ok(!/loadForecast|investigateGames|loadBoard/.test(main), "main fetches nothing for the board");
  assert.ok(/params\.get\("board"\) === "1"\) openBoard\(\)/.test(main), "only ?board=1 opens it at load");
  const load = fnSource("loadBoardView");
  assert.ok(/await loadForecast\(\)/.test(load));
  assert.ok(/\n\s+investigateGames\(board, \{[^\n]*\}\);/.test(load), "the comparisons are not awaited");
  assert.ok(/onRetry: \(\) => openBoard\(\)/.test(load), "a failed load offers Try again");
  const open = fnSource("openBoard");
  assert.ok(/if \(!state\.boardLoading\) state\.boardLoading = loadBoardView\(\)/.test(open), "opening twice never investigates twice");
  assert.ok(!/loadBoard\b/.test(DEMO.replace(/loadBoardView/g, "")), "demo.js no longer waits for the whole board");
});
