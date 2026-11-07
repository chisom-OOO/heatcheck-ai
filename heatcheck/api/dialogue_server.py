"""POST /api/dialogue -> {heater_text, ref_text, evidence_record_id, verdict} (+ claim_id, sources).

Stdlib HTTP server bound to 127.0.0.1. CORS is limited to Experience's local UI origins. The
provider key stays in this process's environment; it is never returned.

Request:  {"question": "<1..500 chars>"}
Response: 200 {"heater_text": str, "ref_text": str, "evidence_record_id": str|null,
               "verdict": SURVIVED_PROTOCOL|NOT_SUPPORTED|INSUFFICIENT_EVIDENCE|DATA_INVALID|
                          BLOCKED|null, "claim_id": str, "sources": {...}}
          400 {"error": ...} for a bad request. verdict and evidence_record_id are null when no
          registered test exists for the question (claim_id "NONE").
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from heatcheck.agents.dialogue import Dialogue

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


def make_handler(dialogue: Dialogue):
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

        def do_OPTIONS(self):
            self.send_response(204)
            self._cors()
            self.send_header("Access-Control-Allow-Methods", "POST")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def do_POST(self):
            if self.path != "/api/dialogue":
                return self._send(404, {"error": "not found"})
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0 or n > MAX_BODY:
                return self._send(400, {"error": "missing or oversized body"})
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


def serve(dialogue: Dialogue, port: int = 8770) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1", port), make_handler(dialogue))
