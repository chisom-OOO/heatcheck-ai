// Referee evidence view model. Pure functions: no DOM, no network, no statistics.
//
// PROVISIONAL. Max owns the Referee evidence record format and has not delivered it yet. Until
// then this module defines the four things the UI shows (claim, attacks run, verdict, evidence)
// and two adapters into that view:
//   fromRecord(record)        a record in the provisional shape below (replace when Max's lands)
//   fromStandInRun(run, plan) today's stand-in engine output (server/engine_fixture.py),
//                             always labelled as stand-in, never as a Referee record
// Values are displayed exactly as supplied. Nothing missing is zero-filled: it is shown as
// unavailable with a reason, and every gap is listed in `problems`.
//
// Provisional record shape (format "provisional-experience/0"):
//   { format, data_mode,
//     claim:       { claim_id, statement, plan_hash, revision },
//     attacks_run: [ { test_id, outcome, statistic, p_value, method, reason } ],
//     verdict:     { decision, reason },
//     evidence:    [ { label, value, kind } ] }

export const FORMAT_STATUS = "PROVISIONAL: awaiting Max's Referee evidence record format";
export const PROVISIONAL_FORMAT = "provisional-experience/0";

export const VERDICTS = {
  SURVIVED_PROTOCOL: ["✓", "Survived every registered check"],
  NOT_SUPPORTED: ["✕", "Not supported by the planned checks"],
  INSUFFICIENT_EVIDENCE: ["?", "Not enough evidence to tell"],
  DATA_INVALID: ["!", "Data invalid"],
  BLOCKED: ["■", "Blocked: could not run"],
};
export const ATTACK_OUTCOMES = ["PASSED", "FAILED", "NOT_RUN", "ERROR"];
const DATA_MODES = ["SYNTHETIC", "RECORDED_MARKET", "LIVE_MARKET", "REAL_NBA_RETROSPECTIVE"];

const UNAVAILABLE = (reason) => ({ available: false, reason });
const shown = (v) => ({ available: true, value: v });

function isObj(o) { return o !== null && typeof o === "object" && !Array.isArray(o); }

function field(obj, key, problems, where) {
  if (!isObj(obj) || obj[key] === undefined || obj[key] === null || obj[key] === "") {
    problems.push(`${where}.${key} missing`);
    return UNAVAILABLE(`${key} not supplied`);
  }
  return shown(obj[key]);
}

function numberOrText(v, what) {
  if (v === null || v === undefined) return UNAVAILABLE(`${what} not reported`);
  if (typeof v === "number" && !Number.isFinite(v)) return UNAVAILABLE(`${what} is not finite`);
  if (Array.isArray(v)) return shown(v.map((x) => String(x)).join(" / "));
  return shown(String(v));
}

function verdictView(decision, reason, problems) {
  if (decision === null || decision === undefined || decision === "") {
    problems.push("verdict.decision missing");
    return { decision: "NO_VERDICT", recognised: false, icon: "•", plain: "No verdict in this record", reason: reason ?? null };
  }
  const meta = VERDICTS[decision];
  if (!meta) {
    problems.push(`verdict.decision ${JSON.stringify(decision)} is not a recognised verdict`);
    return { decision: String(decision), recognised: false, icon: "•", plain: "Unrecognised verdict: shown as supplied", reason: reason ?? null };
  }
  return { decision, recognised: true, icon: meta[0], plain: meta[1], reason: reason ?? null };
}

function attackView(a, i, problems) {
  const where = `attacks_run[${i}]`;
  if (!isObj(a)) { problems.push(`${where} is not an object`); return null; }
  let outcome = a.outcome;
  if (!ATTACK_OUTCOMES.includes(outcome)) {
    problems.push(`${where}.outcome ${JSON.stringify(outcome)} is not one of ${ATTACK_OUTCOMES.join("/")}`);
    outcome = "UNRECOGNISED";
  }
  return {
    test_id: field(a, "test_id", problems, where),
    outcome,
    statistic: outcome === "NOT_RUN" ? UNAVAILABLE("not run") : numberOrText(a.statistic, "statistic"),
    p_value: outcome === "NOT_RUN" ? UNAVAILABLE("not run") : numberOrText(a.p_value, "p-value"),
    method: a.method ? shown(String(a.method)) : UNAVAILABLE("method not stated"),
    reason: a.reason ? String(a.reason) : null,
  };
}

