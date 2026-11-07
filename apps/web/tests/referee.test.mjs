// Run from apps/web:  node --test tests/
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import * as referee from "../web/referee.js";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const example = () => JSON.parse(readFileSync(join(ROOT, "fixtures", "referee", "provisional_record.example.json"), "utf8"));
const valid = () => JSON.parse(readFileSync(join(ROOT, "fixtures", "envelopes", "valid", "AttackResult.json"), "utf8"));

test("module is pure: no DOM or network globals used", () => {
  const src = readFileSync(join(ROOT, "web", "referee.js"), "utf8");
  for (const word of ["document.", "window.", "fetch(", "innerHTML", "XMLHttpRequest"]) assert.ok(!src.includes(word), word);
});

test("provisional record maps to claim, attacks, verdict, evidence", () => {
  const vm = referee.fromRecord(example());
  assert.equal(vm.source, "REFEREE_RECORD");
  assert.match(vm.format_status, /^PROVISIONAL/);
  assert.equal(vm.data_mode, "SYNTHETIC");
  assert.equal(referee.show(vm.claim.statement), "Players shoot better after three makes");
  assert.deepEqual(vm.attacks.map((a) => a.outcome), ["PASSED", "FAILED", "NOT_RUN"]);
  assert.equal(referee.show(vm.attacks[0].statistic), "0.031");        // shown as supplied, not reformatted
  assert.equal(referee.show(vm.attacks[1].p_value), "unavailable: p-value not reported");
  assert.equal(referee.show(vm.attacks[2].statistic), "unavailable: not run");
  assert.equal(vm.verdict.decision, "NOT_SUPPORTED");
  assert.ok(vm.verdict.recognised);
  assert.equal(vm.evidence.length, 2);
  assert.deepEqual(vm.problems, []);
});

test("unknown verdict is shown as supplied, never mapped to a known one", () => {
  const r = example();
  r.verdict.decision = "PROBABLY_TRUE";
  const vm = referee.fromRecord(r);
  assert.equal(vm.verdict.decision, "PROBABLY_TRUE");
  assert.equal(vm.verdict.recognised, false);
  assert.ok(vm.problems.some((p) => p.includes("PROBABLY_TRUE")));
});

test("missing sections are listed as gaps, nothing is zero-filled", () => {
  const vm = referee.fromRecord({ format: "provisional-experience/0", data_mode: "SYNTHETIC" });
  assert.equal(vm.claim, null);
  assert.deepEqual(vm.attacks, []);
  assert.deepEqual(vm.evidence, []);
  assert.equal(vm.verdict.decision, "NO_VERDICT");
  for (const gap of ["claim missing", "attacks_run missing", "verdict missing", "evidence missing"]) assert.ok(vm.problems.includes(gap), gap);
  for (const bad of [null, 7, "x", []]) assert.ok(referee.fromRecord(bad).problems.includes("record is not a JSON object"));
});

test("unknown attack outcome and non-finite numbers are flagged", () => {
  const r = example();
  r.attacks_run[0].outcome = "OK";
  r.attacks_run[1].statistic = Number.NaN;
  const vm = referee.fromRecord(r);
  assert.equal(vm.attacks[0].outcome, "UNRECOGNISED");
  assert.equal(referee.show(vm.attacks[1].statistic), "unavailable: statistic is not finite");
  assert.ok(vm.problems.some((p) => p.startsWith("attacks_run[0].outcome")));
});

test("other formats are read but flagged", () => {
  const r = example();
  r.format = "max-referee/1";
  assert.ok(referee.fromRecord(r).problems.some((p) => p.includes("max-referee/1")));
});

test("stand-in run is labelled stand-in and reports unrun mandatory attacks", () => {
  const plan = { claim_id: "clm_x", statement: "s", canonical_plan_hash: "h1", data_mode: "SYNTHETIC",
                 mandatory_attacks: ["permutation_within_sequence", "split_half_sign", "placebo_lag7"] };
  const run = { run_id: "r1", revision: 2, plan_hash: "h1", result: {
    decision: "SURVIVED_PROTOCOL", reason: "all passed", data_hash: "d".repeat(64), engine: "fixture-engine",
    attacks: [{ test_id: "permutation_within_sequence", version: 1, statistic: 0.05, p_value: 0.001, pass: true, null_method_assumptions: "perm", note: "n" },
              { test_id: "split_half_sign", version: 1, statistic: [0.04, 0.06], p_value: null, pass: false, null_method_assumptions: "halves", note: "n" }],
    attack_envelopes: [{ test_id_version: valid().test_id_version, evidence_hash: valid().evidence_hash }],
    evaluation_run: { code_config_environment_hash: "c".repeat(64), raw_output_hashes: ["r".repeat(64)] },
    sequences: 40, attempts: 4000, eligible_positions: 500 } };
  const vm = referee.fromStandInRun(run, plan);
  assert.equal(vm.source, "STAND_IN_ENGINE");
  assert.ok(vm.problems[0].includes("not a Referee record"));
  assert.equal(vm.data_mode, "SYNTHETIC");
  assert.equal(referee.show(vm.claim.plan_hash), "h1");
  assert.equal(referee.show(vm.claim.revision), "2");
  assert.deepEqual(vm.attacks.map((a) => [referee.show(a.test_id), a.outcome]),
    [["permutation_within_sequence@1", "PASSED"], ["split_half_sign@1", "FAILED"], ["placebo_lag7", "NOT_RUN"]]);
  assert.equal(referee.show(vm.attacks[1].statistic), "0.04 / 0.06");
  assert.equal(vm.verdict.decision, "SURVIVED_PROTOCOL");
  const labels = vm.evidence.map((e) => e.label);
  for (const l of ["data hash", "code/config/environment hash", "raw output hash", "sequences", "engine"]) assert.ok(labels.includes(l), l);
  assert.ok(labels.some((l) => l.startsWith("evidence hash ")));
});

test("stand-in run without a matching plan does not borrow another claim", () => {
  const vm = referee.fromStandInRun({ run_id: "r", revision: 1, plan_hash: "old", result: { decision: "BLOCKED", reason: "x", attacks: [] } }, null);
  assert.equal(referee.show(vm.claim.statement), "unavailable: plan not loaded");
  assert.equal(referee.show(vm.claim.plan_hash), "old");
  assert.equal(vm.verdict.decision, "BLOCKED");
  assert.deepEqual(vm.attacks, []);
});
