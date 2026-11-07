// Injected into the active tab only when the user clicks the extension (activeTab).
// Reads the current selection and any tables it touches. Returns data; never acts on page content.
(() => {
  const MAX_TEXT = 200000, MAX_TABLES = 10, MAX_ROWS = 200, MAX_COLS = 40;
  const sel = window.getSelection();
  const text = sel ? sel.toString().slice(0, MAX_TEXT) : "";
  const tables = [];
  if (sel && sel.rangeCount) {
    const range = sel.getRangeAt(0);
    for (const t of document.querySelectorAll("table")) {
      if (tables.length >= MAX_TABLES) break;
      if (!range.intersectsNode(t)) continue;
      const rows = [];
      for (const tr of Array.from(t.rows).slice(0, MAX_ROWS)) {
        rows.push(Array.from(tr.cells).slice(0, MAX_COLS).map((c) => c.innerText.trim().slice(0, 500)));
      }
      tables.push({ rows, truncated: t.rows.length > MAX_ROWS });
    }
  }
  return { url: location.href, title: document.title.slice(0, 300), selected_text: text, tables,
           retrieved_utc: new Date().toISOString(), in_frame: window !== window.top };
})();
