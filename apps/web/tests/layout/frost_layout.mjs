// Frost layout check (Experience, 8 Nov 2026; rehearsal fixes 1-3) in a real browser against MOCKS:
// a local server serves apps/web/web and answers the API with Max's captured answers
// (tests/fixtures/max_api/captures.json) or the ?frost=sample fixture. No model, no key, no network.
// Edge (installed) runs headless and is driven over the DevTools protocol with Node's own WebSocket,
// so nothing is downloaded. Max's real end-to-end run stays his (demo.cmd).
//
//   node apps/web/tests/layout/frost_layout.mjs OUTDIR [--edge PATH]
//
// For each viewport (1440x900, 1920x1080), a question with Frost (?frost=sample) and a market card
// with Frost (captured /api/investigate answer plus a MOCK frost list built from that card's own
// checks; the captures predate Frost). Checks, measured in the page:
//   - the middle column is at least 560 px wide; Heater's and Frost's figures stay inside their
//     columns; no bubble or chip reaches into Frost's column or is covered at its right edge
//   - when the stamp lands and after both reactions, the Ref card and the stamp are fully on screen
//     above the fixed footer
//   - Frost's bubbles and chips are on the page (dialogue: 3 questions, 3 chips; market: 3 and 3)
// Writes OUTDIR/<case>.png and OUTDIR/results.json; exits 1 on any failure.
import { spawn } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync, existsSync } from "node:fs";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { dirname, extname, join, normalize, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const APP = resolve(HERE, "..", "..");
const WEB = join(APP, "web");
const REPO = resolve(APP, "..", "..");
const OUT = resolve(process.argv[2] || join(tmpdir(), "frost-layout"));
const EDGE = (() => { const i = process.argv.indexOf("--edge"); return i > 0 ? process.argv[i + 1] : process.env.EDGE || "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe"; })();
const VIEWPORTS = [[1440, 900], [1920, 1080]];

// ---- mock API
const CAP = JSON.parse(readFileSync(join(APP, "tests", "fixtures", "max_api", "captures.json"), "utf8"));
const INDEX = JSON.parse(readFileSync(join(REPO, "data", "experience", "quotes", "20261107T222950Z", "board.mappings.json"), "utf8"));
const MAPPING_FIELDS = ["mapping_id", "game_id", "venue", "contract_id", "team_id", "label", "status", "two_sided"];
const live = CAP.exchanges.filter((e) => !e.test_forecast);
/** MOCK: three challenges in Max's shape, built from the card's own captured checks. */
function mockFrost(body) {
  const checks = (body.challenger_checks || []).slice(0, 3);
  return checks.map((c) => ({ check: c.check_id, question: `MOCK: what does ${c.check_id} say about this card?`,
    chip: `MOCK chip from the card's own check: ${c.status}: ${c.detail}`, source: c.check_id }));
}
function api(method, path, req) {
  if (path === "/api/route") return [200, { action: "DIALOGUE", game_id: null, reason: "mock" }];
  if (path === "/api/market-mappings") {
    return [200, { format: INDEX.format, mappings: INDEX.mappings.map((m) => Object.fromEntries(MAPPING_FIELDS.map((k) => [k, m[k]]))) }];
  }
  if (path === "/api/live-forecast") { const e = live.find((x) => x.path === path); return [e.status, e.body]; }
  if (path === "/api/investigate" && method === "POST") {
    const e = live.find((x) => x.path === path && x.status === 200 && x.request?.game_id === req?.game_id && x.request?.mapping_id === req?.mapping_id);
    if (!e) return [404, { error: "not in the captures" }];
    const body = JSON.parse(JSON.stringify(e.body));
    body.frost = mockFrost(body);
    body.frost_reaction = "MOCK: a gap is a question, not an edge.";
    return [200, body];
  }
  return [404, { error: "not found (mock)" }];
}
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json",
  ".webp": "image/webp", ".png": "image/png", ".svg": "image/svg+xml", ".jsonl": "application/x-ndjson" };
