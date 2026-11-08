// Tamper test (Experience, 8 Nov 2026): "Corrupt one byte" asks Max's server to flip one byte of a
// sealed file, shows what the validator caught (offset, expected, actual, its error), the DATA_INVALID
// stamp and the new ledger row; "Restore" puts the byte back. Pure model: no DOM.
//
// Max's endpoints have not landed yet. The reply shapes below are PROVISIONAL (Experience's proposal,
// to be matched to Max's):
//   POST /api/tamper/flip    -> {file, offset, expected, actual, error, verdict: "DATA_INVALID",
//                                ledger_row: {evidence_id, claim_id, decision, reason, recorded_at}}
//   POST /api/tamper/restore -> {restored: true, file?, message?}
// Also read: validator_error / message for the error, row / entry for the ledger row (flat, or a
// ledger entry with identity.*), and the same fields in a non-2xx JSON body (an ApiError carries
// them as extra keys). Nothing is invented: a missing field shows as "not in the reply".

export const TAMPER_FLIP_URL = "/api/tamper/flip";
export const TAMPER_RESTORE_URL = "/api/tamper/restore";

/** Whether the button shows. Hidden by default until Max's endpoint lands (decision: if it is not
 *  there by 08:45, the button stays behind ?tamper=1). ?tamper=mock runs against MOCK replies. */
export const TAMPER_DEFAULT_VISIBLE = false;
export function tamperMode(params) {
  const p = params?.get?.("tamper");
  if (p === "mock") return "mock";
  if (p === "1" || TAMPER_DEFAULT_VISIBLE) return "live";
  return "off";
}

const str = (x) => (typeof x === "string" ? x.trim() : "");
const shown = (x) => (x === null || x === undefined || x === "" ? null : typeof x === "string" ? x : JSON.stringify(x));
export const NOT_IN_REPLY = "not in the reply";

/** One ledger row for the table, from a flat row or a ledger entry ({evidence_id, identity: {...}}). */
export function ledgerRowView(row) {
  if (!row || typeof row !== "object") return null;
  const id = row.identity && typeof row.identity === "object" ? row.identity : {};
  const claim = str(row.claim_id) || str(id.claim?.claim_id) || str(id.claim_id);
  const decision = str(row.decision) || str(id.decision);
  const reason = str(row.reason) || str(id.reason);
  const eid = str(row.evidence_id) || str(row.id);
  const at = str(row.recorded_at) || str(row.created_at) || str(id.recorded_at);
  if (!claim && !decision && !eid) return null;
  return { claim: claim || "?", decision: decision || "?", reason, id: eid ? eid.slice(0, 12) : "?", at };
}

/** The panel's view of a flip reply. ``ok`` is false when the reply is not a flip result at all
 *  (then ``problem`` says why and no values are shown). */
export function flipView(body, { httpStatus = 200, mock = false } = {}) {
  const b = body && typeof body === "object" ? body : null;
  const has = b && ["offset", "expected", "actual"].some((k) => k in b);
  if (!has) {
    const why = b ? str(b.message) || str(b.error) : "";
    return { ok: false, problem: `the server did not report a flipped byte${httpStatus !== 200 ? ` (HTTP ${httpStatus}${why ? `: ${why}` : ""})` : why ? ` (${why})` : ""}` };
  }
  const err = str(b.validator_error) || str(b.error_message) || (typeof b.error === "string" && b.error !== "DATA_INVALID" ? str(b.error) : "") || str(b.message);
  const verdict = str(b.verdict) || str(b.decision) || (b.error === "DATA_INVALID" ? "DATA_INVALID" : "");
  return {
    ok: true, mock,
    rows: [
      ["File", shown(b.file) ?? NOT_IN_REPLY],
      ["Offset", Number.isInteger(b.offset) ? `${b.offset.toLocaleString("en-US")} (0x${b.offset.toString(16).toUpperCase()})` : shown(b.offset) ?? NOT_IN_REPLY],
      ["Expected", shown(b.expected) ?? NOT_IN_REPLY],
      ["Actual", shown(b.actual) ?? NOT_IN_REPLY],
      ["Validator error", err || NOT_IN_REPLY],
    ],
    error: err,
    verdict,
    caught: verdict === "DATA_INVALID",
    row: ledgerRowView(b.ledger_row || b.row || b.entry),
  };
}

/** The panel's view of a restore reply. */
export function restoreView(body, { httpStatus = 200 } = {}) {
  const b = body && typeof body === "object" ? body : null;
  if (b?.restored === true) return { ok: true, text: str(b.message) || `Restored${str(b.file) ? ` ${b.file}` : ""}: the byte is back and the file matches its seal again.` };
  const why = b ? str(b.message) || str(b.error) : "";
  return { ok: false, text: `Restore failed${httpStatus !== 200 ? ` (HTTP ${httpStatus})` : ""}${why ? `: ${why}` : ""}. The file may still be corrupted.` };
}

/** The Ref's line for a caught flip, in the personality's DATA_INVALID wording. */
export function tamperRefLine(view, personality) {
  if (!view.ok) return `Can't run the tamper test: ${view.problem}.`;
  if (!view.caught) return `The server flipped a byte but did not report DATA_INVALID (verdict: ${view.verdict || "none"}).`;
  const tpl = personality?.ref_templates?.DATA_INVALID || "No ruling. The data failed its checks: {reason}.";
  const reason = (view.error || "the validator refused the file").replace(/\.$/, "");
  return tpl.replace("{reason}", reason);
}

/** POST with no body; returns {status, body} (body null when the reply is not JSON). Network errors
 *  become status 0. */
export async function postTamper(url, fetchImpl = globalThis.fetch) {
  try {
    const r = await fetchImpl(url, { method: "POST", headers: { Accept: "application/json" } });
    let body = null;
    try { body = await r.json(); } catch { body = null; }
    return { status: r.status, body };
  } catch (e) {
    return { status: 0, body: { message: e?.message || "network error" } };
  }
}

// ---- ?tamper=mock: in-page replies, labelled MOCK on the panel; no request is sent, no file changes.
export const MOCK_FLIP = Object.freeze({
  mock: true,
  file: "MOCK: ledger/evidence.jsonl",
  offset: 4096,
  expected: "0x22",
  actual: "0x23",
  error: "MOCK: ledger line 3: entry hash mismatch (tampered)",
  verdict: "DATA_INVALID",
  ledger_row: { evidence_id: "mock0000000000000000", claim_id: "TAMPER-TEST", decision: "DATA_INVALID",
    reason: "MOCK: entry hash mismatch", recorded_at: "MOCK" },
});
export const MOCK_RESTORE = Object.freeze({ mock: true, restored: true, message: "MOCK: restored; no file was changed." });

/** A fetch stand-in for ?tamper=mock and the tests. */
export function mockTamperFetch() {
  let flipped = false;
  return async (url) => {
    const json = (status, body) => ({ status, ok: status < 300, json: async () => body });
    if (url === TAMPER_FLIP_URL) { flipped = true; return json(200, MOCK_FLIP); }
    if (url === TAMPER_RESTORE_URL) {
      if (!flipped) return json(409, { error: "NOTHING_TO_RESTORE", message: "MOCK: no byte is flipped" });
      flipped = false;
      return json(200, MOCK_RESTORE);
    }
    return json(404, { error: "NOT_FOUND", message: url });
  };
}
