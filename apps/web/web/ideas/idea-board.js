// Idea board: loads Research's idea-family results (GET /api/ideas, served read-only by the UI
// server after checking every hash binding) and renders them. Relative URL only. All text is
// set with textContent.

import { CANDIDATE_NOTE, familyHeadline, ideaCard, ideaTitle, scoreboardText } from "./idea-model.js";

/** {status: OK|UNAVAILABLE, reason, families, refused, source}. */
export async function loadIdeas({ timeoutMs = 15000 } = {}) {
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), timeoutMs);
  try {
    const r = await fetch("/api/ideas", { headers: { Accept: "application/json" }, signal: ctl.signal });
    let body = null;
    try { body = await r.json(); } catch { /* non-JSON */ }
    if (r.status !== 200 || !Array.isArray(body?.families)) {
      return { status: "UNAVAILABLE", reason: body?.message || body?.error || `HTTP ${r.status}`, families: [], refused: [] };
    }
    return { status: "OK", families: body.families, refused: body.refused || [], source: body.source,
      proposals: Array.isArray(body.proposals) ? body.proposals : [] };
  } catch (e) {
    return { status: "UNAVAILABLE", reason: e.name === "AbortError" ? "timeout" : e.message, families: [], refused: [] };
  } finally {
    clearTimeout(t);
  }
}

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}

/** Render into ``root``. ``onAsk(result, family)`` runs Heater and the Ref on one idea. */
export function renderIdeas(root, data, { onAsk } = {}) {
  root.replaceChildren();
  const head = el("header", "board-head");
  head.append(el("h2", "board-title", "Idea board"));
  if (data.status !== "OK") {
    head.append(el("p", "board-note", `No idea results: ${data.reason}.`));
    root.append(head);
    return;
  }
  head.append(el("p", "board-note", "Ideas tested together by Research's idea machine. Exploratory: "
    + "\"worth a proper test\" means a lead, never a finding."));
  root.append(head);

  // Heater's own proposals (Max): the model turned a fan's question into ideas; not run yet, no numbers.
  for (const pr of data.proposals || []) {
    const sec = el("section", "idea-family idea-proposed");
    sec.append(el("h3", "idea-family-title", `Proposed by Heater: "${pr.message}"`));
    sec.append(el("p", "board-note", `${pr.ideas.length} ideas the model proposed in Research's grammar. `
      + "Not run yet: sent to Research's idea machine. No results until it runs them together."));
    const grid = el("div", "board-grid");
    for (const idea of pr.ideas) {
      const card = el("article", "mcard icard proposed");
      card.append(el("span", "icard-kind", "PROPOSED BY HEATER"));
      card.append(el("h4", "mcard-title", ideaTitle(idea)));
      card.append(el("p", "mcard-verdict icard-verdict proposed", "Not run yet"));
      grid.append(card);
    }
    sec.append(grid);
    sec.append(el("p", "board-note", `Request ${pr.request_file} · sha256 ${pr.request_sha256.slice(0, 12)}… · `
      + `${pr.model || "model"} · ${pr.created_utc || ""}`));
    root.append(sec);
  }

  for (const f of data.families.filter((x) => x.mode === "development")) {
    const sec = el("section", "idea-family");
    sec.append(el("h3", "idea-family-title", familyHeadline(f)));
    if (f.research_note) sec.append(el("p", "board-note idea-family-note", f.research_note));
    sec.append(el("p", "board-note", CANDIDATE_NOTE));
    const grid = el("div", "board-grid");
    for (const r of f.results) {
      const v = ideaCard(r, f);
      const card = el("article", `mcard icard ${v.verdictKind}`);
      card.append(el("span", "icard-kind", v.kind));
      card.append(el("h4", "mcard-title", v.title));
      card.append(el("p", "icard-numbers", v.numbers));
      card.append(el("p", "mcard-why", v.chance));
      card.append(el("p", `mcard-verdict icard-verdict ${v.verdictKind}`, v.verdict));
      if (v.canAsk && onAsk) {
        const b = el("button", "mcard-ask", "Ask Heater about this idea");
        b.type = "button";
        b.addEventListener("click", () => onAsk(r, f));
        card.append(b);
      }
      grid.append(card);
    }
    sec.append(grid);
    root.append(sec);
  }

  const synth = data.families.filter((x) => x.mode === "synthetic");
  if (synth.length) {
    const sec = el("section", "idea-family");
    sec.append(el("h3", "idea-family-title", "Does the idea machine work? Checked on made-up leagues"));
    sec.append(el("p", "board-note", "SYNTHETIC: leagues with a planted answer key, revealed only after the "
      + "results were written. One league each, so these are counts, not rates."));
    const grid = el("div", "board-grid");
    for (const f of synth) {
      const s = scoreboardText(f);
      const card = el("article", "mcard icard synthetic");
      card.append(el("span", "mcard-sample", "SYNTHETIC"));
      card.append(el("h4", "mcard-title", s.title));
      const ul = el("ul", "icard-tally");
      for (const line of s.lines) ul.append(el("li", "", line));
      card.append(ul);
      card.append(el("p", "mcard-why", `${f.n_ideas} ideas, p after allowing for all ${f.n_ideas}`));
      grid.append(card);
    }
    sec.append(grid);
    root.append(sec);
  }

  if (data.refused.length) {
    const sec = el("section", "idea-family");
    sec.append(el("h3", "idea-family-title", "Not shown"));
    for (const x of data.refused) sec.append(el("p", "board-note", `${x.name}: ${x.reason}`));
    root.append(sec);
  }
}
