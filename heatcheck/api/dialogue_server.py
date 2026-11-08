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
from heatcheck.agents.scenario import (
    ConfirmationError,
    EffectsProvider,
    ResearchStub,
    board_intro,
    card_intro,
    check_confirmation,
    estimate_scenario,
    parse_scenario,
    pick_game,
    route,
    scenario_identity,
    scenario_menu,
)
from heatcheck.api.display_titles import DISPLAY_TITLES
from heatcheck.api.tamper import Tamper, TamperError
from heatcheck.api.transcription import MAX_BYTES as TRANSCRIBE_MAX
from heatcheck.api.transcription import TranscribeError, Transcriber
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
TRANSCRIBE_MAX_BYTES = TRANSCRIBE_MAX
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


@dataclass
class ScenarioConfig:
    """POST /api/scenario/estimate: where confirmed scenarios are recorded, and Research's effects."""

    ledger: EvidenceLedger
    provider: EffectsProvider | None = None  # ResearchStub until research/scenario-effects is merged
    clock: object | None = None


def _json_body(raw: bytes, keys: set[str], optional: frozenset[str] = frozenset()) -> dict:
    try:
        obj = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise ValueError("body is not JSON") from None
    if not isinstance(obj, dict) or not keys <= set(obj) or set(obj) - keys - optional:
        raise ValueError(f"body must have {sorted(keys)}" + (f" and optionally {sorted(optional)}" if optional else ""))
    msg = obj.get("message")
    if msg is not None and (not isinstance(msg, str) or not msg.strip() or len(msg) > MAX_QUESTION):
        raise ValueError(f"message must be a non-empty string of at most {MAX_QUESTION} characters")
    gid = obj.get("game_id")
    if gid is not None and (not isinstance(gid, str) or len(gid) > 40):
        raise ValueError("game_id must be a short string")
    return obj


def _now_z(clock=None) -> str:
    return (clock or _now)()[:19] + "Z"


def run_route(req: dict, live_forecast: Path | None, clock=None) -> dict:
    """Where a free-text message goes: OPEN_BOARD, OPEN_CARD, SCENARIO or DIALOGUE."""
    fc = live_forecast_payload(live_forecast)
    games = fc["forecast"]["games"] if fc["status"] == "OK" else []
    now = _now_z(clock)
    out = route(req["message"], games, now)
    if out["action"] == "OPEN_BOARD":
        out["heater_text"] = board_intro(len(games)) if games else (
            "Tonight's board has no forecast to show right now; I'll open it so you can see why.")
    elif out["action"] == "OPEN_CARD":
        row = next(g for g in games if g["game_id"] == out["game_id"])
        out["heater_text"] = card_intro(row, now)
    out["forecast_status"] = fc["status"]
    return out


def run_scenario_parse(req: dict, live_forecast: Path | None, clock=None) -> tuple[int, dict]:
    fc = live_forecast_payload(live_forecast)
    if fc["status"] != "OK":
        return 200, {"status": "NO_FORECAST", "label": "NO NUMBER",
                     "heater_text": f"I can't run a what-if without a forecast ({fc['reason']})."}
    games = fc["forecast"]["games"]
    gid = req.get("game_id")
    if gid:
        row = next((g for g in games if g["game_id"] == gid), None)
        if row is None:
            return 404, {"error": f"{gid} is not in the live forecast"}
    else:
        row, cands = pick_game(req["message"], games, _now_z(clock))
        if row is None:
            names = ", ".join(f"{g['away_team']} at {g['home_team']}" for g in cands[:4])
            return 200, {"status": "NEEDS_GAME", "label": "NO NUMBER",
                         "candidates": [g["game_id"] for g in cands],
                         "heater_text": "Which game do you mean? Name a team playing tonight"
                         + (f" ({names})." if names else ".")}
    out = parse_scenario(req["message"], row, fc["file_sha256"])
    out["is_sample"] = fc["is_sample"]
    return 200, out


