// Safer gambling on the demo page (Experience, 8 Nov 2026). Mocks only, no browser: the footer,
// the board header and the first-ask notice all show Max's responsible_use.json text, unchanged.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import { FIRST_ASK_KEY, RESPONSIBLE_URL, firstTimeThisSession, loadResponsibleUse } from "../web/responsible.js";
import { renderBoard } from "../web/market/board.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const WEB = join(HERE, "..", "web");
const RU = JSON.parse(readFileSync(join(WEB, "responsible_use.json"), "utf8"));
const HTML = readFileSync(join(WEB, "demo.html"), "utf8");
const JS = readFileSync(join(WEB, "demo.js"), "utf8");
const CSS = readFileSync(join(WEB, "demo.css"), "utf8");

// a minimal DOM stand-in, as in board.test.mjs
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

const row = { game_id: "nba:0022600100", home_team: "Cleveland Cavaliers", away_team: "New York Knicks",
  tip_utc: "2026-11-08T00:30:00Z", p_home_win: "0.662" };
const okBoard = { status: "OK", isSample: false, forecast: { model: "B1", inputs_used: [] },
  games: [{ row, mapping: null, resp: null, error: "No market price was captured for this game", pending: false }] };

// ---- the static footer is Max's short text, word for word, and always visible
test("demo.html footer carries Max's short text exactly, outside every hidden section", () => {
  const m = /<footer class="rg-footer"[^>]*>\s*<p id="rg-short">([^<]*)<\/p>\s*<\/footer>/.exec(HTML);
  assert.ok(m, "footer with #rg-short");
  assert.equal(m[1], RU.short);
  assert.ok(!/<footer[^>]*\bhidden\b/.test(HTML), "the footer is never hidden");
  assert.ok(HTML.indexOf("<footer") > HTML.indexOf("</form>") && HTML.indexOf("<footer") < HTML.indexOf("</main>"),
    "a direct part of the stage, after the question box");
  assert.match(CSS, /grid-template-areas: "hero talk" "ask ask" "foot foot"/, "wide layout has a footer row");
  assert.match(CSS, /grid-template-areas: "hero" "talk" "ask" "foot"/, "narrow layout has a footer row");
  assert.ok(!/<a\s/i.test(m[0]), "no link in the footer");
});

// ---- loading Max's file
const res = (status, body) => ({ ok: status >= 200 && status < 300, status, json: async () => body });

test("loadResponsibleUse returns Max's short and full text, unchanged", async () => {
  const calls = [];
  const r = await loadResponsibleUse({ fetchImpl: async (u) => { calls.push(u); return res(200, RU); } });
  assert.deepEqual(r, { short: RU.short, full: RU.full });
  assert.deepEqual(calls, [RESPONSIBLE_URL]);
  assert.equal(RESPONSIBLE_URL, "responsible_use.json", "relative: same origin, next to demo.html");
});

test("loadResponsibleUse gives null on a missing file, a bad shape or a network error (static footer stands)", async () => {
  assert.equal(await loadResponsibleUse({ fetchImpl: async () => res(404, null) }), null);
  assert.equal(await loadResponsibleUse({ fetchImpl: async () => res(200, { short: "x" }) }), null);
  assert.equal(await loadResponsibleUse({ fetchImpl: async () => res(200, { short: " ", full: "y" }) }), null);
  assert.equal(await loadResponsibleUse({ fetchImpl: async () => { throw new Error("offline"); } }), null);
});

// ---- once per session
test("firstTimeThisSession: true once, then false; also when storage is missing or throws", () => {
  const mem = new Map();
  const store = { getItem: (k) => mem.get(k) ?? null, setItem: (k, v) => mem.set(k, v) };
  assert.equal(firstTimeThisSession(store, "t1"), true);
  assert.equal(mem.get("t1"), "1");
  assert.equal(firstTimeThisSession(store, "t1"), false);
  const seen = { getItem: () => "1", setItem: () => {} };   // shown earlier in this browser session
  assert.equal(firstTimeThisSession(seen, "t2"), false);
  const broken = { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); } };
  assert.equal(firstTimeThisSession(broken, "t3"), true);
  assert.equal(firstTimeThisSession(broken, "t3"), false, "memory keeps it to once per page view");
  assert.equal(firstTimeThisSession(null, "t4"), true);
  assert.equal(firstTimeThisSession(null, "t4"), false);
  assert.equal(FIRST_ASK_KEY, "heatcheck.responsible-use.shown");
});