const server = createServer((rq, rs) => {
  const url = new URL(rq.url, "http://x");
  let body = "";
  rq.on("data", (d) => { body += d; });
  rq.on("end", () => {
    if (url.pathname.startsWith("/api/")) {
      let req = null;
      try { req = body ? JSON.parse(body) : null; } catch { req = null; }
      const [status, json] = api(rq.method, url.pathname, req);
      rs.writeHead(status, { "Content-Type": "application/json" });
      return rs.end(JSON.stringify(json));
    }
    const file = normalize(join(WEB, url.pathname === "/" ? "demo.html" : decodeURIComponent(url.pathname)));
    if (!file.startsWith(WEB + sep) || !existsSync(file)) { rs.writeHead(404); return rs.end(); }
    rs.writeHead(200, { "Content-Type": TYPES[extname(file)] || "application/octet-stream" });
    rs.end(readFileSync(file));
  });
});

// ---- Edge over the DevTools protocol
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function launchEdge() {
  const profile = mkdtempSync(join(tmpdir(), "frost-edge-"));
  const p = spawn(EDGE, ["--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check", "--mute-audio",
    "--disable-extensions", "--disable-sync", "--remote-debugging-port=0", `--user-data-dir=${profile}`, "about:blank"], { stdio: "ignore" });
  const portFile = join(profile, "DevToolsActivePort");
  for (let i = 0; i < 100 && !existsSync(portFile); i++) await sleep(100);
  const port = readFileSync(portFile, "utf8").split("\n")[0].trim();
  let page;
  for (let i = 0; i < 50 && !page; i++) {
    page = (await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find((t) => t.type === "page");
    if (!page) await sleep(100);
  }
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; });
  let id = 0;
  const pending = new Map();
  ws.onmessage = (m) => { const d = JSON.parse(m.data); if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); } };
  const send = (method, params = {}) => new Promise((res, rej) => {
    const i = ++id;
    pending.set(i, (d) => (d.error ? rej(new Error(`${method}: ${d.error.message}`)) : res(d.result)));
    ws.send(JSON.stringify({ id: i, method, params }));
  });
  const close = () => { try { ws.close(); } catch { /* closed */ } p.kill(); setTimeout(() => rmSync(profile, { recursive: true, force: true }), 1500); };
  return { send, close };
}

