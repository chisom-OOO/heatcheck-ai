"""GET / (console page) and POST /api/dialogue -> {heater_text, ref_text, evidence_record_id, verdict} (+ claim_id, sources).

Stdlib HTTP server bound to 127.0.0.1. CORS is limited to Experience's local UI origins. The
provider key stays in this process's environment; it is never returned.

Request:  {"question": "<1..500 chars>"}
Response: 200 {"heater_text": str, "ref_text": str, "evidence_record_id": str|null,
               "verdict": SURVIVED_PROTOCOL|NOT_SUPPORTED|INSUFFICIENT_EVIDENCE|DATA_INVALID|
                          BLOCKED|null, "claim_id": str, "sources": {...}}
          400 {"error": ...} for a bad request. verdict and evidence_record_id are null when no
          registered test exists for the question (claim_id "NONE").

GET /api/live-forecast re-reads and validates the configured heatcheck-live-forecast/1 file on
every request (docs/LIVE_FORECAST_FORMAT.md):
  {"status": "OK", "is_sample": bool, "file_sha256": str, "forecast": {...}}
  {"status": "UNAVAILABLE" | "DATA_INVALID", "reason": str}   (no forecast values are returned)

POST /api/investigate {"game_id": "nba:..", "mapping_id": str, "message": str} runs the read-only
MARKET_COMPARISON investigation (heatcheck/agents/market_investigation.py) on the configured
forecast file and quote bundle, appends it to the investigation ledger and returns
{..., "verdict": "Worth investigating · Edge unverified" | "Can't compare", "evidence_id"}.
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from heatcheck.agents.dialogue import Dialogue
from heatcheck.agents.market_investigation import InvestigationInputError, investigate
from heatcheck.api.display_titles import DISPLAY_TITLES
from heatcheck.contracts.bundle import BundleError, load_bundle
from heatcheck.contracts.live_forecast import (
    LiveForecastError,
    parse_live_forecast,
    validate_live_forecast,
)
from heatcheck.contracts.records import RecordError
from heatcheck.ledger.evidence import EvidenceLedger

CONSOLE = Path(__file__).with_name("console.html")

MAX_BODY = 16 * 1024
MAX_QUESTION = 500
ALLOWED_ORIGINS = {"http://127.0.0.1:8765", "http://localhost:8765"}


def validate_request(raw: bytes) -> str:
    try:
        obj = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise ValueError("body is not JSON") from None
    if not isinstance(obj, dict) or set(obj) != {"question"}:
        raise ValueError("body must be exactly {\"question\": string}")
    q = obj["question"]
    if not isinstance(q, str) or not q.strip():
        raise ValueError("question must be a non-empty string")
    if len(q) > MAX_QUESTION:
        raise ValueError(f"question longer than {MAX_QUESTION} characters")
    return q.strip()


def live_forecast_payload(path: Path | None) -> dict:
    """Read and validate the live forecast file now. An invalid file never leaks partial values."""
    if path is None:
        return {"status": "UNAVAILABLE", "reason": "no live forecast file configured"}
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return {"status": "UNAVAILABLE", "reason": f"{path.name} not found"}
    except OSError as e:
        return {"status": "UNAVAILABLE", "reason": f"{path.name} unreadable ({type(e).__name__})"}
    try:
        lf = parse_live_forecast(raw)
    except LiveForecastError as e:
        return {"status": "DATA_INVALID", "reason": str(e)}
    return {"status": "OK", "is_sample": lf.is_sample, "file_sha256": hashlib.sha256(raw).hexdigest(),
            "forecast": lf.doc}


@dataclass
class InvestigationConfig:
    """Sources for POST /api/investigate. Every request re-reads and re-validates both files."""

    market_bundle: Path | list[Path]  # a bundle, or a directory searched for bundles
    ledger: EvidenceLedger
    mode: str = "LIVE"  # LIVE: compare as of now; RECORDED: as of the quote's capture time
    thesis_lookup: object | None = None  # () -> recorded GP-REST entry or None
    heater_llm: object | None = None  # (system, user) -> str
    clock: object | None = None  # () -> "YYYY-MM-DDTHH:MM:SS.ffffffZ"
    verifications: Path | None = None  # Max's heatcheck-mapping-verification/1 documents


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def discover_bundles(roots: Path | list[Path]) -> list[Path]:
    """Each root is a bundle (has manifest.json) or a directory searched recursively for them."""
    out = []
    for root in [roots] if isinstance(roots, Path) else list(roots):
        root = Path(root)
        if (root / "manifest.json").is_file():
            out.append(root)
        elif root.is_dir():
            out.extend(sorted(p.parent for p in root.rglob("manifest.json")))
    return out


def load_verifications(vdir: Path | None) -> list[dict]:
    if vdir is None or not Path(vdir).is_dir():
        return []
    docs = []
    for f in sorted(Path(vdir).glob("*.json")):
        docs.extend(json.loads(f.read_text(encoding="utf-8")).get("verifications", []))
    return docs


def select_bundle(cfg: InvestigationConfig, mapping_id: str, as_of: str | None):
    """The bundle holding the newest quote for ``mapping_id`` (received by ``as_of`` when given),
    with Max's verified mappings applied. Returns (records, records_sha256, newest_received,
    problems)."""
    from heatcheck.contracts.mapping_verification import apply_verifications
    from heatcheck.contracts.records import parse_utc
    docs = load_verifications(cfg.verifications)
    best, problems = None, []
    for b in discover_bundles(cfg.market_bundle):
        try:
            manifest, recs = load_bundle(b)
        except (BundleError, RecordError, ValueError, OSError) as e:
            problems.append(f"{b.name}: {str(e)[:120]}")
            continue
        got = [parse_utc(r["body"]["received_utc"]) for r in recs
               if r["record_type"] == "QUOTE" and r["body"]["mapping_id"] == mapping_id]
        if as_of is not None:
            got = [t for t in got if t <= parse_utc(as_of)]
        if not got:
            continue
        if best is None or max(got) > best[2]:
            recs, notes = apply_verifications(recs, manifest["records_sha256"], docs)
            problems.extend(notes)
            best = (recs, manifest["records_sha256"], max(got))
    if best is None:
        return None, None, None, problems
    return (*best, problems)


def validate_investigate_request(raw: bytes) -> dict:
    try:
        obj = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise ValueError("body is not JSON") from None
    if not isinstance(obj, dict) or set(obj) != {"game_id", "mapping_id", "message"}:
        raise ValueError('body must be exactly {"game_id", "mapping_id", "message"}')
    for k in ("game_id", "mapping_id"):
        if not isinstance(obj[k], str) or not obj[k] or len(obj[k]) > 200:
            raise ValueError(f"{k} must be a non-empty string")
    if not isinstance(obj["message"], str) or len(obj["message"]) > MAX_QUESTION:
        raise ValueError(f"message must be a string of at most {MAX_QUESTION} characters")
    return obj


def run_investigation(req: dict, live_forecast: Path | None, cfg: InvestigationConfig) -> tuple[int, dict]:
    fc = live_forecast_payload(live_forecast)
    if fc["status"] != "OK":
        return 200, {"verdict": "Can't compare", "ref_text": f"Can't compare. Forecast {fc['status']}: {fc['reason']}.",
                     "evidence_id": None}
    # The exact bytes hashed in fc (one read), not a second read of the file.
    lf = validate_live_forecast(fc["forecast"])
    as_of = None if cfg.mode == "RECORDED" else (cfg.clock or _now)()
    records, records_sha, newest, problems = select_bundle(cfg, req["mapping_id"], as_of)
    if records is None:
        why = "; ".join(problems[:3]) or f"no quote for mapping {req['mapping_id']}"
        if cfg.mode == "RECORDED" and not problems:
            return 404, {"error": f"no recorded quote for mapping {req['mapping_id']}"}
        return 200, {"verdict": "Can't compare", "evidence_id": None,
                     "ref_text": f"Can't compare. Quote source: {why[:300]}."}
    if as_of is None:
        as_of = newest.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    thesis = cfg.thesis_lookup() if cfg.thesis_lookup else None
    try:
        out, identity = investigate(lf, fc["file_sha256"], req["game_id"], req["mapping_id"], records,
                                    records_sha, req["message"], as_of, mode=cfg.mode,
                                    thesis_entry=thesis, heater_llm=cfg.heater_llm)
    except InvestigationInputError as e:
        return 404, {"error": str(e)}
    entry, _retried = cfg.ledger.put(identity)
    out["evidence_id"] = entry["evidence_id"]
    out["recorded_at_utc"] = entry["created_at_utc"]
    return 200, out


def make_handler(dialogue: Dialogue, live_forecast: Path | None = None,
                 investigation: InvestigationConfig | None = None):
    lock = threading.Lock()  # one turn at a time: the ledger is append-only and file-backed

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):  # no request logging (questions may be personal)
            pass

        def _cors(self):
            origin = self.headers.get("Origin")
            if origin in ALLOWED_ORIGINS:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")

        def _send(self, code: int, obj: dict):
            body = json.dumps(obj, ensure_ascii=False, allow_nan=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self._cors()
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            """GET / serves the console page (static file, no data embedded);
            GET /api/display-titles returns the presentation-only claim title map."""
            if self.path == "/api/display-titles":
                return self._send(200, {"display_titles": DISPLAY_TITLES})
            if self.path == "/api/live-forecast":
                return self._send(200, live_forecast_payload(live_forecast))
            if self.path not in ("/", "/index.html"):
                return self._send(404, {"error": "not found"})
            body = CONSOLE.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'unsafe-inline'; "
                             "style-src 'unsafe-inline'; connect-src 'self'")
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self):
            self.send_response(204)
            self._cors()
            self.send_header("Access-Control-Allow-Methods", "GET, POST")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def do_POST(self):
            if self.path not in ("/api/dialogue", "/api/investigate"):
                return self._send(404, {"error": "not found"})
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0 or n > MAX_BODY:
                return self._send(400, {"error": "missing or oversized body"})
            if self.path == "/api/investigate":
                if investigation is None:
                    return self._send(503, {"error": "investigation is not configured (no quote source)"})
                try:
                    req = validate_investigate_request(self.rfile.read(n))
                except ValueError as e:
                    return self._send(400, {"error": str(e)})
                try:
                    with lock:
                        code, out = run_investigation(req, live_forecast, investigation)
                except Exception as e:  # never invent a verdict
                    return self._send(500, {"error": f"investigation failed: {type(e).__name__}"})
                return self._send(code, out)
            try:
                q = validate_request(self.rfile.read(n))
            except ValueError as e:
                return self._send(400, {"error": str(e)})
            try:
                with lock:
                    out = dialogue.turn(q)
            except Exception as e:  # the loop itself failed; never invent a verdict
                return self._send(500, {"error": f"turn failed: {type(e).__name__}"})
            return self._send(200, out)

    return Handler


def serve(dialogue: Dialogue, port: int = 8770, live_forecast: Path | None = None,
          investigation: InvestigationConfig | None = None) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1", port), make_handler(dialogue, live_forecast, investigation))
