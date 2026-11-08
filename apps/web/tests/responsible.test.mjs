// Responsible-use notice on the page (Max, 8 Nov 2026): one source (responsible_use.json), static
// footer equal to it, board header (board.test.mjs), once-per-session notice on the first market Ask.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import { ASK_NOTICE_KEY, firstAskThisSession, loadResponsibleUse } from "../web/responsible.js";

const WEB = join(dirname(fileURLToPath(import.meta.url)), "..", "web");
const RU = JSON.parse(readFileSync(join(WEB, "responsible_use.json"), "utf8"));
const unescape = (s) => s.replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");

test("the page footer is always in demo.html and equals the JSON short text", () => {
  const html = readFileSync(join(WEB, "demo.html"), "utf8");
  const m = html.match(/<footer class="ru-footer" id="ru-footer">([^<]*)<\/footer>/);
  assert.ok(m, "footer missing");
  assert.equal(unescape(m[1]), RU.short);
  assert.ok(html.indexOf("ru-footer") > html.indexOf("</main>"), "footer sits outside every view");
  assert.match(html, /<aside class="ru-notice" id="ru-notice" hidden/);
});

test("the footer is fixed and visible on every view (CSS)", () => {
  const css = readFileSync(join(WEB, "demo.css"), "utf8");
  assert.match(css, /\.ru-footer\s*\{[^}]*position:\s*fixed/);
  assert.doesNotMatch(css, /body\[data-view="[^"]+"\][^{]*\.ru-footer[^{]*\{[^}]*display:\s*none/);
});

test("loadResponsibleUse reads both fields, and returns null on any failure", async () => {
  const ok = await loadResponsibleUse(async () => ({ ok: true, json: async () => RU }));
  assert.deepEqual(ok, { short: RU.short, full: RU.full });
  assert.equal(await loadResponsibleUse(async () => ({ ok: false })), null);
  assert.equal(await loadResponsibleUse(async () => { throw new TypeError("offline"); }), null);
  assert.equal(await loadResponsibleUse(async () => ({ ok: true, json: async () => ({ short: 1 }) })), null);
});

test("the Ask notice shows once per session", () => {
  const store = new Map();
  const storage = { getItem: (k) => store.get(k) ?? null, setItem: (k, v) => store.set(k, v) };
  assert.equal(firstAskThisSession(storage, { shown: false }), true);
  assert.equal(store.get(ASK_NOTICE_KEY), "1");
  assert.equal(firstAskThisSession(storage, { shown: false }), false);      // reload, same session
  const memo = { shown: false };
  const broken = { getItem() { throw new Error("blocked"); }, setItem() { throw new Error("blocked"); } };
  assert.equal(firstAskThisSession(broken, memo), true);                    // storage blocked: once per page
  assert.equal(firstAskThisSession(broken, memo), false);
});
