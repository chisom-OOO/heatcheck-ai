// Tamper test UI (Experience, 8 Nov 2026) against Max's endpoints (heatcheck/api/tamper.py, 547111f).
// Mocks only, no browser; Max runs the real end-to-end with demo.cmd.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import {
  MOCK_FLIP, NOT_IN_REPLY, TAMPER_DEFAULT_VISIBLE, TAMPER_EVENTS_URL, TAMPER_FLIP_URL, TAMPER_RESTORE_URL, TAMPER_TARGET,
  eventRows, flipView, ledgerRowView, mockTamperFetch, postTamper, restoreView, tamperMode, tamperRefLine,
} from "../web/tamper/tamper-model.js";
import { renderTamper, setTamperStatus } from "../web/tamper/tamper.js";
import { DEFAULT_PERSONALITY, stampFor, stateForDecision } from "../web/heater/heater-model.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const WEB = join(HERE, "..", "web");
const JS = readFileSync(join(WEB, "demo.js"), "utf8");
const HTML = readFileSync(join(WEB, "demo.html"), "utf8");
const CSS = readFileSync(join(WEB, "demo.css"), "utf8");
const PERSONALITY = JSON.parse(readFileSync(join(WEB, "heater", "heater_personality.json"), "utf8"));
const API_DOC = readFileSync(join(HERE, "..", "..", "..", "docs", "DIALOGUE_API.md"), "utf8");