const MEASURE = `(async () => {
  const r = (el) => { if (!el || el.hidden) return null; const b = el.getBoundingClientRect(); return { l: b.left, t: b.top, r: b.right, b: b.bottom, w: b.width, h: b.height }; };
  // the drawn figure: bounding box of the visible pose's bright pixels, mapped to the screen
  window.__bb = window.__bb || {};
  const figure = async (img) => {
    if (!img) return null;
    const src = img.currentSrc || img.src;
    if (!window.__bb[src]) {
      const im = new Image(); im.src = src; await im.decode();
      const c = document.createElement("canvas"); c.width = im.naturalWidth; c.height = im.naturalHeight;
      const g = c.getContext("2d"); g.drawImage(im, 0, 0); const d = g.getImageData(0, 0, c.width, c.height).data;
      let l = c.width, rr = -1, t = c.height, bb = -1;
      for (let y = 0; y < c.height; y++) for (let x = 0; x < c.width; x++) { const k = (y * c.width + x) * 4;
        if (d[k + 3] > 40 && Math.max(d[k], d[k + 1], d[k + 2]) > 60) { if (x < l) l = x; if (x > rr) rr = x; if (y < t) t = y; if (y > bb) bb = y; } }
      window.__bb[src] = [l / c.width, (rr + 1) / c.width, t / c.height, (bb + 1) / c.height];
    }
    const [fl, fr, ft, fb] = window.__bb[src];
    const b = img.getBoundingClientRect();   // poses fill their box (same 687/1024 aspect)
    return { l: b.left + fl * b.width, r: b.left + fr * b.width, t: b.top + ft * b.height, b: b.top + fb * b.height, boxH: b.height, src: src.split("/").pop() };
  };
  const label = (el) => { if (!el) return null; const cs = getComputedStyle(el); return { ...r(el), shown: cs.display !== "none", text: el.innerText, font: cs.fontFamily, size: cs.fontSize, color: cs.color }; };
  const asked = document.getElementById("asked"), acs = getComputedStyle(asked);
  const input = document.getElementById("q").getBoundingClientRect();
  const inputOn = input.top >= 0 && input.bottom <= document.getElementById("ru-footer").getBoundingClientRect().top;
  const inputAt = inputOn ? document.elementFromPoint(input.left + 20, (input.top + input.bottom) / 2) : null;
  const foot = document.getElementById("ru-footer").getBoundingClientRect().top;
  const items = [...document.querySelectorAll("#convo > li")].map((li) => {
    const b = li.getBoundingClientRect();
    const cy = (b.top + b.bottom) / 2;
    let covered = null;
    if (cy > 0 && cy < foot) { const at = document.elementFromPoint(Math.min(b.right - 6, innerWidth - 1), cy); covered = !(at && (at === li || li.contains(at))); }
    return { cls: li.className, l: b.left, r: b.right, covered };
  });
  return { vw: innerWidth, vh: innerHeight, foot, scrollY, phase: document.body.dataset.phase, cast: document.body.dataset.cast,
    talk: r(document.querySelector(".talk")), side: r(document.getElementById("frost-side")), hero: r(document.querySelector(".hero")),
    froot: r(document.querySelector(".f-root")), hroot: r(document.querySelector(".hero .h-root")),
    ref: r(document.getElementById("ref")), stamp: r(document.getElementById("stamp")), items,
    frostBubbles: document.querySelectorAll("#convo .cv-frost").length, chips: document.querySelectorAll("#convo .cv-chip").length,
    sample: !document.getElementById("sample-flag").hidden, stampText: document.getElementById("stamp").textContent,
    hfig: await figure(document.querySelector(".hero .h-pose.on")), ffig: await figure(document.querySelector(".f-pose.on")),
    hname: label(document.querySelector(".heater-name")), fname: label(document.querySelector(".frost-name")),
    brandShown: !document.querySelector(".brand").hidden, asked: { shown: !asked.hidden, text: asked.textContent, size: acs.fontSize, weight: acs.fontWeight, color: acs.color, align: acs.textAlign },
    form: r(document.getElementById("ask")), inputFree: inputOn ? Boolean(inputAt && document.getElementById("ask").contains(inputAt)) : null,
    headline: document.getElementById("ref-title").textContent, badgeSize: getComputedStyle(document.querySelector(".ref-badge")).fontSize };
})()`;