def run_scenario_estimate(req: dict, live_forecast: Path | None, cfg: ScenarioConfig) -> tuple[int, dict]:
    fc = live_forecast_payload(live_forecast)
    if fc["status"] != "OK":
        return 409, {"error": f"forecast {fc['status']}: {fc['reason']}"}
    row = next((g for g in fc["forecast"]["games"] if g["game_id"] == req["game_id"]), None)
    if row is None:
        return 404, {"error": f"{req['game_id']} is not in the live forecast"}
    try:
        changes, focus = check_confirmation(req, row, fc["file_sha256"])
    except ConfirmationError as e:
        return 409, {"error": str(e)}
    as_of = (cfg.clock or _now)()
    est = estimate_scenario(changes, row, fc["forecast"], fc["is_sample"], fc["file_sha256"], as_of,
                            cfg.provider or ResearchStub(), focus_team=focus)
    identity = scenario_identity(est, changes, req["interpretation_id"], fc["file_sha256"],
                                 req.get("message_sha256"))
    entry, _retried = cfg.ledger.put(identity)
    est["evidence_id"] = entry["evidence_id"]
    est["recorded_at_utc"] = entry["created_at_utc"]
    return 200, est


def run_scenario_menu(query: str, live_forecast: Path | None, cfg: ScenarioConfig | None) -> tuple[int, dict]:
    """GET /api/scenario?game_id=...[&team=...]: Experience's heatcheck-scenario/1."""
    from urllib.parse import parse_qs
    q = parse_qs(query, max_num_fields=4)
    gid = (q.get("game_id") or [""])[0]
    team = (q.get("team") or [None])[0]
    if not gid or len(gid) > 40:
        return 400, {"error": "game_id is required"}
    fc = live_forecast_payload(live_forecast)
    if fc["status"] != "OK":
        return 200, {"format": "heatcheck-scenario/1", "status": "UNAVAILABLE", "game_id": gid,
                     "reason": f"forecast {fc['status']}: {fc['reason']}"}
    row = next((g for g in fc["forecast"]["games"] if g["game_id"] == gid), None)
    if row is None:
        return 404, {"error": f"{gid} is not in the live forecast"}
    provider = (cfg.provider if cfg else None) or ResearchStub()
    if hasattr(provider, "api_answer") and not fc["is_sample"]:
        try:
            return 200, provider.api_answer(row, team or row["home_team"], fc["file_sha256"])
        except ValueError as e:  # includes Research's ScenarioRefused
            return 400, {"error": str(e)}
    try:
        return 200, scenario_menu(row, fc["forecast"], fc["is_sample"], fc["file_sha256"],
                                  ((cfg.clock if cfg else None) or _now)(), provider, team)
    except ValueError as e:
        return 400, {"error": str(e)}


ESTIMATE_KEYS = {"game_id", "changes", "focus_team", "interpretation_id", "confirmed"}
SCENARIO_PATHS = ("/api/route", "/api/scenario", "/api/scenario/estimate")