/** View model from a provisional Referee evidence record. Never throws on bad content. */
export function fromRecord(record) {
  const problems = [];
  if (!isObj(record)) {
    return { source: "REFEREE_RECORD", format_status: FORMAT_STATUS, data_mode: null, claim: null, attacks: [],
             verdict: verdictView(null, null, problems), evidence: [], problems: ["record is not a JSON object", ...problems] };
  }
  if (record.format !== PROVISIONAL_FORMAT) {
    problems.push(`format ${JSON.stringify(record.format ?? null)} is not ${PROVISIONAL_FORMAT}; fields may be misread`);
  }
  const dataMode = DATA_MODES.includes(record.data_mode) ? record.data_mode : null;
  if (!dataMode) problems.push(`data_mode ${JSON.stringify(record.data_mode ?? null)} not recognised`);

  let claim = null;
  if (isObj(record.claim)) {
    claim = {
      claim_id: field(record.claim, "claim_id", problems, "claim"),
      statement: field(record.claim, "statement", problems, "claim"),
      plan_hash: field(record.claim, "plan_hash", problems, "claim"),
      revision: record.claim.revision === undefined ? UNAVAILABLE("revision not supplied") : shown(record.claim.revision),
    };
  } else problems.push("claim missing");

  let attacks = [];
  if (Array.isArray(record.attacks_run)) {
    attacks = record.attacks_run.map((a, i) => attackView(a, i, problems)).filter(Boolean);
    if (!attacks.length) problems.push("attacks_run is empty: no attack was reported");
  } else problems.push("attacks_run missing");

  const v = isObj(record.verdict) ? record.verdict : {};
  if (!isObj(record.verdict)) problems.push("verdict missing");
  const verdict = verdictView(v.decision, v.reason, problems);

  let evidence = [];
  if (Array.isArray(record.evidence)) {
    evidence = record.evidence.map((e, i) => isObj(e)
      ? { label: String(e.label ?? `evidence[${i}]`), value: numberOrText(e.value, "value"), kind: String(e.kind ?? "other") }
      : (problems.push(`evidence[${i}] is not an object`), null)).filter(Boolean);
    if (!evidence.length) problems.push("evidence is empty");
  } else problems.push("evidence missing");

  return { source: "REFEREE_RECORD", format_status: FORMAT_STATUS, data_mode: dataMode, claim, attacks, verdict, evidence, problems };
}

/** View model from today's stand-in engine run (GET /api/run/<id>) and its confirmed plan. */
export function fromStandInRun(run, plan) {
  const problems = ["source is the stand-in engine (server/engine_fixture.py), not a Referee record"];
  const res = (run && run.result) || {};
  const p = plan || {};
  const claim = {
    claim_id: p.claim_id ? shown(p.claim_id) : UNAVAILABLE("plan not loaded"),
    statement: p.statement ? shown(p.statement) : UNAVAILABLE("plan not loaded"),
    plan_hash: run && run.plan_hash ? shown(run.plan_hash) : (p.canonical_plan_hash ? shown(p.canonical_plan_hash) : UNAVAILABLE("plan hash not reported")),
    revision: run && run.revision !== undefined ? shown(run.revision) : UNAVAILABLE("revision not reported"),
  };
  const reported = Array.isArray(res.attacks) ? res.attacks : [];
  const attacks = reported.map((a) => ({
    test_id: shown(a.version ? `${a.test_id}@${a.version}` : a.test_id),
    outcome: a.pass === true ? "PASSED" : a.pass === false ? "FAILED" : "ERROR",
    statistic: numberOrText(a.statistic, "statistic"),
    p_value: numberOrText(a.p_value, "p-value"),
    method: a.null_method_assumptions ? shown(a.null_method_assumptions) : UNAVAILABLE("method not stated"),
    reason: a.note || null,
  }));
  const ran = new Set(reported.map((a) => a.test_id));
  for (const m of p.mandatory_attacks || []) {
    if (!ran.has(m)) {
      attacks.push({ test_id: shown(m), outcome: "NOT_RUN", statistic: UNAVAILABLE("not run"), p_value: UNAVAILABLE("not run"),
                     method: UNAVAILABLE("not run"), reason: "mandatory in the confirmed plan but not reported by the engine" });
    }
  }
  const ev = [];
  const er = res.evaluation_run || {};
  const add = (label, value, kind) => ev.push({ label, value: numberOrText(value, label), kind });
  add("data hash", res.data_hash, "hash");
  add("code/config/environment hash", er.code_config_environment_hash, "hash");
  add("raw output hash", (er.raw_output_hashes || [])[0], "hash");
  for (const a of res.attack_envelopes || []) add(`evidence hash ${a.test_id_version}`, a.evidence_hash, "hash");
  if (res.effect_estimate !== undefined) add(`effect estimate (${res.effect_units || "units not stated"})`, res.effect_estimate, "estimate");
  if (res.interval !== undefined) add(`95% interval${res.interval_method ? ` (${res.interval_method})` : ""}`, res.interval, "estimate");
  if (res.sequences !== undefined) add("sequences", res.sequences, "count");
  if (res.attempts !== undefined) add("attempts", res.attempts, "count");
  if (res.eligible_positions !== undefined) add("eligible streak positions", res.eligible_positions, "count");
  if (res.engine) add("engine", res.engine, "version");
  return {
    source: "STAND_IN_ENGINE", format_status: FORMAT_STATUS,
    data_mode: [res.data_mode, p.data_mode].find((m) => DATA_MODES.includes(m)) || null,
    claim, attacks, verdict: verdictView(res.decision, res.reason, problems), evidence: ev, problems,
  };
}

/** Text for one displayed value: the value itself, or "unavailable: <reason>". */
export function show(v) {
  if (!v) return "unavailable";
  return v.available ? String(v.value) : `unavailable: ${v.reason}`;
}
