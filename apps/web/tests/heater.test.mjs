// Run from apps/web:  node --test tests/heater.test.mjs
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import * as M from "../web/heater/heater-model.js";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const H = join(ROOT, "web", "heater");
const css = readFileSync(join(H, "heater.css"), "utf8");
const js = readFileSync(join(H, "heater.js"), "utf8");
const FIXTURE = join(H, "fixtures", "evidence_real_game.jsonl");
const SOURCE = join(ROOT, "..", "..", "reports", "max", "logs", "2026-11-07-loop", "evidence_real_game.jsonl");
const entries = () => M.parseJsonl(readFileSync(FIXTURE, "utf8"));
const byClaim = (id) => entries().find((e) => e.identity.claim.claim_id === id);

/** Width and height of a WebP file (VP8, VP8L or VP8X), read from its header. */
function webpSize(buf) {
  assert.equal(buf.toString("ascii", 0, 4), "RIFF");
  assert.equal(buf.toString("ascii", 8, 12), "WEBP");
  const kind = buf.toString("ascii", 12, 16);
  if (kind === "VP8X") return [1 + buf.readUIntLE(24, 3), 1 + buf.readUIntLE(27, 3)];
  if (kind === "VP8 ") return [buf.readUInt16LE(26) & 0x3fff, buf.readUInt16LE(28) & 0x3fff];
  if (kind === "VP8L") {
    const b = buf.readUInt32LE(21);
    return [1 + (b & 0x3fff), 1 + ((b >> 14) & 0x3fff)];
  }
  throw new Error(`unknown WebP chunk ${kind}`);
}

test("one pose map covers all 9 states; unsure and blocked borrow thinking and listening", () => {
  assert.deepEqual(Object.keys(M.POSE_FOR_STATE).sort(), [...M.STATES].sort());
  for (const s of M.STATES) assert.ok(M.POSES.includes(M.POSE_FOR_STATE[s]), s);
  assert.equal(M.POSE_FOR_STATE.unsure, "thinking");
  assert.equal(M.POSE_FOR_STATE.blocked, "listening");
  for (const p of M.POSES) assert.equal(M.POSE_FOR_STATE[p], p);
  assert.equal(M.poseFile("cooled"), "poses/cooled.webp");
  assert.equal(M.POSES.length, 7);
});

const missingPoses = M.POSES.filter((p) => !existsSync(join(H, "poses", `${p}.webp`)));
test("pose images present", { todo: missingPoses.length ? `missing: ${missingPoses.join(", ")}` : false }, () => {
  assert.deepEqual(missingPoses, []);
});

test("every pose image present is a 687x1024 WebP", () => {
  for (const p of M.POSES.filter((x) => !missingPoses.includes(x))) {
    const [w, h] = webpSize(readFileSync(join(H, "poses", `${p}.webp`)));
    assert.deepEqual([w, h], [687, 1024], p);
  }
});

