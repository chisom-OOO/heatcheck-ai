const APP = "http://127.0.0.1:8765";
const $ = (id) => document.getElementById(id);
chrome.storage.session.get("code").then((v) => { if (v.code) $("code").value = v.code; });
function show(msg, cls) { $("out").textContent = msg; $("out").className = cls; }
$("send").addEventListener("click", async () => {
  const code = $("code").value.trim();
  if (!/^[0-9a-f]{32}$/.test(code)) return show("Enter the 32-character pairing code from the workspace.", "err");
  await chrome.storage.session.set({ code });
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  let grabbed;
  try {
    const [res] = await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ["grab.js"] });
    grabbed = res && res.result;
  } catch (e) {
    return show("This page can't be read (browser-restricted page, PDF viewer or store page): " + e.message, "err");
  }
  if (!grabbed) return show("Nothing was returned from the page.", "err");
  if (!grabbed.selected_text.trim() && !grabbed.tables.length) return show("Nothing is selected on this page. Select text or a table first.", "err");
  try {
    const r = await fetch(APP + "/api/page", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: code, origin: "extension", ...grabbed }) });
    const d = await r.json();
    if (!r.ok) return show(`Refused: ${d.message || r.status}`, "err");
    show(`Attached (${d.source.bytes} bytes, sha256 ${d.source.sha256.slice(0, 10)}…). The workspace plan was revoked if one was confirmed.`, "ok");
  } catch (e) {
    show("Heat Check workspace is not reachable at " + APP + ".", "err");
  }
});
