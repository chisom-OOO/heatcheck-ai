import { createRequire } from "module"; const require = createRequire(import.meta.url);
const pw = require("/opt/npm-tools/node_modules/playwright");
const b = await pw.chromium.launch({ executablePath: "/usr/bin/google-chrome", headless: true, args:["--no-sandbox"] });
const p = await b.newPage({ viewport: { width: 1360, height: 900 } });
await p.goto("http://127.0.0.1:8765/"); await p.waitForFunction(() => window.__heatcheck && window.__heatcheck.S.session);
await p.click("#tab-harness"); await p.waitForSelector("#harness-view svg");
await p.screenshot({ path: "evidence/screenshots/12_harness_full_batch.png", fullPage: true });
await b.close();