// Max's documented example reply (docs/DIALOGUE_API.md, "A real run on the committed file")
const FLIP = JSON.parse(API_DOC.match(/\{"offset": 24585[^`]*?\}/s)[0]);
const EVENTS = { events: [
  { evidence_id: "1".repeat(64), kind: "TAMPER_ATTEMPT", at_utc: "2026-11-08T07:30:00.000000Z", line: 5, offset: 24585,
    validator_message: "ledger line 5: identity hash mismatch (tampered)", verdict: "DATA_INVALID" },
  { evidence_id: FLIP.ledger_event_id, kind: "TAMPER_ATTEMPT", at_utc: "2026-11-08T07:35:00.000000Z", line: 5, offset: 24585,
    validator_message: FLIP.error, verdict: "DATA_INVALID" },
] };

// ---- minimal DOM
class El {
  constructor(tag) { this.tagName = tag.toUpperCase(); this.children = []; this.className = ""; this._text = ""; this.cls = new Set(); }
  get classList() { const s = this; return { toggle: (c, on) => { if (on) s.cls.add(c); else s.cls.delete(c); }, contains: (c) => s.cls.has(c) || s.className.split(" ").includes(c) }; }
  append(...k) { this.children.push(...k); }
  replaceChildren(...k) { this.children = k; }
  set textContent(t) { this._text = String(t); this.children = []; }
  get textContent() { return this._text + this.children.map((c) => c.textContent).join(""); }
  all(pred) { return this.children.flatMap((c) => [...(pred(c) ? [c] : []), ...c.all(pred)]); }
  querySelector(sel) { return this.all((e) => sel.startsWith(".") && e.className.split(" ").includes(sel.slice(1)))[0] || null; }
}
globalThis.document = { createElement: (t) => new El(t) };
const byClass = (root, c) => root.all((e) => e.className.split(" ").includes(c));
const byTag = (root, t) => root.all((e) => e.tagName === t.toUpperCase());

// ---- visibility
test("the button is hidden by default; ?tamper=1 shows it; ?tamper=mock is MOCK", () => {
  const P = (q) => new URLSearchParams(q);
  assert.equal(TAMPER_DEFAULT_VISIBLE, false);
  assert.equal(tamperMode(P("")), "off");
  assert.equal(tamperMode(P("tamper=1")), "live");
  assert.equal(tamperMode(P("tamper=0")), "off");
  assert.equal(tamperMode(P("tamper=mock")), "mock");
  assert.match(HTML, /<button type="button" class="tamper-btn" id="btn-tamper" hidden>Corrupt one byte<\/button>/);
  assert.match(HTML, /id="btn-restore" hidden>Restore the byte</);
  assert.match(JS, /ui\.tamperBtn\.hidden = TAMPER === "off";/);
  assert.match(CSS, /\.tamper-btn \{ color: #fff; background: #D7263D;/, "the button is red");
});

test("the page calls Max's three routes, relative, and the page server forwards /api/tamper/*", () => {
  assert.equal(TAMPER_FLIP_URL, "/api/tamper/flip");
  assert.equal(TAMPER_RESTORE_URL, "/api/tamper/restore");
  assert.equal(TAMPER_EVENTS_URL, "/api/tamper/events");
  for (const r of ["POST /api/tamper/flip", "POST /api/tamper/restore", "GET /api/tamper/events"]) assert.ok(API_DOC.includes(r), r);
  const app = readFileSync(join(HERE, "..", "server", "app.py"), "utf8");
  assert.match(app, /MAX_ENDPOINTS = \{[^}]*"tamper"/);
});

// ---- the flip reply
test("Max's flip reply shows file, line, offset, expected, actual and the validator error", () => {
  const v = flipView(FLIP);
  assert.equal(v.ok, true);
  assert.equal(v.caught, true);
  assert.deepEqual(v.rows, [
    ["File", TAMPER_TARGET], ["Line", "5"], ["Offset", "24,585 (0x6009)"], ["Expected", "0x53 'S'"], ["Actual", "0x52 'R'"],
    ["Validator error", "ledger line 5: identity hash mismatch (tampered)"],
  ]);
  assert.equal(v.eventId, FLIP.ledger_event_id);
  assert.match(TAMPER_TARGET, /^evidence\/evidence\.jsonl \(scratch copy; the committed file is only read\)$/);
});

test("missing fields say so; nothing is filled in", () => {
  const v = flipView({ offset: 7 });
  assert.equal(v.ok, true);
  assert.deepEqual(v.rows.slice(1).map(([, x]) => x), ["7 (0x7)", NOT_IN_REPLY, NOT_IN_REPLY, NOT_IN_REPLY]);
  assert.equal(v.caught, false, "no DATA_INVALID in the reply: no stamp");
  assert.match(tamperRefLine(v, PERSONALITY), /did not report DATA_INVALID/);
});

test("Max's error replies: rate limit, demo off, and NOT_DETECTED said loudly, never as a pass", () => {
  const rl = flipView({ error: "RATE_LIMITED", message: "one flip per 5 s" }, { httpStatus: 429 });
  assert.equal(rl.ok, false);
  assert.match(rl.problem, /HTTP 429: one flip per 5 seconds; wait a moment/);
  assert.match(flipView({ error: "TAMPER_OFF", message: "x" }, { httpStatus: 503 }).problem, /HTTP 503: the tamper demo is off on this server/);
  const nd = flipView({ error: "NOT_DETECTED", message: "the ledger reader accepted the tampered copy" }, { httpStatus: 500 });
  assert.equal(nd.ok, false);
  assert.equal(nd.notDetected, true);
  assert.match(nd.problem, /THE LEDGER READER ACCEPTED THE TAMPERED COPY/);
  assert.equal(tamperRefLine(nd, PERSONALITY), "The check failed: a byte was flipped and the ledger reader accepted it. Don't trust a ruling until this is fixed.");
  const root = new El("section");
  renderTamper(root, nd);
  assert.match(byClass(root, "tamper-alarm")[0].textContent, /^CHECK FAILED: /);
  assert.match(JS, /ui\.stamp\.textContent = "CHECK FAILED";/);
});

test("no endpoint or a network error: nothing flipped, no values, no stamp", async () => {
  assert.equal(flipView({ error: "NO_ROUTE", message: "POST /api/tamper/flip" }, { httpStatus: 404 }).problem,
    "the server did not report a flipped byte (HTTP 404: POST /api/tamper/flip)");
  const down = await postTamper(TAMPER_FLIP_URL, async () => { throw new TypeError("Failed to fetch"); });
  assert.deepEqual(down, { status: 0, body: { message: "Failed to fetch" } });
  const v = flipView(down.body, { httpStatus: down.status });
  assert.equal(v.ok, false);
  assert.equal(tamperRefLine(v, PERSONALITY), "Can't run the tamper test: the server did not report a flipped byte (HTTP 0: Failed to fetch).");
});

test("the Ref words a caught flip in the personality's DATA_INVALID line; the stamp is DATA INVALID", () => {
  assert.equal(tamperRefLine(flipView(FLIP), PERSONALITY), "No ruling. The data failed its checks: ledger line 5: identity hash mismatch (tampered).");
  assert.deepEqual(stampFor("DATA_INVALID", PERSONALITY), { text: "DATA INVALID", kind: "blocked" });
  assert.equal(stateForDecision("DATA_INVALID"), "blocked");
  assert.ok(DEFAULT_PERSONALITY.ref_templates.DATA_INVALID);
});

// ---- the new ledger row
test("the new row is the TAMPER_ATTEMPT event whose id is the flip's ledger_event_id", () => {
  const r = eventRows(EVENTS, FLIP.ledger_event_id);
  assert.equal(r.found, true);
  assert.equal(r.row.fullId, FLIP.ledger_event_id);
  assert.deepEqual([r.row.claim, r.row.decision, r.row.reason], ["TAMPER_ATTEMPT", "DATA_INVALID", FLIP.error]);
  assert.deepEqual(r.recent.map((x) => x.id), ["111111111111"], "earlier events above it");
  assert.equal(eventRows(EVENTS, "nope").found, false);
  assert.equal(eventRows({ events: [] }, FLIP.ledger_event_id).row, null);
  assert.equal(ledgerRowView({}), null);
});

test("the panel lists the facts, then the tamper ledger with the new row marked last", () => {
  const root = new El("section");
  const r = eventRows(EVENTS, FLIP.ledger_event_id);
  renderTamper(root, flipView(FLIP), { recent: r.recent, row: r.row, status: "One byte is corrupted." });
  assert.deepEqual(byTag(root, "dt").map((e) => e.textContent), ["File", "Line", "Offset", "Expected", "Actual", "Validator error"]);
  assert.equal(byClass(root, "tamper-error")[0].textContent, FLIP.error);
  assert.deepEqual(byTag(root, "th").map((e) => e.textContent), ["Entry", "Verdict", "Evidence id", "Validator message"]);
  const rows = byTag(root, "tbody")[0].children;
  assert.equal(rows.length, 2);
  assert.equal(rows[0].className, "");
  assert.equal(rows[1].className, "tamper-new");
  assert.ok(rows[1].textContent.startsWith(`TAMPER_ATTEMPTDATA_INVALID${FLIP.ledger_event_id.slice(0, 12)}`));
  assert.equal(byClass(root, "tamper-mock").length, 0, "a live reply has no MOCK label");
  setTamperStatus(root, "Restored.", true);
  assert.ok(byClass(root, "tamper-status")[0].classList.contains("good"));
});

test("when the events list has no new row, the panel says why instead of inventing one", () => {
  const root = new El("section");
  renderTamper(root, flipView(FLIP), { rowNote: "The tamper ledger did not load (HTTP 503: TAMPER_OFF)." });
  assert.equal(byClass(root, "tamper-new").length, 0);
  assert.equal(byClass(root, "tamper-problem")[0].textContent, "The tamper ledger did not load (HTTP 503: TAMPER_OFF).");
});

test("a failed flip draws only the problem: no facts, no ledger", () => {
  const root = new El("section");
  renderTamper(root, flipView(null, { httpStatus: 404 }));
  assert.equal(byTag(root, "dl").length, 0);
  assert.equal(byTag(root, "table").length, 0);
  assert.match(byClass(root, "tamper-problem")[0].textContent, /^Nothing was flipped: /);
});

// ---- restore
test("restore: Max's {restored: true} says the scratch copy is gone and the committed ledger never changed", async () => {
  assert.deepEqual(restoreView({ restored: true }),
    { ok: true, text: "Restored: the corrupted copy is deleted. The committed ledger was only read and never changed." });
  assert.deepEqual(restoreView({ error: "TAMPER_OFF", message: "off" }, { httpStatus: 503 }),
    { ok: false, text: "Restore failed (HTTP 503): off. The file may still be corrupted." });
  const f = mockTamperFetch();
  assert.equal((await postTamper(TAMPER_FLIP_URL, f)).status, 200);
  const r = await postTamper(TAMPER_RESTORE_URL, f);
  assert.equal(restoreView(r.body, { httpStatus: r.status }).ok, true);
});

test("postTamper POSTs flip/restore with no body and GETs the events", async () => {
  const calls = [];
  const f = async (url, init) => { calls.push([url, init.method]); return { status: 200, json: async () => ({}) }; };
  await postTamper(TAMPER_FLIP_URL, f);
  await postTamper(TAMPER_EVENTS_URL, f, "GET");
  assert.deepEqual(calls, [["/api/tamper/flip", "POST"], ["/api/tamper/events", "GET"]]);
  assert.match(JS, /postTamper\(TAMPER_EVENTS_URL, tamperFetch\(\), "GET"\)/);
});

// ---- mock mode is labelled
test("?tamper=mock: same shape as Max's reply, MOCK in every text value, and the panel says no file changed", async () => {
  const f = mockTamperFetch();
  const r = await postTamper(TAMPER_FLIP_URL, f);
  assert.deepEqual(Object.keys(FLIP).every((k) => k in r.body), true);
  const v = flipView(r.body, { httpStatus: r.status, mock: true });
  for (const [k, x] of v.rows) if (k === "File" || k === "Validator error") assert.match(x, /^MOCK: /);
  const ev = eventRows((await postTamper(TAMPER_EVENTS_URL, f, "GET")).body, v.eventId);
  assert.equal(ev.found, true);
  const root = new El("section");
  renderTamper(root, v, { row: ev.row });
  assert.equal(byClass(root, "tamper-mock")[0].textContent, "MOCK REPLY: no request was sent and no file was changed");
  assert.equal(MOCK_FLIP.mock, true);
  assert.match(JS, /if \(TAMPER === "mock"\) ui\.tamperBtn\.textContent = "Corrupt one byte \(MOCK\)";/);
});

// ---- page wiring (source order; the browser run is Max's, with demo.cmd)
test("runTamper: flip, events, Ref line, then the stamp only for a caught flip; Restore appears once flipped", () => {
  const i = JS.indexOf("async function tamperTurn(");
  const src = JS.slice(i, JS.indexOf("\nconst runRestore = ", i));
  const at = (s) => { const k = src.indexOf(s); assert.ok(k >= 0, s); return k; };
  assert.ok(at("postTamper(TAMPER_FLIP_URL") < at("postTamper(TAMPER_EVENTS_URL"));
  assert.ok(at("postTamper(TAMPER_EVENTS_URL") < at("renderTamper(ui.tamper, view"));
  assert.ok(at("if (view.ok) { state.tampered = true; ui.restoreBtn.hidden = false; }") < at("await h.speak(refLine, \"ref\""));
  assert.ok(at("await h.speak(refLine, \"ref\"") < at("if (view.ok && view.caught) {"));
  assert.ok(at("if (view.ok && view.caught) {") < at('stampFor("DATA_INVALID", state.personality)'));
  assert.ok(at('stampFor("DATA_INVALID", state.personality)') < at("} else if (view.notDetected) {"));
  // one flip at a time until restored (busyTurn refuses a second turn while one runs)
  assert.match(JS, /const runTamper = \(\) => \(state\.tampered \? undefined : busyTurn\("tamper", tamperTurn\)\);/);
  assert.match(JS, /const runRestore = \(\) => \(state\.tampered \? busyTurn\("restore", restoreTurn\) : undefined\);/);
  const r = JS.slice(JS.indexOf("async function restoreTurn("), JS.indexOf("\n}\n", JS.indexOf("async function restoreTurn(")));
  assert.match(r, /postTamper\(TAMPER_RESTORE_URL/);
  assert.match(r, /if \(view\.ok\) \{[^}]*state\.tampered = false;\s*ui\.restoreBtn\.hidden = true;/);
  assert.match(JS, /ui\.tamperBtn\.disabled = b \|\| Boolean\(state\.tampered\);/);
});