function judge(name, m, expect) {
  const fails = [];
  const ok = (c, msg) => { if (!c) fails.push(msg); };
  const s = m.final;
  ok(s.cast === "frost", `Frost on stage (cast=${s.cast})`);
  ok(s.talk.w >= 560, `middle column ${s.talk.w.toFixed(0)} px >= 560`);
  ok(s.side.l >= s.talk.r - 0.5, `Frost's column starts after the conversation (${s.side.l.toFixed(0)} >= ${s.talk.r.toFixed(0)})`);
  ok(s.hero.r <= s.talk.l + 0.5, `Heater's column ends before the conversation (${s.hero.r.toFixed(0)} <= ${s.talk.l.toFixed(0)})`);
  // the drawn figures (not their boxes, whose empty edges may be clipped) stay inside their columns
  for (const [who, f, col] of [["Heater", s.hfig, s.hero], ["Frost", s.ffig, s.side]]) {
    ok(f && f.l >= col.l - 1 && f.r <= col.r + 1, `${who}'s drawn figure (${f?.src}) inside his column (${f?.l.toFixed(0)}..${f?.r.toFixed(0)} in ${col.l.toFixed(0)}..${col.r.toFixed(0)})`);
    const frac = f ? f.boxH / s.vh : 0;
    if (s.vw >= 1900) ok(frac >= 0.85 && frac <= 0.9 + 1e-3, `${who} is ${(frac * 100).toFixed(1)}% of the viewport height (85-90% at 1920x1080)`);
    else ok(frac >= 0.6, `${who} is ${(frac * 100).toFixed(1)}% of the viewport height (as large as the column allows)`);
    ok(f && f.b <= s.foot + 0.5 && f.b >= s.foot - 90, `${who}'s feet near the bottom above the footer (${f?.b.toFixed(0)}, footer ${s.foot.toFixed(0)})`);
  }
  // name labels: shown, centred over the figure, above its head, inside the column, in their colours
  for (const [who, n, f, col, color, font] of [["HEATER", s.hname, s.hfig, s.hero, "rgb(255, 122, 26)", "Oswald"], ["FROST", s.fname, s.ffig, s.side, "rgb(143, 211, 255)", "Nunito"]]) {
    ok(n?.shown && n.text === who, `${who} label shown (${n?.text})`);
    ok(Boolean(n) && n.size === "44px" && n.color === color && n.font.replace(/"/g, "").startsWith(font),`${who} label 44px ${color} ${font} (${n?.size} ${n?.color} ${n?.font})`);
    ok(n && n.l >= col.l - 1 && n.r <= col.r + 1, `${who} label inside its column`);
    ok(n && f && Math.abs((n.l + n.r) / 2 - (f.l + f.r) / 2) <= 45, `${who} label centred over the figure (label ${((n.l + n.r) / 2).toFixed(0)}, figure ${((f.l + f.r) / 2).toFixed(0)})`);
    ok(n && f && n.b <= f.t + 2, `${who} label above the head (label bottom ${n?.b.toFixed(0)}, head ${f?.t.toFixed(0)})`);
  }
  // the ask box sits under the conversation, uncovered
  ok(s.form.l >= s.hero.r - 0.5 && s.form.r <= s.side.l + 0.5, `ask box within the middle column (${s.form.l.toFixed(0)}..${s.form.r.toFixed(0)})`);
  ok(s.inputFree !== false, `question box not covered (${s.inputFree === null ? "scrolled below the Ref card, not checked here" : "on screen"})`);
  // the question replaces the wordmark; the Ref card's headline and badge
  ok(!s.brandShown && s.asked.shown && s.asked.text === expect.asked, `question shown instead of the wordmark ("${s.asked.text}")`);
  ok(s.asked.size === "26px" && s.asked.weight === "700" && s.asked.color === "rgb(236, 234, 244)" && s.asked.align === "center", `question style ${s.asked.size} ${s.asked.weight} ${s.asked.color} ${s.asked.align}`);
  ok(s.headline && s.headline.length > 0, `Ref headline: "${s.headline}"`);
  ok(s.badgeSize === "24.96px", `THE REF badge ${s.badgeSize} (double .78rem)`);
  for (const it of s.items) {
    ok(it.l >= s.hero.r - 0.5, `${it.cls} starts at ${it.l.toFixed(0)}, after Heater's column at ${s.hero.r.toFixed(0)}`);
    ok(it.r <= s.side.l + 0.5, `${it.cls} ends at ${it.r.toFixed(0)}, before Frost's column at ${s.side.l.toFixed(0)}`);
    ok(it.covered !== true, `${it.cls} not covered at its right edge`);
  }
  for (const [when, x] of [["stamp", m.atStamp], ["end", s]]) {
    ok(x.ref && x.ref.t >= 0 && x.ref.b <= x.foot + 0.5, `${when}: Ref card on screen above the footer (top ${x.ref?.t.toFixed(0)}, bottom ${x.ref?.b.toFixed(0)}, footer ${x.foot.toFixed(0)})`);
    ok(x.stamp && x.stamp.t >= 0 && x.stamp.b <= x.foot + 0.5, `${when}: stamp on screen above the footer (top ${x.stamp?.t.toFixed(0)}, bottom ${x.stamp?.b.toFixed(0)})`);
  }
  ok(s.frostBubbles >= expect.questions, `${s.frostBubbles} Frost bubbles >= ${expect.questions}`);
  ok(s.chips === expect.chips, `${s.chips} chips == ${expect.chips}`);
  if (expect.sample) ok(s.sample, "SAMPLE RESPONSE label shown");
  return { case: name, pass: fails.length === 0, fails, final: { ...s, items: s.items.length }, atStamp: { ref: m.atStamp.ref, stamp: m.atStamp.stamp, foot: m.atStamp.foot } };
}

async function runCase(b, base, [w, h], kind) {
  const name = `${kind}-${w}x${h}`;
  await b.send("Emulation.setDeviceMetricsOverride", { width: w, height: h, deviceScaleFactor: 1, mobile: false });
  const q = kind === "dialogue" ? `?voice=0&frost=sample&ask=${encodeURIComponent("Is the hot hand real?")}` : "?voice=0&board=1";
  await b.send("Page.navigate", { url: `${base}/demo.html${q}` });
  const ev = async (expr) => (await b.send("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true })).result.value;
  for (let i = 0; i < 100 && !(await ev("document.body.dataset.ready === '1'")); i++) await sleep(100);
  if (kind === "market") {
    for (let i = 0; i < 200 && !(await ev("!!document.querySelector('.mcard-ask:not(.board-retry):not([disabled])')")); i++) await sleep(150);
    await sleep(800);
    await ev("document.querySelector('.mcard-ask:not(.board-retry):not([disabled])').click(), true");
  }
  const t0 = Date.now();
  let atStamp = null;
  while (Date.now() - t0 < 180000) {
    const ph = await ev("document.body.dataset.phase");
    if (!atStamp && (ph === "verdict" || ph === "done")) { await sleep(1500); atStamp = await ev(MEASURE); }
    if (ph === "done" && atStamp) break;
    await sleep(250);
  }
  await sleep(1200);
  const final = await ev(MEASURE);
  const shot = await b.send("Page.captureScreenshot", { format: "png" });
  writeFileSync(join(OUT, `${name}.png`), Buffer.from(shot.data, "base64"));
  if (!atStamp) return { case: name, pass: false, fails: [`no stamp within 180 s (phase ${final.phase})`], final };
  return judge(name, { atStamp, final }, kind === "dialogue" ? { questions: 3, chips: 3, sample: true, asked: "Is the hot hand real?" } : { questions: 3, chips: 3, asked: "Walk me through this game" });
}

/** The idle home view: the wordmark, no question, no name labels (Heater alone). */
async function homeCase(b, base, [w, h]) {
  const name = `home-${w}x${h}`;
  await b.send("Emulation.setDeviceMetricsOverride", { width: w, height: h, deviceScaleFactor: 1, mobile: false });
  await b.send("Page.navigate", { url: `${base}/demo.html?voice=0` });
  const ev = async (expr) => (await b.send("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true })).result.value;
  for (let i = 0; i < 100 && !(await ev("document.body.dataset.ready === '1'")); i++) await sleep(100);
  await sleep(500);
  const s = await ev(`({ brand: !document.querySelector(".brand").hidden, asked: !document.getElementById("asked").hidden,
    label: getComputedStyle(document.querySelector(".heater-name")).display })`);
  const shot = await b.send("Page.captureScreenshot", { format: "png" });
  writeFileSync(join(OUT, `${name}.png`), Buffer.from(shot.data, "base64"));
  const fails = [];
  if (!s.brand || s.asked) fails.push(`home: wordmark shown and no question (brand ${s.brand}, asked ${s.asked})`);
  return { case: name, pass: fails.length === 0, fails, final: s };
}

mkdirSync(OUT, { recursive: true });
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const base = `http://127.0.0.1:${server.address().port}`;
const b = await launchEdge();
const results = [];
try {
  await b.send("Page.enable");
  await b.send("Runtime.enable");
  // offline: the Google Fonts stylesheet is blocked, so the labels use their fallback fonts here; the
  // check reads the declared family (Oswald / Nunito first)
  await b.send("Network.enable");
  await b.send("Network.setBlockedURLs", { urls: ["*fonts.googleapis.com*", "*fonts.gstatic.com*"] });
  for (const vp of VIEWPORTS) for (const kind of ["home", "dialogue", "market"]) {
    const r = kind === "home" ? await homeCase(b, base, vp) : await runCase(b, base, vp, kind);
    results.push(r);
    console.log(`${r.pass ? "PASS" : "FAIL"} ${r.case}${r.fails.length ? `\n  - ${r.fails.join("\n  - ")}` : ""}`);
  }
} finally {
  b.close();
  server.close();
}
writeFileSync(join(OUT, "results.json"), `${JSON.stringify({ edge: EDGE, results }, null, 1)}\n`);
const failed = results.filter((r) => !r.pass).length;
console.log(`${results.length - failed}/${results.length} cases PASS`);
process.exit(failed ? 1 : 0);
