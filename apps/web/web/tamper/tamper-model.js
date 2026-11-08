// Tamper test (Experience, 8 Nov 2026): "Corrupt one byte" asks Max's server to flip one byte of a
// sealed file, shows what the validator caught (offset, expected, actual, its error), the DATA_INVALID
// stamp and the new ledger row; "Restore" puts the byte back. Pure model: no DOM.
//
// Max's endpoints (heatcheck/api/tamper.py, docs/DIALOGUE_API.md, 547111f; forwarded by the page server):
//   POST /api/tamper/flip    -> 200 {offset, line, expected, actual, verdict: "DATA_INVALID", error,
//                                    ledger_event_id}; 429 RATE_LIMITED (one flip per 5 s),
//                                    500 NOT_DETECTED (the reader accepted the copy), 503 TAMPER_OFF
//   POST /api/tamper/restore -> 200 {restored: true} (deletes the scratch copy; idempotent)
//   GET  /api/tamper/events  -> 200 {events: [{evidence_id, kind, at_utc, line, offset,
//                                    validator_message, verdict, ...}]} oldest first
// The flip is on a scratch copy: the committed evidence/evidence.jsonl is only read. The new ledger
// row is the TAMPER_ATTEMPT event whose evidence_id is the flip's ledger_event_id. Nothing is
// invented: a missing field shows as "not in the reply".

export const TAMPER_FLIP_URL = "/api/tamper/flip";
export const TAMPER_RESTORE_URL = "/api/tamper/restore";
export const TAMPER_EVENTS_URL = "/api/tamper/events";
/** What Max's server flips (docs/DIALOGUE_API.md): a scratch copy of this file. */
export const TAMPER_TARGET = "evidence/evidence.jsonl (scratch copy; the committed file is only read)";

/** Whether the button shows. Hidden by default (user, 8 Nov): judges open the page with ?tamper=1;
 *  ?tamper=mock runs against in-page MOCK replies. A server started with --no-tamper answers
 *  503 TAMPER_OFF, which the panel says plainly. */
export const TAMPER_DEFAULT_VISIBLE = false;
export function tamperMode(params) {
  const p = params?.get?.("tamper");
  if (p === "mock") return "mock";
  if (p === "0") return "off";
  if (p === "1" || TAMPER_DEFAULT_VISIBLE) return "live";
  return "off";
}

const str = (x) => (typeof x === "string" ? x.trim() : "");
const shown = (x) => (x === null || x === undefined || x === "" ? null : typeof x === "string" ? x : JSON.stringify(x));
export const NOT_IN_REPLY = "not in the reply";

/** One ledger row for the table: a TAMPER_ATTEMPT event (Max's /api/tamper/events), a flat row, or a
 *  ledger entry ({evidence_id, identity: {...}}). ``fullId`` is kept to find the new row. */
export function ledgerRowView(row) {
  if (!row || typeof row !== "object") return null;
  const id = row.identity && typeof row.identity === "object" ? row.identity : {};
  const claim = str(row.kind) || str(row.claim_id) || str(id.claim?.claim_id) || str(id.claim_id) || str(id.kind);
  const decision = str(row.verdict) || str(row.decision) || str(id.decision) || str(id.verdict);
  const reason = str(row.validator_message) || str(row.reason) || str(id.reason) || str(id.validator_message);
  const eid = str(row.evidence_id) || str(row.id);
  const at = str(row.at_utc) || str(row.created_at_utc) || str(row.recorded_at) || str(id.at_utc);
  if (!claim && !decision && !eid) return null;
  return { claim: claim || "?", decision: decision || "?", reason, id: eid ? eid.slice(0, 12) : "?", at, fullId: eid };
}

/** The table rows after a flip: up to ``keep`` earlier events, then the new one (the event whose id is
 *  the flip's ledger_event_id). ``found`` is false when the events list has no such event. */
export function eventRows(eventsBody, ledgerEventId, keep = 3) {
  const all = (Array.isArray(eventsBody?.events) ? eventsBody.events : []).map(ledgerRowView).filter(Boolean);
  const k = ledgerEventId ? all.findIndex((r) => r.fullId === ledgerEventId) : -1;
  if (k < 0) return { recent: all.slice(-keep), row: null, found: false };
  return { recent: all.slice(Math.max(0, k - keep), k), row: all[k], found: true };
}

/** The panel's view of a flip reply. ``ok`` is false when the reply is not a flip result at all
 *  (then ``problem`` says why and no values are shown). */
