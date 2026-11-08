// Responsible-use notice (Max, 8 Nov 2026). The text has one source, responsible_use.json; the page
// footer in demo.html carries the short form as static HTML (tested equal to the JSON) so it shows
// even if scripts fail. This module loads the JSON for the board header and the one-time Ask notice.

export const RU_URL = "responsible_use.json";
export const ASK_NOTICE_KEY = "heatcheck.responsibleUse.askNoticeShown";

/** {short, full} from the JSON, or null if it cannot be read (the footer still shows). */
export async function loadResponsibleUse(fetchImpl = (...a) => fetch(...a)) {
  try {
    const r = await fetchImpl(RU_URL, { headers: { Accept: "application/json" } });
    if (!r.ok) return null;
    const d = await r.json();
    return typeof d?.short === "string" && typeof d?.full === "string" ? { short: d.short, full: d.full } : null;
  } catch {
    return null;
  }
}

/** True the first time in this browser session; storage failures still show it once per page. */
export function firstAskThisSession(storage, memo) {
  if (memo.shown) return false;
  memo.shown = true;
  try {
    if (storage?.getItem(ASK_NOTICE_KEY)) return false;
    storage?.setItem(ASK_NOTICE_KEY, "1");
  } catch { /* private window or blocked storage: once per page view */ }
  return true;
}
