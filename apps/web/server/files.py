"""Bounded, explicit file intake: type/size/content checks, preview, provenance, safe export."""
import csv
import hashlib
import io
import json
import re

from .timefmt import now_z

MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 50_000
MAX_COLS = 200
ALLOWED_EXT = {".csv", ".json", ".txt"}
BLOCKED_MAGIC = [
    (b"PK\x03\x04", "archive/Office container (zip, docx, xlsx, jar)"),
    (b"\x1f\x8b", "gzip archive"),
    (b"Rar!", "rar archive"),
    (b"7z\xbc\xaf", "7z archive"),
    (b"MZ", "Windows executable"),
    (b"\x7fELF", "ELF executable"),
    (b"%PDF", "PDF (not supported in this build)"),
    (b"\xd0\xcf\x11\xe0", "legacy Office/macro container"),
]
FORMULA_PREFIX = ("=", "+", "-", "@", "\t", "\r")


class FileRejected(ValueError):
    pass


def _ext(name):
    m = re.search(r"(\.[A-Za-z0-9]+)$", name or "")
    return m.group(1).lower() if m else ""


def safe_name(name):
    """Never trust a path: keep the basename only and strip traversal / control chars."""
    base = re.split(r"[\\/]", name or "")[-1]
    base = re.sub(r"[\x00-\x1f]", "", base).strip(". ")
    if not base or ".." in base:
        raise FileRejected("unsafe file name")
    return base[:120]


def ingest(name, data, declared_mime=None, meta=None):
    name = safe_name(name)
    if len(data) == 0:
        raise FileRejected("empty file")
    if len(data) > MAX_BYTES:
        raise FileRejected(f"file is {len(data)} bytes; limit is {MAX_BYTES}")
    ext = _ext(name)
    if ext not in ALLOWED_EXT:
        raise FileRejected(f"extension {ext or '(none)'} not allowed; allowed: {sorted(ALLOWED_EXT)}")
    for magic, label in BLOCKED_MAGIC:
        if data.startswith(magic):
            raise FileRejected(f"content looks like {label}; rejected despite extension {ext}")
    if b"\x00" in data[:4096]:
        raise FileRejected("binary content in a text-type file")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise FileRejected("not valid UTF-8 text") from None
    if declared_mime and declared_mime.split(";")[0].strip() not in (
        "text/csv", "application/json", "text/plain", "application/vnd.ms-excel", "application/octet-stream", ""
    ):
        raise FileRejected(f"declared MIME type {declared_mime!r} does not match a text data file")

    prov = {
        "file_name": name,
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "retrieved_utc": now_z(),
        "declared_mime": declared_mime,
        "source_date": (meta or {}).get("source_date"),
        "units": (meta or {}).get("units"),
        "origin": "user_selected_file",
        "trust": "UNTRUSTED_DATA",
    }
    if ext == ".csv":
        preview = _csv_preview(text)
    elif ext == ".json":
        preview = _json_preview(text)
    else:
        preview = {"kind": "text", "lines": text.splitlines()[:20], "total_lines": len(text.splitlines())}
    prov["missingness"] = preview.get("missingness")
    return {"provenance": prov, "preview": preview, "suggested_mapping": preview.get("suggested_mapping")}


def _csv_preview(text):
    try:
        rows = list(csv.reader(io.StringIO(text)))
    except csv.Error as e:
        raise FileRejected(f"malformed CSV: {e}") from None
    if not rows:
        raise FileRejected("CSV has no rows")
    if len(rows) > MAX_ROWS:
        raise FileRejected(f"CSV has {len(rows)} rows; limit is {MAX_ROWS}")
    header, body = rows[0], rows[1:]
    if len(header) > MAX_COLS:
        raise FileRejected(f"CSV has {len(header)} columns; limit is {MAX_COLS}")
    ragged = sum(1 for r in body if len(r) != len(header))
    miss = {}
    for i, h in enumerate(header):
        empties = sum(1 for r in body if i >= len(r) or r[i].strip() == "")
        miss[h] = empties
    hazards = sum(1 for r in rows for c in r if c.startswith(FORMULA_PREFIX))
    return {
        "kind": "csv",
        "columns": header,
        "rows_total": len(body),
        "ragged_rows": ragged,
        "sample": [[_display(c) for c in r] for r in body[:10]],
        "missingness": miss,
        "formula_like_cells": hazards,
        "suggested_mapping": _suggest_mapping(header),
    }


def _json_preview(text):
    from .contracts import ContractError, loads_strict
    try:
        obj = loads_strict(text)
    except (ValueError, ContractError) as e:
        raise FileRejected(f"JSON rejected: {e}") from None
    desc = {"kind": "json", "top_level": type(obj).__name__}
    if isinstance(obj, list):
        desc["items"] = len(obj)
        desc["sample"] = json.dumps(obj[:3])[:800]
    elif isinstance(obj, dict):
        desc["keys"] = list(obj.keys())[:50]
    return desc


def _display(cell):
    # Rendered as text by the UI (never innerHTML); also visibly flag formulas.
    return cell[:200]


def _suggest_mapping(header):
    guesses = {
        "player": ("player", "name", "shooter"),
        "game_id": ("game_id", "game"),
        "made": ("made", "make", "result", "fgm", "shot_made_flag"),
        "period": ("period", "quarter"),
        "clock": ("clock", "time_remaining"),
        "margin": ("margin", "score_margin"),
    }
    out = {}
    low = [h.strip().lower() for h in header]
    for k, names in guesses.items():
        for i, h in enumerate(low):
            if h in names:
                out[k] = header[i]
                break
    return out  # a suggestion only; the user must approve the mapping


def csv_safe_cell(value):
    """Neutralise spreadsheet formula injection on export."""
    s = "" if value is None else str(value)
    return "'" + s if s.startswith(FORMULA_PREFIX) else s


def export_csv(rows):
    buf = io.StringIO()
    w = csv.writer(buf)
    for r in rows:
        w.writerow([csv_safe_cell(c) for c in r])
    return buf.getvalue()