// ---- board header
test("the board header shows the full notice above the cards when prices are shown", () => {
  const root = new El("section");
  renderBoard(root, okBoard, { onAsk: () => {}, notice: RU.full });
  const head = byClass(root, "board-head")[0];
  const n = byClass(head, "board-notice");
  assert.equal(n.length, 1);
  assert.equal(n[0].textContent, RU.full);
  assert.equal(n[0].attrs.role, "note");
  assert.ok(root.children.indexOf(head) < root.children.findIndex((c) => c.className === "board-grid"), "before the cards");
});

test("no notice element without text, and none on the board's error view", () => {
  const root = new El("section");
  renderBoard(root, okBoard, { onAsk: () => {} });
  assert.equal(byClass(root, "board-notice").length, 0);
  const err = new El("section");
  renderBoard(err, { status: "UNAVAILABLE", reason: "Max's server is not answering", games: [] }, { notice: RU.full });
  assert.equal(byClass(err, "board-notice").length, 0, "no prices shown, so no notice");
});

// ---- the page wiring (source checks: the browser run is Max's, with demo.cmd)
const body = (name) => {
  const i = JS.indexOf(`async function ${name}(`);
  assert.ok(i >= 0, name);
  const rest = JS.slice(i + 10);
  const next = rest.search(/\n(?:async function|function|const|let|\/\/ -{10}) /);  // next top-level item
  return JS.slice(i, next < 0 ? undefined : i + 10 + next);
};

test("the first market Ask, card what-if or own scenario shows the notice before Heater speaks", () => {
  for (const name of ["askMarket", "askScenario", "runScenario"]) {
    const src = body(name);
    const at = src.indexOf("showFirstAskNotice()");
    assert.ok(at > 0, `${name} calls showFirstAskNotice`);
    assert.ok(at > src.indexOf("reset();"), `${name}: after reset(), so it is not hidden again`);
    const take = src.indexOf("ui.take.textContent");
    if (take >= 0) assert.ok(at < take, `${name}: before Heater's first line`);
  }
  for (const name of ["ask", "askIdea"]) assert.ok(!body(name).includes("showFirstAskNotice"), `${name} is not a market flow`);
  assert.match(JS, /function showFirstAskNotice\(\) \{\s*if \(!firstTimeThisSession\(sessionStore\(\)\)\) return;/);
  assert.match(JS, /ui\.rgFirstText\.textContent = responsibleFull\(\);/);
  assert.match(HTML, /<aside class="rg-first" id="rg-first" hidden aria-label="Responsible use">/);
  assert.match(JS, /ui\.rgFirstOk\.addEventListener\("click", \(\) => \{ ui\.rgFirst\.hidden = true; \}\);/);
});

test("the page reads Max's file at start, updates the footer from it, and passes the full text to the board", () => {
  assert.match(JS, /import \{ firstTimeThisSession, loadResponsibleUse \} from "\.\/responsible\.js";/);
  assert.match(JS, /state\.responsibleLoad = loadResponsibleUse\(\)\.then\(\(r\) => \{\s*state\.responsible = r;\s*if \(r\) ui\.rgShort\.textContent = r\.short;/);
  assert.match(JS, /const responsibleFull = \(\) => state\.responsible\?\.full \|\| ui\.rgShort\.textContent;/);
  assert.match(JS, /const boardHandlers = \(\) => \(\{[\s\S]*?notice: responsibleFull\(\),\s*\}\);/);
  const load = JS.slice(JS.indexOf("async function loadBoardView("), JS.indexOf("function scenarioDetails("));
  assert.ok(load.indexOf("await state.responsibleLoad") < load.indexOf("renderBoard(ui.board, board, boardHandlers())"),
    "the board waits for the (local) file before drawing its header");
});

test("the notice wording lives only in Max's file and the static footer copy", () => {
  const phrase = "National Gambling Helpline";
  for (const f of ["demo.js", "responsible.js", join("market", "board.js")]) {
    assert.ok(!readFileSync(join(WEB, f), "utf8").includes(phrase), `${f} does not restate the text`);
  }
});
