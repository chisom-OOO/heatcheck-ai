// Safer-gambling notice on the demo page (Experience, 8 Nov 2026).
//
// The wording has ONE source: Max's web/responsible_use.json ({"short", "full"}). This module only
// loads it; nothing here writes or changes the text. Where it shows:
//   - page footer, always: the short text (demo.html carries the same text statically, so it shows
//     even before or without JavaScript; a test keeps the two identical);
//   - "Tonight's games" board header: the full text;
//   - the first market Ask or what-if of a browser session: the full text, once, until dismissed.

/** Max's single source of the wording, next to this file. */
export const RESPONSIBLE_URL = "responsible_use.json";

/** {short, full} from Max's file, or null if it cannot be read (the static footer then stands). */
export async function loadResponsibleUse({ fetchImpl = globalThis.fetch, url = RESPONSIBLE_URL } = {}) {
  try {
    const r = await fetchImpl(url, { headers: { Accept: "application/json" } });
    if (!r.ok) return null;
    const doc = await r.json();
    const ok = (s) => typeof s === "string" && s.trim().length > 0;
    return ok(doc?.short) && ok(doc?.full) ? { short: doc.short, full: doc.full } : null;
  } catch {
    return null;
  }
}

export const FIRST_ASK_KEY = "heatcheck.responsible-use.shown";
const shownHere = new Set(); // when sessionStorage is unavailable (private mode, blocked storage)

/** True the first time this is called in a browser session, false after. ``storage`` is
 *  sessionStorage or null; any storage error falls back to this page view's memory. */
export function firstTimeThisSession(storage, key = FIRST_ASK_KEY) {
  if (shownHere.has(key)) return false;
  shownHere.add(key);
  try {
    if (storage?.getItem(key)) return false;
    storage?.setItem(key, "1");
  } catch { /* memory only */ }
  return true;
}
