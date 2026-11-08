// Tamper test UI (Experience, 8 Nov 2026). Mocks only, no browser; Max's endpoints have not landed.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import {
  MOCK_FLIP, NOT_IN_REPLY, TAMPER_DEFAULT_VISIBLE, TAMPER_FLIP_URL, TAMPER_RESTORE_URL, flipView, ledgerRowView,
  mockTamperFetch, postTamper, restoreView, tamperMode, tamperRefLine,
} from "../web/tamper/tamper-model.js";
import { renderTamper, setTamperStatus } from "../web/tamper/tamper.js";
import { DEFAULT_PERSONALITY, stampFor, stateForDecision } from "../web/heater/heater-model.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const WEB = join(HERE, "..", "web");
const JS = readFileSync(join(WEB, "demo.js"), "utf8");
const HTML = readFileSync(join(WEB, "demo.html"), "utf8");
const CSS = readFileSync(join(WEB, "demo.css"), "utf8");
const PERSONALITY = JSON.parse(readFileSync(join(WEB, "heater", "heater_personality.json"), "utf8"));

// a reply as Max's endpoint is proposed to send it (values made up for the test, not real data)
const FLIP = {
  file: "ledger/evidence.jsonl", offset: 1234, expected: "0x7b", actual: "0x7a",
  error: "ledger line 2: entry hash mismatch (tampered)", verdict: "DATA_INVALID",
  ledger_row: { evidence_id: "abcdef0123456789abcd", claim_id: "TAMPER-TEST", decision: "DATA_INVALID", reason: "entry hash mismatch" },
};

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
test("the button is hidden unless ?tamper=1 (Max's endpoints) or ?tamper=mock", () => {
  const P = (q) => new URLSearchParams(q);
  assert.equal(TAMPER_DEFAULT_VISIBLE, false, "hidden by default until Max's endpoint lands");
  assert.equal(tamperMode(P("")), "off");
  assert.equal(tamperMode(P("tamper=0")), "off");
  assert.equal(tamperMode(P("tamper=1")), "live");
  assert.equal(tamperMode(P("tamper=mock")), "mock");
  assert.match(HTML, /<button type="button" class="tamper-btn" id="btn-tamper" hidden>Corrupt one byte<\/button>/);
  assert.match(HTML, /id="btn-restore" hidden>Restore the byte</);
  assert.match(JS, /ui\.tamperBtn\.hidden = TAMPER === "off";/);
  assert.match(CSS, /\.tamper-btn \{ color: #fff; background: #D7263D;/, "the button is red");
});

// ---- the flip reply
test("a flip reply shows offset, expected, actual and the validator error, and the new ledger row", () => {
  const v = flipView(FLIP);
  assert.equal(v.ok, true);
  assert.equal(v.caught, true);
  assert.deepEqual(v.rows, [
    ["File", "ledger/evidence.jsonl"], ["Offset", "1,234 (0x4D2)"], ["Expected", "0x7b"], ["Actual", "0x7a"],
    ["Validator error", "ledger line 2: entry hash mismatch (tampered)"],
  ]);
  assert.deepEqual(v.row, { claim: "TAMPER-TEST", decision: "DATA_INVALID", reason: "entry hash mismatch", id: "abcdef012345", at: "" });
});

test("missing fields say so; nothing is filled in", () => {
  const v = flipView({ offset: 7 });
  assert.equal(v.ok, true);
  assert.deepEqual(v.rows.map(([, x]) => x), [NOT_IN_REPLY, "7 (0x7)", NOT_IN_REPLY, NOT_IN_REPLY, NOT_IN_REPLY]);
  assert.equal(v.row, null);
  assert.equal(v.caught, false, "no DATA_INVALID in the reply: no stamp");
  assert.match(tamperRefLine(v, PERSONALITY), /did not report DATA_INVALID/);
});

test("an ApiError body (409 DATA_INVALID with the flip fields as extras) still reads as a caught flip", () => {
  const v = flipView({ error: "DATA_INVALID", message: "sha256 mismatch on restricted_labels.sqlite", offset: 10, expected: "aa", actual: "ab" }, { httpStatus: 409 });
  assert.equal(v.ok, true);
  assert.equal(v.caught, true);
  assert.equal(v.error, "sha256 mismatch on restricted_labels.sqlite");
});

test("no endpoint, a network error or a non-flip reply: nothing flipped, no values, no stamp", async () => {
  assert.deepEqual(flipView({ error: "NOT_FOUND", message: "no route" }, { httpStatus: 404 }),
    { ok: false, problem: "the server did not report a flipped byte (HTTP 404: no route)" });
  assert.equal(flipView(null, { httpStatus: 500 }).ok, false);
  const down = await postTamper(TAMPER_FLIP_URL, async () => { throw new TypeError("Failed to fetch"); });
  assert.deepEqual(down, { status: 0, body: { message: "Failed to fetch" } });
  const v = flipView(down.body, { httpStatus: down.status });
  assert.equal(v.ok, false);
  assert.equal(tamperRefLine(v, PERSONALITY), "Can't run the tamper test: the server did not report a flipped byte (HTTP 0: Failed to fetch).");
});

test("the Ref words a caught flip in the personality's DATA_INVALID line; the stamp is DATA INVALID", () => {
  assert.equal(tamperRefLine(flipView(FLIP), PERSONALITY), "No ruling. The data failed its checks: ledger line 2: entry hash mismatch (tampered).");
  assert.deepEqual(stampFor("DATA_INVALID", PERSONALITY), { text: "DATA INVALID", kind: "blocked" });
  assert.equal(stateForDecision("DATA_INVALID"), "blocked");
  assert.ok(DEFAULT_PERSONALITY.ref_templates.DATA_INVALID);
});

test("ledger rows read from a flat row or a ledger entry", () => {
  assert.deepEqual(ledgerRowView({ evidence_id: "0123456789abcdef", identity: { claim: { claim_id: "CONF-HH" }, decision: "INSUFFICIENT_EVIDENCE", reason: "r" } }),
    { claim: "CONF-HH", decision: "INSUFFICIENT_EVIDENCE", reason: "r", id: "0123456789ab", at: "" });
  assert.equal(ledgerRowView({}), null);
  assert.equal(ledgerRowView(null), null);
});

// ---- restore
test("restore: success, failure, and the mock refuses a restore with nothing flipped", async () => {
  assert.equal(restoreView({ restored: true }).ok, true);
  assert.match(restoreView({ restored: true, file: "x.sqlite" }).text, /^Restored x\.sqlite: the byte is back/);
  assert.deepEqual(restoreView({ error: "IO", message: "read-only" }, { httpStatus: 500 }),
    { ok: false, text: "Restore failed (HTTP 500): read-only. The file may still be corrupted." });
  const f = mockTamperFetch();
  assert.equal((await postTamper(TAMPER_RESTORE_URL, f)).status, 409);
  assert.equal((await postTamper(TAMPER_FLIP_URL, f)).status, 200);
  const r = await postTamper(TAMPER_RESTORE_URL, f);
  assert.equal(restoreView(r.body, { httpStatus: r.status }).ok, true);
});

test("postTamper POSTs to the relative URL with no body", async () => {
  const calls = [];
  await postTamper(TAMPER_FLIP_URL, async (url, init) => { calls.push([url, init]); return { status: 200, json: async () => FLIP }; });
  assert.deepEqual(calls, [["/api/tamper/flip", { method: "POST", headers: { Accept: "application/json" } }]]);
});

// ---- mock mode is labelled
test("?tamper=mock replies say MOCK in every value and the panel says no file was changed", async () => {
  const r = await postTamper(TAMPER_FLIP_URL, mockTamperFetch());
  const v = flipView(r.body, { httpStatus: r.status, mock: true });
  for (const [k, x] of v.rows) if (k === "File" || k === "Validator error") assert.match(x, /^MOCK: /);
  const root = new El("section");
  renderTamper(root, v);
  assert.match(byClass(root, "tamper-mock")[0].textContent, /^MOCK REPLY: no request was sent and no file was changed$/);
  assert.equal(MOCK_FLIP.mock, true);
  assert.match(JS, /if \(TAMPER === "mock"\) ui\.tamperBtn\.textContent = "Corrupt one byte \(MOCK\)";/);
});

// ---- the panel
test("the panel lists the facts, then the ledger with the recent rows and the new one marked", () => {
  const root = new El("section");
  const recent = [{ evidence_id: "1111111111111111", identity: { claim: { claim_id: "CONF-HH" }, decision: "INSUFFICIENT_EVIDENCE" } }];
  renderTamper(root, flipView(FLIP), { recent, status: "One byte is corrupted." });
  assert.deepEqual(byTag(root, "dt").map((e) => e.textContent), ["File", "Offset", "Expected", "Actual", "Validator error"]);
  assert.equal(byClass(root, "tamper-error")[0].textContent, "ledger line 2: entry hash mismatch (tampered)");
  const rows = byTag(root, "tbody")[0].children;
  assert.equal(rows.length, 2);
  assert.equal(rows[0].className, "");
  assert.equal(rows[1].className, "tamper-new", "the new row is last and marked");
  assert.match(rows[1].textContent, /TAMPER-TESTDATA_INVALIDabcdef012345/);
  assert.equal(byClass(root, "tamper-mock").length, 0, "a live reply has no MOCK label");
  setTamperStatus(root, "Restored.", true);
  assert.equal(byClass(root, "tamper-status")[0].textContent, "Restored.");
  assert.ok(byClass(root, "tamper-status")[0].classList.contains("good"));
});

test("a failed flip draws only the problem: no facts, no ledger", () => {
  const root = new El("section");
  renderTamper(root, flipView(null, { httpStatus: 404 }));
  assert.equal(byTag(root, "dl").length, 0);
  assert.equal(byTag(root, "table").length, 0);
  assert.match(byClass(root, "tamper-problem")[0].textContent, /^Nothing was flipped: /);
});

// ---- page wiring (source order; the browser run is Max's, with demo.cmd)
test("runTamper: flip, Ref line, then the stamp only for a caught flip; Restore appears once a byte is flipped", () => {
  const i = JS.indexOf("async function runTamper(");
  const src = JS.slice(i, JS.indexOf("\nasync function runRestore(", i));
  const at = (s) => { const k = src.indexOf(s); assert.ok(k >= 0, s); return k; };
  assert.ok(at("postTamper(TAMPER_FLIP_URL") < at("renderTamper(ui.tamper, view"));
  assert.ok(at("if (view.ok) { state.tampered = true; ui.restoreBtn.hidden = false; }") < at("await h.speak(refLine, \"ref\""));
  assert.ok(at("await h.speak(refLine, \"ref\"") < at("if (view.ok && view.caught) {"));
  assert.ok(at("if (view.ok && view.caught) {") < at('stampFor("DATA_INVALID", state.personality)'));
  assert.match(src, /if \(state\.busy \|\| state\.tampered\) return;/, "one flip at a time until restored");
  const r = JS.slice(JS.indexOf("async function runRestore("), JS.indexOf("\n}\n", JS.indexOf("async function runRestore(")));
  assert.match(r, /postTamper\(TAMPER_RESTORE_URL/);
  assert.match(r, /if \(view\.ok\) \{\s*state\.tampered = false;\s*ui\.restoreBtn\.hidden = true;/);
  assert.match(JS, /ui\.tamperBtn\.disabled = b \|\| Boolean\(state\.tampered\);/);
});