test("the SVG rig is gone: no heater.svg and no SVG mount", () => {
  assert.ok(!existsSync(join(H, "heater.svg")));
  assert.doesNotMatch(js, /heater\.svg|innerHTML = \(await/);
  assert.match(js, /createElement\("img"|el\("img"/);
});

test("CSS: 200 ms crossfade, #12121A stage, radial edge mask, every state, reduced motion", () => {
  assert.match(css, /:is\(\.h-pose, \.h-slice\) \{ transition: opacity 200ms ease/);
  assert.match(css, /\.h-pose\.on \{ opacity: 1; \}/);
  assert.match(css, /--stage: #12121A/);
  assert.match(css, /mask-image: var\(--mask\)/);
  assert.match(css, /--mask: radial-gradient\(/);
  for (const s of M.STATES) assert.match(css, new RegExp(`\\.st-${s}\\b`), s);
  assert.match(css, /@keyframes h-squash/);
  assert.match(css, /translateX\(-3px\)[\s\S]*translateX\(3px\)/);
  assert.match(css, /\.h-slice \{[^}]*animation: h-slice 600ms/);
  assert.match(css, /\.st-cooled \.h-spark:nth-child\(n\+3\) \{ display: none; \}/);
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)[\s\S]*animation: none !important[\s\S]*\.h-sparks, \.h-root \.h-glitch \{ display: none !important; \}/);
  assert.doesNotMatch(css, /@import|url\(\s*["']?https?:/i);
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

test("card model for HH-K2: the Ref's numbers come only from the record", () => {
  const e = byClaim("HH-K2");
  const m = M.cardModel(e, { verified: false });
  assert.equal(m.title, e.identity.claim.plan.statement);
  assert.equal(m.endState, "cooled");
  assert.ok(m.refLine.endsWith(e.identity.reason));
  assert.deepEqual(m.facts, ["5 attacks", "181 attempts", "1 game", "real nba retrospective",
    `evidence ${e.evidence_id.slice(0, 8)}`, "hashes not verified here"]);
  const shown = [m.title, m.refLine, ...m.facts].join(" ");
  const record = JSON.stringify(e);
  for (const n of shown.match(/\d[\d.,]*/g) || []) {
    const plain = n.replace(/,/g, "").replace(/\.$/, "");
    assert.ok(record.includes(plain) || plain === String(e.identity.attack_results.length), `number ${n} not in record`);
  }
});

test("Heater's line is a hot take, never the claim description", () => {
  for (const e of entries()) {
    const m = M.cardModel(e);
    assert.notEqual(m.heaterLine, m.title);
    assert.ok(!m.heaterLine.includes(m.title));
    assert.doesNotMatch(m.heaterLine, /\d/, "Heater says no numbers; those belong to the Ref");
  }
  assert.equal(M.cardModel(byClaim("HH-K2")).heaterLine, "Two in a row? He's HEATING UP! Give him the ball!");
});

test("personality file formats: table, {lines}, {claims}, default fallback, rotation", () => {
  const t = M.linesTable({ lines: { "HH-K2": ["A!", "B!"], default: "Generic!" } });
  assert.deepEqual(t, { "HH-K2": ["A!", "B!"], "*": ["Generic!"] });
  assert.deepEqual(M.linesTable({ claims: { X: ["x"] } }), { X: ["x"] });
  assert.deepEqual(M.linesTable({ X: "x" }), { X: ["x"] });
  assert.equal(M.linesTable([]), null);
  assert.equal(M.linesTable({ X: [1, null] }), null);
  assert.equal(M.heaterLineFor("HH-K2", t, 1), "B!");
  assert.equal(M.heaterLineFor("GP-REST", t), "Generic!");
  assert.equal(M.heaterLineFor("GP-REST", { X: ["x"] }), M.PLACEHOLDER_LINES["*"][0]);
});

const PERSONALITY = JSON.parse(readFileSync(join(H, "heater_personality.json"), "utf8"));
const WEB = join(ROOT, "web");

test("Ref in plain English: words first, numbers second, every number from the record", () => {
  const k2 = byClaim("HH-K2");
  assert.equal(M.refPlain(k2, PERSONALITY).text,
    "The data says no. Making two in a row didn't make the next shot more likely (p = 0.24, 181 shots, one game).");
  const perm = k2.identity.attack_results.find((a) => a.test_id_version.startsWith("A-PERMUTATION-NULL@"));
  assert.equal(M.fmtP(perm.p_value), "0.24");
  assert.equal(M.refPlain(byClaim("HH-K3"), PERSONALITY).text,
    "Can't tell yet. Too few shots came right after three makes in a row to compare (14 after three makes, 18 after three misses; 30 of each needed). Not enough evidence either way.");
  assert.equal(M.refPlain(byClaim("GP-REST"), PERSONALITY).text,
    "No ruling. This test needs season-long game results, and those aren't loaded yet.");
  for (const e of entries()) {
    const { text, plain } = M.refPlain(e, PERSONALITY);
    assert.ok(plain, e.identity.claim.claim_id);
    const record = JSON.stringify(e);
    for (const n of text.match(/\d[\d.,]*/g) || []) {
      const v = n.replace(/[.,]$/, "");
      const inRecord = record.includes(v) || (v.includes(".") && record.match(/\d+\.\d+/g).some((x) => M.fmtP(Number(x)) === v));
      assert.ok(inRecord, `${e.identity.claim.claim_id}: ${n} not from the record`);
    }
  }
});

test("stamps, takes and reactions come from heater_personality.json", () => {
  assert.deepEqual(M.stampFor("NOT_SUPPORTED", PERSONALITY), { text: "NOT SUPPORTED", kind: "not-supported" });
  assert.deepEqual(M.stampFor("INSUFFICIENT_EVIDENCE", PERSONALITY), { text: "NOT ENOUGH EVIDENCE", kind: "insufficient" });
  assert.deepEqual(M.stampFor("SURVIVED_PROTOCOL", PERSONALITY), { text: "SURVIVED", kind: "survived" });
  assert.equal(M.stampFor("BLOCKED", PERSONALITY).text, PERSONALITY.verdict_stamps.BLOCKED);
  assert.equal(M.stampFor(null).kind, "untested");
  assert.equal(M.takeFor("HH-K2", PERSONALITY), "Two in a row? He's HEATING UP! Give him the ball!");
  assert.equal(M.takeFor("NOT-A-CLAIM", PERSONALITY), PERSONALITY.claims.NONE);
  assert.equal(M.reactFor("NOT_SUPPORTED", PERSONALITY, 1), PERSONALITY.react.NOT_SUPPORTED[1]);
  assert.equal(M.reactFor("UNKNOWN", PERSONALITY), "");
});

test("offline routing of the example questions", () => {
  assert.equal(M.routeQuestion("Is the hot hand real?"), "HH-K2");
  assert.equal(M.routeQuestion("Three in a row, is he hot?"), "HH-K3");
  assert.equal(M.routeQuestion("Do home teams win more?"), "CONF-HA");
  assert.equal(M.routeQuestion("Does rest matter?"), "GP-REST");
  assert.equal(M.routeQuestion("Who is the GOAT?"), "NONE");
  assert.equal(M.latestFor(entries(), "HH-K2").identity.decision, "NOT_SUPPORTED");
  assert.equal(M.latestFor(entries(), "CONF-HA"), null);
  for (const id of Object.keys(PERSONALITY.claims)) assert.ok(M.CLAIM_TITLES[id], `display title for ${id}`);
});

test("demo page: no debug text in the default view", () => {
  const html = readFileSync(join(WEB, "demo.html"), "utf8");
  assert.doesNotMatch(html, /HH-K|GP-|CONF-|<select|type="checkbox"|hashes|placeholder lines|Phase/);
  assert.doesNotMatch(html, /<script(?![^>]*\bsrc=)|style=|<style/);
  assert.match(html, /Ask Heater anything about the NBA…/);
  for (const chip of ["Is the hot hand real?", "Do home teams win more?", "Does rest matter?"]) assert.ok(html.includes(chip), chip);
  const js2 = readFileSync(join(WEB, "demo.js"), "utf8");
  assert.match(js2, /params\.get\("debug"\) === "1"/);
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