def make_handler(dialogue: Dialogue, live_forecast: Path | None = None,
                 investigation: InvestigationConfig | None = None, scenario: ScenarioConfig | None = None,
                 transcriber: Transcriber | None = None, tamper: Tamper | None = None):
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
            if self.path == "/api/tamper/events":
                if tamper is None:
                    return self._send(503, {"error": "TAMPER_OFF", "message": "The tamper demo is off on this server."})
                return self._send(200, {"events": tamper.events_list()})
            if self.path == "/api/display-titles":
                return self._send(200, {"display_titles": DISPLAY_TITLES})
            if self.path == "/api/live-forecast":
                return self._send(200, live_forecast_payload(live_forecast))
            if self.path.split("?", 1)[0] == "/api/scenario":
                try:
                    return self._send(*run_scenario_menu(self.path.partition("?")[2], live_forecast, scenario))
                except Exception as e:  # never invent an estimate
                    return self._send(500, {"error": f"scenario failed: {type(e).__name__}"})
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

        def _scenario_post(self, raw: bytes):
            try:
                if self.path == "/api/route":
                    req = _json_body(raw, {"message"})
                elif self.path == "/api/scenario":
                    req = _json_body(raw, {"message"}, frozenset({"game_id"}))
                else:
                    req = _json_body(raw, ESTIMATE_KEYS, frozenset({"message_sha256"}))
            except ValueError as e:
                return self._send(400, {"error": str(e)})
            clock = scenario.clock if scenario else None
            try:
                if self.path == "/api/route":
                    return self._send(200, run_route(req, live_forecast, clock))
                if self.path == "/api/scenario":
                    return self._send(*run_scenario_parse(req, live_forecast, clock))
                if scenario is None:
                    return self._send(503, {"error": "scenarios are not configured (no ledger)"})
                with lock:
                    return self._send(*run_scenario_estimate(req, live_forecast, scenario))
            except Exception as e:  # never invent an estimate
                return self._send(500, {"error": f"scenario failed: {type(e).__name__}"})

        def _transcribe(self):
            """POST /api/transcribe: one WAV clip in, {"transcript"} out. The audio is never stored."""
            ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            n = int(self.headers.get("Content-Length") or 0)
            if n > TRANSCRIBE_MAX_BYTES:
                # Read and drop the upload (never stored) so the client sees the 413 instead of a
                # reset connection; beyond 8 MB just close.
                if n <= 4 * TRANSCRIBE_MAX_BYTES:
                    left = n
                    while left > 0:
                        chunk = self.rfile.read(min(left, 65536))
                        if not chunk:
                            break
                        left -= len(chunk)
                else:
                    self.close_connection = True
                return self._send(413, {"error": "TOO_LARGE",
                                        "message": "That recording is too long. Keep it under 30 seconds."})
            audio = self.rfile.read(n) if n > 0 else b""  # always read first, so every answer arrives
            if transcriber is None or not transcriber.configured:
                return self._send(503, {"error": "SERVICE_UNAVAILABLE",
                                        "message": "Voice transcription is off on this server."})
            if ctype not in ("audio/wav", "audio/x-wav", "audio/wave"):
                return self._send(415, {"error": "BAD_AUDIO", "message": "Send 16 kHz mono 16-bit PCM WAV."})
            try:
                return self._send(200, transcriber.transcribe(audio))
            except TranscribeError as e:
                return self._send(e.status, e.body())
            except Exception as e:  # never invent a transcript
                return self._send(502, {"error": "SERVICE_UNAVAILABLE",
                                        "message": f"Transcription failed ({type(e).__name__})."})

        def do_POST(self):
            if self.path == "/api/transcribe":
                return self._transcribe()
            if self.path in ("/api/tamper/flip", "/api/tamper/restore"):
                n = int(self.headers.get("Content-Length") or 0)
                if 0 < n <= MAX_BODY:
                    self.rfile.read(n)   # no body is needed; read any so the client sees the answer
                if tamper is None:
                    return self._send(503, {"error": "TAMPER_OFF", "message": "The tamper demo is off on this server."})
                try:
                    if self.path.endswith("/flip"):
                        return self._send(200, tamper.flip())
                    return self._send(200, tamper.restore())
                except TamperError as e:
                    return self._send(e.status, e.body())
            if self.path not in ("/api/dialogue", "/api/investigate", *SCENARIO_PATHS):
                return self._send(404, {"error": "not found"})
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0 or n > MAX_BODY:
                return self._send(400, {"error": "missing or oversized body"})
            if self.path in SCENARIO_PATHS:
                return self._scenario_post(self.rfile.read(n))
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
          investigation: InvestigationConfig | None = None,
          scenario: ScenarioConfig | None = None,
          transcriber: Transcriber | None = None, tamper: Tamper | None = None) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1", port),
                               make_handler(dialogue, live_forecast, investigation, scenario, transcriber, tamper))
