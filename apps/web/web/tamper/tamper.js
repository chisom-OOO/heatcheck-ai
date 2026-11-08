// Tamper panel: what the validator caught, and the ledger with the new row. DOM only; the values
// come from tamper-model.js views (the server's reply, never filled in here).

import { ledgerRowView } from "./tamper-model.js";

const el = (tag, cls, text) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
};

/** Draw the panel for a flip view. ``recent`` are the page's last ledger entries (shown above the new
 *  row so it is seen arriving); ``status`` is the line under the panel. */
export function renderTamper(root, view, { recent = [], status = "" } = {}) {
  const parts = [];
  if (view?.mock) parts.push(el("p", "tamper-mock", "MOCK REPLY: no request was sent and no file was changed"));
  if (view && !view.ok) {
    parts.push(el("p", "tamper-problem", `Nothing was flipped: ${view.problem}.`));
  } else if (view) {
    const dl = el("dl", "tamper-facts");
    for (const [k, v] of view.rows) {
      dl.append(el("dt", "", k), el("dd", k === "Validator error" ? "tamper-error" : "", v));
    }
    parts.push(dl);
    const table = el("table", "tamper-ledger");
    table.append(el("caption", "", "Evidence ledger"));
    const head = el("tr");
    for (const h of ["Claim", "Decision", "Evidence id", "Reason"]) head.append(el("th", "", h));
    const thead = el("thead");
    thead.append(head);
    table.append(thead);
    const body = el("tbody");
    const addRow = (r, isNew) => {
      const tr = el("tr", isNew ? "tamper-new" : "");
      tr.append(el("td", "", r.claim), el("td", "", r.decision), el("td", "mono", r.id), el("td", "", r.reason));
      body.append(tr);
    };
    recent.map(ledgerRowView).filter(Boolean).forEach((r) => addRow(r, false));
    if (view.row) addRow(view.row, true);
    table.append(body);
    parts.push(table);
    if (!view.row) parts.push(el("p", "tamper-problem", "The reply has no new ledger row."));
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