export function flipView(body, { httpStatus = 200, mock = false } = {}) {
  const b = body && typeof body === "object" ? body : null;
  const has = b && ["offset", "expected", "actual"].some((k) => k in b);
  if (!has) {
    const code = b ? str(b.error) : "";
    const why = b ? str(b.message) : "";
    // Max's codes, in plain words; NOT_DETECTED is the one that matters most and is never softened
    const plain = { RATE_LIMITED: "one flip per 5 seconds; wait a moment and try again",
      NOT_DETECTED: "THE LEDGER READER ACCEPTED THE TAMPERED COPY (the check failed to catch it)",
      TAMPER_OFF: "the tamper demo is off on this server" }[code];
    const detail = plain || why || code;
    return { ok: false, code, notDetected: code === "NOT_DETECTED",
      problem: `the server did not report a flipped byte${httpStatus !== 200 ? ` (HTTP ${httpStatus}${detail ? `: ${detail}` : ""})` : detail ? ` (${detail})` : ""}` };
  }
  const err = str(b.validator_error) || str(b.error_message) || (typeof b.error === "string" && b.error !== "DATA_INVALID" ? str(b.error) : "") || str(b.message);
  const verdict = str(b.verdict) || str(b.decision) || (b.error === "DATA_INVALID" ? "DATA_INVALID" : "");
  const rows = [["File", shown(b.file) ?? (mock ? NOT_IN_REPLY : TAMPER_TARGET)]];
  if (b.line !== undefined) rows.push(["Line", shown(b.line)]);
  rows.push(
    ["Offset", Number.isInteger(b.offset) ? `${b.offset.toLocaleString("en-US")} (0x${b.offset.toString(16).toUpperCase()})` : shown(b.offset) ?? NOT_IN_REPLY],
    ["Expected", shown(b.expected) ?? NOT_IN_REPLY],
    ["Actual", shown(b.actual) ?? NOT_IN_REPLY],
    ["Validator error", err || NOT_IN_REPLY],
  );
  return {
    ok: true, mock, rows,
    error: err,
    verdict,
    caught: verdict === "DATA_INVALID",
    eventId: str(b.ledger_event_id),
    row: ledgerRowView(b.ledger_row || b.row || b.entry),
  };
}

/** The panel's view of a restore reply. */
export function restoreView(body, { httpStatus = 200 } = {}) {
  const b = body && typeof body === "object" ? body : null;
  if (b?.restored === true) return { ok: true, text: str(b.message) || "Restored: the corrupted copy is deleted. The committed ledger was only read and never changed." };
  const why = b ? str(b.message) || str(b.error) : "";
  return { ok: false, text: `Restore failed${httpStatus !== 200 ? ` (HTTP ${httpStatus})` : ""}${why ? `: ${why}` : ""}. The file may still be corrupted.` };
}

/** The Ref's line for a caught flip, in the personality's DATA_INVALID wording. */
export function tamperRefLine(view, personality) {
  if (view.notDetected) return "The check failed: a byte was flipped and the ledger reader accepted it. Don't trust a ruling until this is fixed.";
  if (!view.ok) return `Can't run the tamper test: ${view.problem}.`;
  if (!view.caught) return `The server flipped a byte but did not report DATA_INVALID (verdict: ${view.verdict || "none"}).`;
  const tpl = personality?.ref_templates?.DATA_INVALID || "No ruling. The data failed its checks: {reason}.";
  const reason = (view.error || "the validator refused the file").replace(/\.$/, "");
  return tpl.replace("{reason}", reason);
}

/** POST with no body (GET for the events list); returns {status, body} (body null when the reply is
 *  not JSON). Network errors become status 0. */
export async function postTamper(url, fetchImpl = globalThis.fetch, method = "POST") {
  try {
    const r = await fetchImpl(url, { method, headers: { Accept: "application/json" } });
    let body = null;
    try { body = await r.json(); } catch { body = null; }
    return { status: r.status, body };
  } catch (e) {
    return { status: 0, body: { message: e?.message || "network error" } };
  }
}

// ---- ?tamper=mock: in-page replies, labelled MOCK on the panel; no request is sent, no file changes.
// Same shape as Max's reply; every text value says MOCK.
export const MOCK_FLIP = Object.freeze({
  mock: true,
  file: "MOCK: evidence/evidence.jsonl",
  offset: 4096,
  line: 3,
  expected: "0x53 'S'",
  actual: "0x52 'R'",
  verdict: "DATA_INVALID",
  error: "MOCK: ledger line 3: identity hash mismatch (tampered)",
  ledger_event_id: "mock00000000000000000000000000000000000000000000000000000000000001",
});
export const MOCK_RESTORE = Object.freeze({ mock: true, restored: true, message: "MOCK: restored; no file was changed." });
const MOCK_EVENT = Object.freeze({ evidence_id: MOCK_FLIP.ledger_event_id, kind: "TAMPER_ATTEMPT", at_utc: "MOCK",
  line: 3, offset: 4096, validator_message: MOCK_FLIP.error, verdict: "DATA_INVALID" });

/** A fetch stand-in for ?tamper=mock and the tests. */
export function mockTamperFetch() {
  let events = [];
  return async (url) => {
    const json = (status, body) => ({ status, ok: status < 300, json: async () => body });
    if (url === TAMPER_EVENTS_URL) return json(200, { events });
    if (url === TAMPER_FLIP_URL) { events = [MOCK_EVENT]; return json(200, MOCK_FLIP); }
    if (url === TAMPER_RESTORE_URL) return json(200, MOCK_RESTORE);   // idempotent, like Max's
    return json(404, { error: "NOT_FOUND", message: url });
  };
}
