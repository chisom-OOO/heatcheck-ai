// Run from apps/web:  node --test tests/heater.test.mjs
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import * as M from "../web/heater/heater-model.js";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const H = join(ROOT, "web", "heater");
const svg = readFileSync(join(H, "heater.svg"), "utf8");
const css = readFileSync(join(H, "heater.css"), "utf8");
const FIXTURE = join(H, "fixtures", "evidence_real_game.jsonl");
const SOURCE = join(ROOT, "..", "..", "reports", "max", "logs", "2026-11-07-loop", "evidence_real_game.jsonl");
const entries = () => M.parseJsonl(readFileSync(FIXTURE, "utf8"));
const byClaim = (id) => entries().find((e) => e.identity.claim.claim_id === id);

test("rig: 15-25 angular shards, exactly one circle (the ball), every named part", () => {
  const shards = svg.match(/<polygon class="h-shard[^"]*"/g) || [];
  assert.ok(shards.length >= 15 && shards.length <= 25, `shards=${shards.length}`);
  assert.equal((svg.match(/<circle/g) || []).length, 1);
  assert.match(svg, /<circle class="h-ball-core"/);
  const parts = ["h-crest", "h-visor", "h-mouth", "h-jaw", "h-lapel", "h-arm-l", "h-arm-r", "h-claw-l",
    "h-claw-r", "h-leg-l", "h-leg-r", "h-ball", "h-blazer-back", "h-blazer-front"];
  for (let i = 1; i <= 7; i++) parts.push(`h-flame-${i}`);
  for (const p of parts) assert.match(svg, new RegExp(`class="[^"]*\\b${p}\\b`), p);
  assert.match(svg, /viewBox="0 0 220 320"/);
});

test("rig: feet stand on the y=300 baseline and nothing goes below the floor", () => {
  for (const leg of ["h-leg-l", "h-leg-r"]) {
    const pts = svg.match(new RegExp(`${leg}" points="([^"]+)"`))[1].trim().split(/\s+/).map((p) => p.split(",").map(Number));
    assert.equal(Math.max(...pts.map((p) => p[1])), 300, leg);
  }
  const all = [...svg.matchAll(/points="([^"]+)"/g)].flatMap((m) => m[1].trim().split(/\s+/).map((p) => Number(p.split(",")[1])));
  assert.ok(Math.max(...all) <= 303);
});

test("rig is self-contained: no style, script, external reference or raster", () => {
  for (const bad of [/<style/i, /<script/i, /href=/i, /<image/i, /style="/i, /https?:\/\/(?!www\.w3\.org\/2000\/svg)/i]) {
    assert.doesNotMatch(svg, bad, String(bad));
  }
  assert.doesNotMatch(css, /@import|url\(\s*["']?https?:/i);
});

test("every state has a CSS class, and reduced motion removes the loops", () => {
  for (const s of ["idle", "hot_take", "heat_check", "vindicated", "cooled"]) assert.match(css, new RegExp(`\\.st-${s}\\b`), s);
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)[\s\S]*animation: none !important/);
});

test("fixture is a byte copy of Max's committed ledger", { skip: !existsSync(SOURCE) && "source ledger not on this branch" }, () => {
  assert.ok(readFileSync(FIXTURE).equals(readFileSync(SOURCE)));
});

test("verdict -> end state and chip; unknown verdicts never vindicate", () => {
  assert.equal(M.stateForDecision("SURVIVED_PROTOCOL"), "vindicated");
  assert.equal(M.stateForDecision("NOT_SUPPORTED"), "cooled");
  assert.equal(M.stateForDecision("INSUFFICIENT_EVIDENCE"), "unsure");
  assert.equal(M.stateForDecision("BLOCKED"), "blocked");
  assert.equal(M.stateForDecision("DATA_INVALID"), "blocked");
  assert.equal(M.stateForDecision("PROBABLY_TRUE"), "unsure");
  assert.deepEqual(M.chipFor(null), { text: "CHECKING…", kind: "checking" });
  assert.deepEqual(M.chipFor("NOT_SUPPORTED"), { text: "NOT SUPPORTED", kind: "not-supported" });
  assert.equal(M.chipFor("PROBABLY_TRUE").kind, "unknown");
});

test("card model for HH-K2 uses only the record's own text and numbers", () => {
  const e = byClaim("HH-K2");
  const m = M.cardModel(e, { verified: false });
  assert.equal(m.title, e.identity.claim.plan.statement);
  assert.equal(m.endState, "cooled");
  assert.ok(m.refLine.endsWith(e.identity.reason));
  assert.deepEqual(m.facts, ["5 attacks", "181 attempts", "1 game", "real nba retrospective",
    `evidence ${e.evidence_id.slice(0, 8)}`, "hashes not verified here"]);
  // every digit run shown on the card appears in the serialized record
  const shown = [m.title, m.refLine, ...m.facts].join(" ");
  const record = JSON.stringify(e);
  for (const n of shown.match(/\d[\d.,]*/g) || []) {
    const plain = n.replace(/,/g, "").replace(/\.$/, "");
    assert.ok(record.includes(plain) || plain === String(e.identity.attack_results.length), `number ${n} not in record`);
  }
});

test("every committed record maps to a state and a chip without problems", () => {
  const got = entries().map((e) => [e.identity.claim.claim_id, M.cardModel(e).endState, M.cardModel(e).problems]);
  assert.deepEqual(got, [["HH-K3", "unsure", []], ["HH-K2", "cooled", []], ["GP-REST", "blocked", []]]);
});

test("bad input is refused, never zero-filled", () => {
  assert.equal(M.cardModel({ evidence_id: 1 }).ok, false);
  assert.throws(() => M.parseJsonl('{"a":1}\n'), /not an evidence-ledger entry/);
  assert.throws(() => M.parseJsonl("nope\n"), /not JSON/);
});

test("emphasis words and boundary word lookup", () => {
  assert.ok(M.isEmphasis("HOT") && M.isEmphasis("HH-K3") && M.isEmphasis("NEVER!"));
  assert.ok(!M.isEmphasis("Hot") && !M.isEmphasis("A") && !M.isEmphasis("p=0.2390"));
  assert.equal(M.wordAt("HOT take: same", 0), "HOT");
  assert.equal(M.wordAt("HOT take: same", 5), "take:");
  assert.equal(M.wordAt("abc", 9), "");
});

test("voices: Heater and Ref get different voices when two exist", () => {
  const v = [{ name: "Microsoft Guy Online", lang: "en-US" }, { name: "Microsoft Libby Online", lang: "en-GB" }, { name: "Hortense", lang: "fr-FR" }];
  const { heater, ref } = M.pickVoices(v);
  assert.equal(heater.name, "Microsoft Guy Online");
  assert.equal(ref.name, "Microsoft Libby Online");
  assert.deepEqual(M.pickVoices([]), { heater: null, ref: null });
  assert.deepEqual(M.VOICE, { heater: { rate: 1.15, pitch: 1.1 }, ref: { rate: 0.95, pitch: 0.9 } });
});
