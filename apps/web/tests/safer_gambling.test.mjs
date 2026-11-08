// Safer gambling (Max, 8 Nov 2026): Heater's page-side lines must carry no betting-encouragement
// wording. Same word list as heatcheck/agents/dialogue.py BETTING_WORDS (server side).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import { PLACEHOLDER_LINES } from "../web/heater/heater-model.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const BETTING = /(?<![\w'’])(?:bet|bets|betting|wager|value bet|free money|guaranteed|sure thing|can['’]?t lose|cannot lose|a lock|lock it in|mortal lock)(?![\w'’])/i;
const strings = (x) => (typeof x === "string" ? [x] : Array.isArray(x) ? x.flatMap(strings)
  : x && typeof x === "object" ? Object.values(x).flatMap(strings) : []);

test("the word list catches the phrases and lets ordinary words through", () => {
  for (const t of ["Bet it", "A LOCK", "value bet", "can't lose", "free money", "guaranteed"]) assert.ok(BETTING.test(t), t);
  for (const t of ["better", "between", "lockdown", "locked in the vault"]) assert.ok(!BETTING.test(t), t);
});

test("heater_personality.json (the lines the demo uses) has no betting wording", () => {
  const doc = JSON.parse(readFileSync(join(HERE, "..", "web", "heater", "heater_personality.json"), "utf8"));
  const bad = strings(doc).filter((s) => BETTING.test(s));
  assert.deepEqual(bad, []);
});

test("responsible_use.json has the short and full text", () => {
  const doc = JSON.parse(readFileSync(join(HERE, "..", "web", "responsible_use.json"), "utf8"));
  assert.deepEqual(Object.keys(doc).sort(), ["full", "short"]);
  assert.match(doc.short, /0808 8020 133/);
  assert.match(doc.full, /^Responsible use\. /);
});

// Open item for Experience (their file): heater-model.js PLACEHOLDER_LINES, used only if
// heater_personality.json fails to load, contain "Bet the rested team" and "a LOCK".
test("PLACEHOLDER_LINES (fallback if the personality file fails to load) have no betting wording",
  { todo: "Experience: reword PLACEHOLDER_LINES GP-REST ('Bet the rested team') and '*' ('a LOCK')" }, () => {
    const bad = strings(PLACEHOLDER_LINES).filter((s) => BETTING.test(s));
    assert.deepEqual(bad, []);
  });
