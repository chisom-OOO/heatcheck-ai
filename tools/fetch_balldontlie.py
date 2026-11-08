"""Fetch NBA games from balldontlie (read-only GET) and store every raw response unchanged.

    uv run --frozen python tools/fetch_balldontlie.py OUT_DIR

Requests (https://api.balldontlie.io/v1/games):
  1. seasons[]=2026&per_page=100, following meta.next_cursor to the end;
  2. dates[]=2026-11-07&dates[]=2026-11-08&per_page=100, following the cursor.

The API key is read from ~/balldontlie_key.txt and sent only in the Authorization header. It is
never printed, logged, written or placed in a URL. Every response body is saved byte-for-byte as
OUT_DIR/<NN>-<sha256[:16]>.json; OUT_DIR/manifest.json lists the URL (no key), HTTP status,
fetch start and receive times (UTC, local clock), byte count and sha256 of each. The script
fails if the key appears in any saved file. Free-tier pacing: waits between requests and retries
HTTP 429 with backoff.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

BASE = "https://api.balldontlie.io/v1/games"
KEY_FILE = Path.home() / "balldontlie_key.txt"
PACE_S = 13.0  # free tier: 5 requests per minute
MAX_PAGES = 50
UA = "HeatCheck-research/1 (read-only schedule fetch)"


def now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def get(url: str, key: str) -> tuple[int, bytes, str, str]:
    for attempt in range(6):
        req = urllib.request.Request(url, headers={"Authorization": key, "Accept": "application/json",
                                                   "User-Agent": UA})
        start = now()
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, r.read(), start, now()
        except urllib.error.HTTPError as e:
            body = e.read()
            if e.code == 429 and attempt < 5:
                wait = 20 * (attempt + 1)
                print(f"  HTTP 429, waiting {wait}s", flush=True)
                time.sleep(wait)
                continue
            return e.code, body, start, now()
    raise RuntimeError("unreachable")


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__)
        return 2
    out = Path(argv[0])
    out.mkdir(parents=True, exist_ok=True)
    key = KEY_FILE.read_text(encoding="utf-8").strip()
    if not key:
        print(f"FAIL: {KEY_FILE} is empty")
        return 1
    queries = [
        ("season_2026", [("seasons[]", "2026"), ("per_page", "100")]),
        ("dates_2026-11-07_08", [("dates[]", "2026-11-07"), ("dates[]", "2026-11-08"), ("per_page", "100")]),
    ]
    entries, n, status = [], 0, 0
    for name, params in queries:
        cursor = None
        for page in range(MAX_PAGES):
            q = params + ([("cursor", str(cursor))] if cursor is not None else [])
            url = f"{BASE}?{urllib.parse.urlencode(q)}"
            if n:
                time.sleep(PACE_S)
            code, body, start, received = get(url, key)
            n += 1
            sha = hashlib.sha256(body).hexdigest()
            fname = f"{n:02d}-{sha[:16]}.json"
            (out / fname).write_bytes(body)
            meta = None
            try:
                meta = json.loads(body).get("meta")
            except (ValueError, AttributeError):
                pass
            count = None
            try:
                count = len(json.loads(body).get("data", []))
            except (ValueError, AttributeError):
                pass
            entries.append({"n": n, "query": name, "page": page, "url": url, "http_status": code,
                            "fetch_start_utc": start, "received_utc": received, "bytes": len(body),
                            "sha256": sha, "file": fname, "games_in_page": count, "meta": meta})
            print(f"{n:02d} {name} page {page}: HTTP {code}, {len(body)} bytes, games {count}, "
                  f"next_cursor {meta.get('next_cursor') if isinstance(meta, dict) else None}", flush=True)
            if code != 200:
                status = 1
                break
            cursor = meta.get("next_cursor") if isinstance(meta, dict) else None
            if cursor is None:
                break
        else:
            print(f"FAIL: {name} did not end within {MAX_PAGES} pages")
            status = 1
    manifest = {"source": "balldontlie GET /v1/games (read-only)", "key_handling":
                "Authorization header only; key not stored here", "requests": entries}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8", newline="\n")
    kb = key.encode("utf-8")
    leaks = [p.name for p in out.iterdir() if p.is_file() and kb in p.read_bytes()]
    if leaks:
        print(f"FAIL: the key appears in {len(leaks)} saved file(s); do not commit")
        return 1
    print(f"key check: not present in any of {len(list(out.iterdir()))} saved files")
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
