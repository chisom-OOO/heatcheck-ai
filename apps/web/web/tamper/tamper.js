// Tamper panel: what the validator caught, and the ledger with the new row. DOM only; the values
// come from tamper-model.js views (the server's reply, never filled in here).

import { ledgerRowView } from "./tamper-model.js";

const el = (tag, cls, text) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
};

/** Draw the panel for a flip view. ``recent`` are the earlier tamper-ledger rows (shown above the new
 *  row so it is seen arriving), ``row`` the new one (from GET /api/tamper/events), ``rowNote`` why it
 *  is missing; ``status`` is the line under the panel. */
export function renderTamper(root, view, { recent = [], row = null, rowNote = "", status = "" } = {}) {
  const parts = [];
  if (view?.mock) parts.push(el("p", "tamper-mock", "MOCK REPLY: no request was sent and no file was changed"));
  if (view?.notDetected) {
    parts.push(el("p", "tamper-problem tamper-alarm", `CHECK FAILED: ${view.problem}.`));
  } else if (view && !view.ok) {
    parts.push(el("p", "tamper-problem", `Nothing was flipped: ${view.problem}.`));
  } else if (view) {
    const dl = el("dl", "tamper-facts");
    for (const [k, v] of view.rows) {
      dl.append(el("dt", "", k), el("dd", k === "Validator error" ? "tamper-error" : "", v));
    }
    parts.push(dl);
    const table = el("table", "tamper-ledger");
    table.append(el("caption", "", "Tamper ledger (hash-chained, logs/tamper_events.jsonl)"));
    const head = el("tr");
    for (const h of ["Entry", "Verdict", "Evidence id", "Validator message"]) head.append(el("th", "", h));
    const thead = el("thead");
    thead.append(head);
    table.append(thead);
    const body = el("tbody");
    const addRow = (r, isNew) => {
      const tr = el("tr", isNew ? "tamper-new" : "");
      tr.append(el("td", "", r.claim), el("td", "", r.decision), el("td", "mono", r.id), el("td", "", r.reason));
      body.append(tr);
    };
    const view1 = (r) => (r && "fullId" in r ? r : ledgerRowView(r));
    recent.map(view1).filter(Boolean).forEach((r) => addRow(r, false));
    const fresh = view1(row) || view.row;
    if (fresh) addRow(fresh, true);
    table.append(body);
    parts.push(table);
    if (!fresh) parts.push(el("p", "tamper-problem", rowNote || "The new ledger row is not in the reply."));
  }
  parts.push(el("p", "tamper-status", status));
  root.replaceChildren(...parts);
}

/** Replace only the status line (after a restore). */
export function setTamperStatus(root, text, ok) {
  let p = root.querySelector(".tamper-status");
  if (!p) { p = el("p", "tamper-status"); root.append(p); }
  p.textContent = text;
  p.classList.toggle("bad", ok === false);
  p.classList.toggle("good", ok === true);
}
