"""HeatCheck-Experience local server (stdlib only).

Run:  python3 -m server.app [--port 8765]
Binds 127.0.0.1 only. Serves web/ and a JSON API. No order, wallet or account capability exists.
"""
import argparse
import hashlib
import json
import os
import platform
import re
import secrets
import sys
import threading
import traceback
import urllib.parse
import urllib.request
import uuid
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

from . import (
    comparison,
    engine_fixture,
    evidence,
    files,
    ideas,
    intake,
    quotes,
    timefmt,
    venue_fixtures,
)
from .authority import AuthorityError, Session, sha
from .contracts import PROTOCOL_VERSION, ContractError, loads_strict, validate_envelope
from .venues import UrllibTransport, VenueError, adapter

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
WEB = os.path.join(ROOT, "web")
EVIDENCE = os.path.join(ROOT, "evidence")
MAX_JSON = 1 * 1024 * 1024
MAX_FILE = files.MAX_BYTES + 1024
MAX_AUDIO = 10 * 1024 * 1024
MAX_PAGE_TEXT = 200_000

SESSIONS = {}
CUSTODY = {}          # run_id -> Custodian (truth holder). Never serialised into run/session/export.
REVEALED = {}         # run_id -> manifest, only after the run's decision exists
MARKET = {}           # proposal_id -> {spec, mapping, forecast, source}
HARNESS = {"status": "IDLE", "progress": [0, 0], "result": None, "error": None}
LOCK = threading.RLock()


def utcnow():
    return timefmt.now_z()


def code_hash():
    h = hashlib.sha256()
    for d in ("server", "web"):
        for base, _, fs in sorted(os.walk(os.path.join(ROOT, d))):
            for f in sorted(fs):
                if f.endswith((".py", ".js", ".html", ".css")):
                    with open(os.path.join(base, f), "rb") as fh:
                        h.update(f.encode() + fh.read())
    h.update(f"python {sys.version.split()[0]} numpy {np.__version__}".encode())
    return h.hexdigest()


CODE_HASH = code_hash()

REQUIRED_FIELDS = {
    "hot_hand": ["population", "streak_length", "setting", "comparator", "direction"],
    "clutch": ["population", "window_minutes", "margin_points", "comparator", "statistic", "direction"],
    "home_court": ["population", "target", "seasons", "direction"],
    "rest": ["population", "target", "seasons", "direction"],
    "game_win": ["population", "target", "game", "direction"],
}
FIXTURE_SUPPORTED = {"hot_hand"}


class ApiError(Exception):
    def __init__(self, status, code, msg, **extra):
        super().__init__(msg)
        self.status, self.code, self.msg, self.extra = status, code, msg, extra


def get_session(sid):
    s = SESSIONS.get(sid)
    if not s:
        raise ApiError(404, "NO_SESSION", "unknown session")
    return s


def session_view(s):
    with s.lock:
        return {
            "session_id": s.id, "revision": s.revision, "claim": s.claim, "sources": s.sources,
            "assumptions": s.assumptions, "plan": s.plan, "confirmation": s.confirmation,
            "current_run": s.current_run,
            "runs": [run_view(r) for r in s.runs.values()],
            "log": s.log[-60:],
        }


def run_view(r):
    out = {k: v for k, v in r.items() if k != "result"}
    out["has_result"] = r.get("result") is not None
    out["decision"] = (r.get("result") or {}).get("decision")
    out["revealed"] = r["run_id"] in REVEALED
    return out


# ------------------------------------------------------------------------------ plans

def build_plan(s, data_mode):
    c = s.claim
    kind = c["kind"]
    channel = c["channel"]
    executable, blocked = True, None
    if data_mode == "SYNTHETIC":
        if kind not in FIXTURE_SUPPORTED:
            executable, blocked = False, f"the local fixture engine implements only the hot-hand streak test; '{kind}' needs Research's engine"
        engine = engine_fixture.ENGINE_ID
        data_hashes = ["generated-per-run-by-custodian"]
        population = {"type": "synthetic_league", "label": f"{engine_fixture.N_SHOOTERS} anonymised shooters",
                      "user_population_note": c.get("population")}
    elif data_mode == "REAL_NBA_RETROSPECTIVE":
        engine = None
        executable, blocked = False, ("Research engine not connected: no agreed evaluation endpoint exists yet, "
                                      "so no real NBA result can be produced here")
        data_hashes = []
        population = c.get("population")
    else:
        raise ApiError(400, "BAD_MODE", "research runs use SYNTHETIC or REAL_NBA_RETROSPECTIVE")
    k = int(c.get("streak_length") or engine_fixture.STREAK_K) if kind == "hot_hand" else None
    body = {
        "protocol_version": PROTOCOL_VERSION,
        "claim_id": c.get("claim_id") or f"clm_{s.id[:8]}",
        "kind": channel,
        "claim_kind": kind,
        "statement": c.get("statement", ""),
        "estimand": (f"pooled P(make | previous {k} makes) minus P(make | otherwise), within sequence"
                     if kind == "hot_hand" else f"{kind} estimand defined by Research"),
        "population": population,
        "target_horizon_cutoff": c.get("cutoff_utc") or "retrospective: events strictly before each shot",
        "effect_units": "absolute difference in make probability" if kind == "hot_hand" else "defined by Research",
        "direction": c.get("direction"),
        "feature_catalogue_hash": sha({"features": ["previous_k_outcomes"], "k": k}),
        "baseline_hash": sha({"baseline": "within-sequence permutation null"}),
        "data_hashes": data_hashes,
        "split_manifest_hash": sha({"split": "first half / second half per sequence"}),
        "primary_metric_test": {"metric": "streak_difference", "test": "permutation_within_sequence", "alpha": engine_fixture.ALPHA},
        "practical_effect_floor": float(c.get("practical_effect_floor") or engine_fixture.PRACTICAL_FLOOR),
        "mandatory_attacks": ["permutation_within_sequence", "split_half_sign", "placebo_lag7", "leave_one_out_sign"],
        "final_family_id": None,
        "final_epoch_id": None,
        "compute_budget": {"permutations": engine_fixture.N_PERMS, "bootstrap": 300, "timeout_seconds": 120},
        "creator_model_prompt": {"interpreter": "rule-based intake v1 (no LLM)", "prompt": None},
        "streak_length": k,
        "data_mode": data_mode,
        "engine": engine,
        "executable": executable,
        "blocked_reason": blocked,
        "plan_note": "Development plan (final_epoch_id null): results are exploratory, not a sealed final evaluation.",
    }
    plan = s.propose_plan(body)
    validate_envelope("ClaimPlan", plan)
    return plan


# ------------------------------------------------------------------------------ runs

def start_run(s, request_id, blind):
    run, replay = s.start_run(request_id)
    if replay:
        return run, True
    plan = s.plan
    if not plan.get("executable"):
        s.complete_run(run["run_id"], {"decision": "BLOCKED", "reason": plan["blocked_reason"], "attacks": [],
                                       "data_mode": plan["data_mode"]})
        return run, False
    if plan["data_mode"] == "SYNTHETIC":
        fam, eff = blind.get("family"), blind.get("effect")
        rng = secrets.SystemRandom()
        if blind.get("random", True) or not fam or not eff:
            fam = rng.choice(engine_fixture.FAMILIES)
            eff = rng.choice(engine_fixture.EFFECTS)
        if fam not in engine_fixture.FAMILIES or eff not in engine_fixture.EFFECTS:
            raise ApiError(400, "BAD_BLIND_CONFIG", "unknown family/effect")
        CUSTODY[run["run_id"]] = engine_fixture.Custodian(rng.randrange(1, 2**31), fam, eff)
    threading.Thread(target=_run_worker, args=(s, run["run_id"], dict(plan)), daemon=True).start()
    return run, False


def _run_worker(s, run_id, plan):
    try:
        cust = CUSTODY[run_id]
        s.add_event(run_id, "fetching", "custodian generating sealed synthetic league")
        data = cust.generate()
        data_hash = hashlib.sha256(np.ascontiguousarray(data["sequences"]).tobytes()).hexdigest()
        product_data = {"sequences": data["sequences"], "shooters": data["shooters"]}  # no config keys
        res = engine_fixture.analyse(product_data, plan,
                                     lambda st, d="": s.add_event(run_id, st, d),
                                     lambda: s.is_cancelled(run_id))
        if res is None:
            return
        res["data_hash"] = data_hash
        res["evaluation_run"] = evaluation_envelope(s, run_id, plan, res, data_hash)
        res["attack_envelopes"] = attack_envelopes(plan, res, data_hash)
        s.add_event(run_id, "complete", res["decision"])
        s.complete_run(run_id, res)
    except Exception as e:  # visible failure, never invented output
        traceback.print_exc()
        s.complete_run(run_id, {"decision": "BLOCKED", "reason": f"engine error: {type(e).__name__}: {e}", "attacks": []})


def evaluation_envelope(s, run_id, plan, res, data_hash):
    run = s.runs[run_id]
    env = {
        "run_id": run_id, "owner_context": f"session {s.id[:8]} / experience-local",
        "confirmed_revision": run["revision"], "plan_hash": run["plan_hash"],
        "final_epoch_id": None, "exposure_receipt_id": None,
        "code_config_environment_hash": CODE_HASH, "data_hashes": [data_hash],
        "seed_manifest": {"analysis_rng_seed": 1234, "generator_seed": "sealed by custodian until reveal"},
        "model_prompt_response_ids": [],
        "counts_coverage": {"sequences": res.get("sequences"), "attempts": res.get("attempts"),
                            "eligible_positions": res.get("eligible_positions")},
        "raw_output_hashes": [sha(quotes.to_jsonable({k: v for k, v in res.items() if k != "talent"}))],
        "decision": res["decision"], "reason": res["reason"], "created_at_utc": utcnow(),
        "data_mode": "SYNTHETIC", "engine": res.get("engine"),
    }
    validate_envelope("EvaluationRun", env)
    return env


def attack_envelopes(plan, res, data_hash):
    out = []
    for a in res.get("attacks", []):
        stat = a["statistic"]
        env = {
            "claim_plan_hash": plan["canonical_plan_hash"], "test_id_version": f"{a['test_id']}@{a['version']}",
            "parameters_hash": sha({"k": plan.get("streak_length"), "test": a["test_id"]}),
            "input_hashes": [data_hash], "scope": "synthetic league (development)",
            "status": "OK" if a["pass"] else "FAILED_CHECK", "reason": a["note"],
            "statistic": stat, "effect_estimate": res.get("effect_estimate") if a["test_id"].startswith("perm") else None,
            "interval": a.get("interval"), "p_value": a.get("p_value"),
            "null_method_assumptions": a["null_method_assumptions"], "evidence_hash": sha(a),
        }
        validate_envelope("AttackResult", env)
        out.append(env)
    return out


# ------------------------------------------------------------------------------ voice

def transcribe(audio, mime):
    key = os.environ.get("META_API_KEY")
    if not key:
        raise ApiError(503, "BLOCKED", "No server-side transcription provider configured (META_API_KEY unset). "
                                        "Use browser speech or type the claim.")
    if not mime.startswith("audio/wav") and not mime.startswith("audio/x-wav"):
        raise ApiError(415, "UNSUPPORTED_AUDIO", "send 16-bit mono PCM WAV (16 or 24 kHz)")
    boundary = uuid.uuid4().hex
    req_json = json.dumps({"mode": "PUSH_TO_TALK", "model": "muse-voice-transcribe-1.0", "audioEncoding": "WAV",
                           "keywords": ["NBA", "free throw", "clutch", "hot hand", "Celtics", "Knicks"]})
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"request\"\r\nContent-Type: application/json\r\n\r\n"
            f"{req_json}\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"audio\"; filename=\"cmd.wav\"\r\n"
            f"Content-Type: audio/wav\r\n\r\n").encode() + audio + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request("https://api.meta.ai/v1/asr/transcribe", data=body, method="POST",
                                 headers={"Authorization": f"Bearer {key}",
                                          "Content-Type": f"multipart/form-data; boundary={boundary}",
                                          "Accept": "application/json"})
    t0 = datetime.now(UTC)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            out = json.loads(r.read(1_000_000))
    except Exception as e:
        raise ApiError(502, "PROVIDER_ERROR", f"transcription failed: {type(e).__name__}") from None
    ms = (datetime.now(UTC) - t0).total_seconds() * 1000
    return {"transcript": out.get("transcript", ""), "provider": "meta muse-voice-transcribe-1.0",
            "provider_ms": round(ms), "audio_ms": out.get("audioDurationMs"), "raw_audio_retained": False}


# ------------------------------------------------------------------------------ harness batch

def _harness_worker(n):
    def prog(done, total):
        HARNESS["progress"] = [done, total]
    try:
        res = engine_fixture.harness_batch(leagues_per_cell=n, progress=prog)
        res["generated_at_utc"] = utcnow()
        res["code_config_environment_hash"] = CODE_HASH
        os.makedirs(EVIDENCE, exist_ok=True)
        name = "harness_batch.json" if n >= 10 else "harness_batch_smoke.json"   # smoke runs never replace the full batch
        res["file"] = name
        with open(os.path.join(EVIDENCE, name), "w") as f:
            json.dump(res, f, indent=1)
        HARNESS.update(status="COMPLETE", result=res)
    except Exception as e:
        HARNESS.update(status="ERROR", error=f"{type(e).__name__}: {e}")


def load_cached_harness():
    p = os.path.join(EVIDENCE, "harness_batch.json")
    if os.path.exists(p) and HARNESS["result"] is None:
        with open(p) as f:
            HARNESS.update(status="COMPLETE", result=json.load(f), cached=True)


# ------------------------------------------------------------------------------ HTTP

MIME = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".json": "application/json",
        ".png": "image/png", ".webp": "image/webp", ".ico": "image/x-icon", ".jsonl": "application/x-ndjson; charset=utf-8"}
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; "
       "media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")

# ------------------------------------------------------------------------------ Max's API pass-through
# The page calls relative /api/... URLs only. Max's endpoints are forwarded to his dialogue server
# with method, body and status unchanged, so the page is same-origin on any port and needs no CORS.
UPSTREAM_DEFAULT = "http://127.0.0.1:8770"
MAX_ENDPOINTS = {"dialogue", "investigate", "live-forecast", "display-titles", "route", "scenario"}
UPSTREAM_TIMEOUT = 60  # Max's doc: client timeout of at least 30 s
UPSTREAM_MAX_BODY = 4 * 1024 * 1024


def upstream_base():
    """Max's dialogue server. Loopback only: the pass-through never reaches another host."""
    base = os.environ.get("HEATCHECK_DIALOGUE_API") or UPSTREAM_DEFAULT
    u = urllib.parse.urlsplit(base)
    if u.scheme != "http" or u.hostname not in ("127.0.0.1", "localhost") or not u.port or u.path not in ("", "/"):
        raise ApiError(500, "BAD_UPSTREAM", "the dialogue API must be http://127.0.0.1:<port>")
    return u.hostname, u.port


def forward(h, method, path_qs):
    """Send the request to Max's server and copy its status, Content-Type and body back unchanged."""
    import http.client
    host, port = upstream_base()
    body = h._body(MAX_JSON) if method == "POST" else None
    headers = {"Accept": h.headers.get("Accept") or "application/json"}
    if body is not None:
        headers["Content-Type"] = h.headers.get("Content-Type") or "application/json"
    conn = http.client.HTTPConnection(host, port, timeout=UPSTREAM_TIMEOUT)
    try:
        conn.request(method, path_qs, body=body, headers=headers)
        r = conn.getresponse()
        data = r.read(UPSTREAM_MAX_BODY + 1)
        status, ctype = r.status, r.getheader("Content-Type") or "application/octet-stream"
    except (OSError, http.client.HTTPException) as e:
        raise ApiError(502, "UPSTREAM_UNAVAILABLE",
                       f"Max's dialogue API at http://{host}:{port} did not answer ({type(e).__name__})") from None
    finally:
        conn.close()
    if len(data) > UPSTREAM_MAX_BODY:
        raise ApiError(502, "UPSTREAM_TOO_LARGE", "the dialogue API response is too large")
    h._send(status, data, ctype)


class Handler(BaseHTTPRequestHandler):
    server_version = "HeatCheckExperience/0.1"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        if os.environ.get("HEATCHECK_QUIET"):
            return
        sys.stderr.write(f"[{self.log_date_time_string()}] {fmt % args}\n")

    # -- plumbing
    def _send(self, status, body, ctype="application/json", extra=None):
        if not isinstance(body, (bytes, bytearray)):
            body = json.dumps(quotes.to_jsonable(body), allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Permissions-Policy", "microphone=(self), display-capture=(self), camera=()")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _host_ok(self):
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in ("127.0.0.1", "localhost")

    def _origin_ok(self):
        origin = self.headers.get("Origin")
        if origin is None:
            return True  # same-origin GET/fetch from non-browser clients (tests)
        u = urllib.parse.urlsplit(origin)
        if u.scheme == "chrome-extension":
            return True
        return u.hostname in ("127.0.0.1", "localhost") and str(u.port or 80) == str(self.server.server_port)

    def _read_body(self):
        """Always consume the declared body so keep-alive connections stay in sync."""
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = -1
        if n < 0:
            self.close_connection = True
            raise ApiError(400, "BAD_LENGTH", "invalid Content-Length")
        if n > MAX_AUDIO:
            self.close_connection = True   # do not read an oversized body; drop the connection after replying
            self._raw = None
            self._declared = n
            return
        self._raw = self.rfile.read(n) if n else b""
        self._declared = n

    def _body(self, limit):
        if self._raw is None or self._declared > limit:
            raise ApiError(413, "TOO_LARGE", f"request body {self._declared} bytes exceeds the limit of {limit} bytes")
        return self._raw

    def _json(self):
        raw = self._body(MAX_JSON)
        try:
            obj = loads_strict(raw.decode("utf-8") or "{}")
        except (ValueError, ContractError, UnicodeDecodeError) as e:
            raise ApiError(400, "BAD_JSON", f"invalid JSON body: {e}") from None
        if not isinstance(obj, dict):
            raise ApiError(400, "BAD_JSON", "body must be an object")
        return obj

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PUT(self):
        self._dispatch("PUT")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def do_PATCH(self):
        self._dispatch("PATCH")

    def _dispatch(self, method):
        self._raw, self._declared = b"", 0
        try:
            if method in ("POST", "PUT", "PATCH", "DELETE"):
                self._read_body()
            if not self._host_ok():
                raise ApiError(421, "BAD_HOST", "requests must address 127.0.0.1 or localhost")
            path = urllib.parse.urlsplit(self.path).path
            if method not in ("GET", "POST"):
                raise ApiError(405, "METHOD_NOT_ALLOWED", "this server is GET/POST only; nothing can be modified or deleted remotely")
            if path.startswith("/api/"):
                if method == "POST" and not self._origin_ok():
                    raise ApiError(403, "BAD_ORIGIN", "cross-origin request refused")
                return self._api(method, path)
            if method != "GET":
                raise ApiError(405, "METHOD_NOT_ALLOWED", "static files are GET only")
            return self._static(path)
        except ApiError as e:
            self._send(e.status, {"error": e.code, "message": e.msg, **e.extra})
        except AuthorityError as e:
            self._send(409, {"error": e.code, "message": str(e)})
        except files.FileRejected as e:
            self._send(422, {"error": "FILE_REJECTED", "message": str(e)})
        except ContractError as e:
            self._send(500, {"error": "CONTRACT_VIOLATION", "message": str(e)})
        except Exception as e:
            traceback.print_exc()
            self._send(500, {"error": "INTERNAL", "message": type(e).__name__})

    def _static(self, path):
        if path == "/":
            path = "/demo.html"  # the demo page; the older workspace UI stays at /index.html
        full = os.path.realpath(os.path.join(WEB, path.lstrip("/")))
        if not full.startswith(os.path.realpath(WEB) + os.sep) or not os.path.isfile(full):
            raise ApiError(404, "NOT_FOUND", "no such file")
        ext = os.path.splitext(full)[1]
        if ext not in MIME:
            raise ApiError(404, "NOT_FOUND", "no such file")
        with open(full, "rb") as f:
            self._send(200, f.read(), MIME[ext])

    # -- API
    def _api(self, method, path):
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(self.path).query))
        parts = path.strip("/").split("/")[1:]
        if parts and parts[0] in MAX_ENDPOINTS:  # every method, so Max's own 4xx answers come back
            qs = urllib.parse.urlsplit(self.path).query
            return forward(self, method, path + (f"?{qs}" if qs else ""))
        key = (method, parts[0] if parts else "")
        r = ROUTES.get(key)
        if not r:
            raise ApiError(404, "NO_ROUTE", f"{method} {path}")
        return r(self, parts[1:], q)


def r_health(h, args, q):
    h._send(200, {"ok": True, "protocol_version": PROTOCOL_VERSION, "code_hash": CODE_HASH,
                  "engine": engine_fixture.ENGINE_ID, "research_engine": False,
                  "server_transcription": bool(os.environ.get("META_API_KEY")),
                  "python": sys.version.split()[0], "platform": platform.platform()})


def r_new_session(h, args, q):
    s = Session()
    SESSIONS[s.id] = s
    h._send(201, session_view(s))


def r_get_session(h, args, q):
    h._send(200, session_view(get_session(args[0] if args else q.get("id"))))


def r_interpret(h, args, q):
    b = h._json()
    h._send(200, intake.interpret(b.get("text", "")))


def r_claim(h, args, q):
    b = h._json()
    s = get_session(b.get("session_id"))
    f = b.get("fields") or {}
    kind = f.get("kind")
    if kind not in REQUIRED_FIELDS:
        raise ApiError(422, "UNSUPPORTED_CLAIM", f"claim kind {kind!r} is not supported")
    missing = [k for k in REQUIRED_FIELDS[kind] if f.get(k) in (None, "", [], {})]
    if missing:
        raise ApiError(422, "NEEDS_CLARIFICATION", "unresolved fields: " + ", ".join(missing), missing=missing)
    if kind == "hot_hand":
        try:
            k = int(f["streak_length"])
        except (TypeError, ValueError):
            raise ApiError(422, "BAD_FIELD", "streak_length must be an integer") from None
        if not 1 <= k <= 6:
            raise ApiError(422, "BAD_FIELD", "streak_length must be 1-6")
    if f.get("direction") not in ("positive", "negative", "two_sided"):
        raise ApiError(422, "BAD_FIELD", "direction must be positive, negative or two_sided")
    claim = {k: v for k, v in f.items() if k in set(REQUIRED_FIELDS[kind]) | {"kind", "channel", "statement", "practical_effect_floor"}}
    claim["claim_id"] = f"clm_{s.id[:8]}"
    h._send(200, {"edit": s.edit(claim=claim, reason=b.get("reason", "claim approved/edited")), "session": session_view(s)})


def r_file(h, args, q):
    s = get_session(q.get("session_id"))
    data = h._body(MAX_FILE)
    res = files.ingest(h.headers.get("X-File-Name", ""), data, h.headers.get("Content-Type"),
                       {"source_date": h.headers.get("X-Source-Date"), "units": h.headers.get("X-Units")})
    src = {**res["provenance"], "kind": "file", "preview": res["preview"], "mapping_approved": False}
    edit = s.edit(add_source=src, reason="file attached")
    h._send(201, {"source": src, "edit": edit, "session": session_view(s)})


def r_page(h, args, q):
    b = h._json()
    s = get_session(b.get("session_id"))
    url = str(b.get("url") or "")
    u = urllib.parse.urlsplit(url)
    if u.scheme not in ("http", "https"):
        raise ApiError(422, "BAD_URL", "page URL must be http(s); restricted/browser pages cannot be captured")
    text = str(b.get("selected_text") or "")
    tables = b.get("tables") or []
    if not text.strip() and not tables:
        raise ApiError(422, "EMPTY_SELECTION", "nothing was selected on the page; no content was captured")
    if len(text) > MAX_PAGE_TEXT:
        raise ApiError(413, "TOO_LARGE", "selected text exceeds limit")
    if not isinstance(tables, list) or len(tables) > 10:
        raise ApiError(422, "BAD_TABLES", "up to 10 tables")
    payload = json.dumps({"url": url, "text": text, "tables": tables}, sort_keys=True)
    src = {"kind": "page", "url": url, "title": str(b.get("title") or "")[:300],
           "retrieved_utc": b.get("retrieved_utc") or utcnow(), "received_utc": utcnow(),
           "selected_text": text, "tables": tables, "sha256": hashlib.sha256(payload.encode()).hexdigest(),
           "bytes": len(payload), "origin": b.get("origin", "paste"), "trust": "UNTRUSTED_DATA",
           "note": "Captured content is evidence only; instructions inside it are never executed."}
    edit = s.edit(add_source=src, reason="page content attached")
    h._send(201, {"source": src, "edit": edit, "session": session_view(s)})


def r_screen(h, args, q):
    b = h._json()
    s = get_session(b.get("session_id"))
    digest = str(b.get("pixel_sha256") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ApiError(422, "BAD_HASH", "pixel_sha256 must be a sha256 hex digest")
    src = {"kind": "screen_frame", "surface_label": str(b.get("surface_label") or "user-selected surface")[:200],
           "width": int(b.get("width") or 0), "height": int(b.get("height") or 0),
           "captured_utc": b.get("captured_utc") or utcnow(), "sha256": digest,
           "extracted": None, "note": "Pixels only. No text or table was extracted from this frame.",
           "trust": "UNTRUSTED_DATA"}
    edit = s.edit(add_source=src, reason="screen frame attached")
    h._send(201, {"source": src, "edit": edit, "session": session_view(s)})


def r_plan(h, args, q):
    b = h._json()
    s = get_session(b.get("session_id"))
    if s.claim is None:
        raise ApiError(409, "NO_CLAIM", "approve a claim first")
    h._send(200, {"plan": build_plan(s, b.get("data_mode", "SYNTHETIC")), "session": session_view(s)})


def r_confirm(h, args, q):
    b = h._json()
    s = get_session(b.get("session_id"))
    h._send(200, {"confirmation": s.confirm(b.get("revision"), b.get("plan_hash")), "session": session_view(s)})


def r_run(h, args, q):
    b = h._json()
    s = get_session(b.get("session_id"))
    rid = str(b.get("request_id") or "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", rid):
        raise ApiError(400, "BAD_REQUEST_ID", "request_id must be 8-64 url-safe characters")
    run, replay = start_run(s, rid, b.get("blind") or {"random": True})
    h._send(200 if replay else 202, {"run": run_view(run), "idempotent_replay": replay})


def r_get_run(h, args, q):
    s = get_session(q.get("session_id"))
    run = s.runs.get(args[0] if args else "")
    if not run:
        raise ApiError(404, "NO_RUN", "unknown run")
    out = run_view(run)
    out["result"] = run["result"]
    out["reveal"] = REVEALED.get(run["run_id"])
    h._send(200, out)


def r_cancel(h, args, q):
    b = h._json()
    s = get_session(b.get("session_id"))
    h._send(200, {"run": run_view(s.cancel(b.get("run_id"))), "session": session_view(s)})


def r_reveal(h, args, q):
    b = h._json()
    s = get_session(b.get("session_id"))
    rid = b.get("run_id")
    run = s.runs.get(rid)
    if not run:
        raise ApiError(404, "NO_RUN", "unknown run")
    if run.get("result") is None:
        raise ApiError(409, "NOT_DECIDED", "truth is revealed only after the run has a recorded decision")
    if rid not in CUSTODY:
        raise ApiError(409, "NO_TRUTH", "this run has no simulator truth (not a synthetic run)")
    if rid not in REVEALED:
        m = CUSTODY[rid].reveal()
        dec = run["result"]["decision"]
        m["decision_at_reveal"] = dec
        real = m["effect_size"] > 0
        if dec == "SURVIVED_PROTOCOL":
            m["outcome"] = "TRUE_DISCOVERY" if real else "FALSE_DISCOVERY"
        elif dec in ("NOT_SUPPORTED", "INSUFFICIENT_EVIDENCE"):
            m["outcome"] = "MISSED_EFFECT" if real else "CORRECT_REJECTION"
        else:
            m["outcome"] = "NO_DECISION"
        m["revealed_at_utc"] = utcnow()
        REVEALED[rid] = m
        s._log("truth_revealed", run_id=rid)
    h._send(200, REVEALED[rid])


def r_export(h, args, q):
    s = get_session(q.get("session_id"))
    rid = args[0] if args else ""
    if rid not in s.runs:
        raise ApiError(404, "NO_RUN", "unknown run")
    exp = s.export(rid)
    exp["reveal"] = REVEALED.get(rid)
    exp["sources"] = [{k: v for k, v in src.items() if k not in ("preview",)} for src in s.sources]
    exp["code_config_environment_hash"] = CODE_HASH
    if q.get("format") == "csv":
        res = s.runs[rid].get("result") or {}
        rows = [["run_id", "revision", "decision", "reason", "test_id", "statistic", "p_value", "pass", "note"]]
        for a in res.get("attacks", []):
            rows.append([rid, s.runs[rid]["revision"], res.get("decision"), res.get("reason"), a["test_id"],
                         json.dumps(quotes.to_jsonable(a["statistic"])), a.get("p_value"), a.get("pass"), a.get("note")])
        for src in s.sources:  # source names/titles are user-controlled: neutralised on export
            rows.append([rid, "", "", "source", src.get("kind"), src.get("file_name") or src.get("title") or src.get("url"),
                         src.get("sha256"), "", ""])
        return h._send(200, files.export_csv(rows).encode(), "text/csv; charset=utf-8",
                       {"Content-Disposition": f'attachment; filename="heatcheck_{rid}.csv"'})
    h._send(200, exp, extra={"Content-Disposition": f'attachment; filename="heatcheck_{rid}.json"'})


def r_transcribe(h, args, q):
    audio = h._body(MAX_AUDIO)
    if not audio:
        raise ApiError(400, "NO_AUDIO", "empty audio")
    h._send(200, transcribe(audio, h.headers.get("Content-Type", "")))


def r_harness_start(h, args, q):
    b = h._json()
    n = int(b.get("leagues_per_cell", 12))
    if not 2 <= n <= 60:
        raise ApiError(400, "BAD_SIZE", "leagues_per_cell must be 2-60")
    with LOCK:
        if HARNESS["status"] == "RUNNING":
            raise ApiError(409, "RUN_ACTIVE", "harness batch already running")
        HARNESS.update(status="RUNNING", progress=[0, 0], error=None)
    threading.Thread(target=_harness_worker, args=(n,), daemon=True).start()
    h._send(202, {"status": "RUNNING"})


def r_harness(h, args, q):
    load_cached_harness()
    h._send(200, HARNESS)


def r_market_scenarios(h, args, q):
    h._send(200, {"scenarios": venue_fixtures.scenario_list(), "game": venue_fixtures.GAME,
                  "forecast": venue_fixtures.FORECAST,
                  "freshness_seconds": {"historical": comparison.FRESHNESS_SECONDS_HISTORICAL,
                                        "live": comparison.FRESHNESS_SECONDS_LIVE}})


def _transport(source):
    if source == "live":
        return UrllibTransport()
    if source.startswith("fixture:"):
        try:
            return venue_fixtures.transport(source.split(":", 1)[1])
        except KeyError:
            raise ApiError(400, "BAD_SOURCE", "unknown fixture scenario") from None
    raise ApiError(400, "BAD_SOURCE", "source must be 'live' or 'fixture:<scenario>'")


def r_market_propose(h, args, q):
    b = h._json()
    venue, ref, source = b.get("venue"), str(b.get("ref") or ""), str(b.get("source") or "")
    if source.startswith("fixture:"):
        sc = venue_fixtures.SCENARIOS.get(source.split(":", 1)[1])
        if sc:
            venue, ref = sc[0], ref or sc[1]
    try:
        out = comparison.propose(venue, ref, venue_fixtures.GAME, venue_fixtures.FORECAST, _transport(source))
    except VenueError as e:
        out = {"stage": "spec", "status": e.status, "reason": e.reason, "spec": None, "mapping": None}
    pid = "prop_" + uuid.uuid4().hex[:12]
    MARKET[pid] = {**out, "source": source, "venue": venue, "ref": ref}
    h._send(200, {"proposal_id": pid, **out, "source": source,
                  "game": venue_fixtures.GAME, "forecast": venue_fixtures.FORECAST})


def r_market_compare(h, args, q):
    b = h._json()
    p = MARKET.get(b.get("proposal_id"))
    if not p:
        raise ApiError(404, "NO_PROPOSAL", "unknown proposal")
    if not p.get("spec"):
        raise ApiError(409, p["status"], p.get("reason", "no market spec"))
    qt = b.get("quote_type", "midpoint")
    if qt not in ("midpoint", "bid", "ask"):
        raise ApiError(400, "BAD_QUOTE_TYPE", "quote_type must be midpoint, bid or ask")
    env = comparison.compare(p["spec"], p["mapping"], venue_fixtures.FORECAST, _transport(p["source"]),
                             b.get("reviewer", ""), qt)
    h._send(200, env)


def r_venues_health(h, args, q):
    out = {}
    for v in ("polymarket", "kalshi"):
        out[v] = adapter(v, UrllibTransport()).health()
    out["live_reachability"] = "not probed automatically; use a live comparison to test (network may be denied)"
    h._send(200, out)


def r_evidence(h, args, q):
    """Verified entries of the configured Referee evidence ledger (read-only)."""
    try:
        h._send(200, evidence.read_verified(evidence.configured_path()))
    except evidence.EvidenceUnavailable as e:
        raise ApiError(404 if e.status in ("NOT_CONFIGURED", "NOT_FOUND") else 409, e.status, str(e)) from None


MAPPING_FIELDS = ("mapping_id", "game_id", "venue", "contract_id", "team_id", "label", "status", "two_sided")
QUOTE_RUNS = os.path.join(ROOT, "..", "..", "data", "experience", "quotes")


def newest_quote_index():
    """The newest capture run's board.mappings.json (run directories are named by UTC start time)."""
    try:
        runs = sorted(d for d in os.listdir(QUOTE_RUNS) if re.fullmatch(r"\d{8}T\d{6}Z", d))
    except OSError:
        return None
    for d in reversed(runs):
        p = os.path.join(QUOTE_RUNS, d, "board.mappings.json")
        if os.path.isfile(p):
            return os.path.abspath(p)
    return None


def r_market_mappings(h, args, q):
    """Which venue mapping ids the quote bundle holds, for the demo's market board (read-only).
    The index is written by ``heatcheck.markets.live_quotes capture|index`` in the capture run
    directory that Max's ``serve_dialogue --quote-bundle`` reads. Ids, labels and statuses, never prices:
    every number on a card comes from Max's /api/investigate."""
    path = os.environ.get("HEATCHECK_QUOTE_INDEX") or newest_quote_index()
    if not path:
        raise ApiError(404, "NOT_CONFIGURED", "no quote mapping index configured (--quote-index)")
    try:
        with open(path, encoding="utf-8") as f:
            idx = json.load(f)
    except FileNotFoundError:
        raise ApiError(404, "NOT_FOUND", f"{os.path.basename(path)} not found") from None
    except (OSError, ValueError) as e:
        raise ApiError(409, "DATA_INVALID", f"quote mapping index unreadable ({type(e).__name__})") from None
    if not isinstance(idx, dict) or idx.get("format") != "heatcheck-quote-mappings/1" or not isinstance(idx.get("mappings"), list):
        raise ApiError(409, "DATA_INVALID", "not a heatcheck-quote-mappings/1 index")
    rows = []
    for m in idx["mappings"]:
        if not isinstance(m, dict) or not all(k in m for k in MAPPING_FIELDS):
            raise ApiError(409, "DATA_INVALID", "a mapping row lacks a required field")
        rows.append({k: m[k] for k in MAPPING_FIELDS})
    h._send(200, {"format": idx["format"], "run": idx.get("run"), "captured": idx.get("captured"),
                  "is_sample_game_list": bool((idx.get("forecast_input") or {}).get("is_sample")),
                  "mappings": rows})


def r_ideas(h, args, q):
    """Research's idea-family results, bindings verified (read-only)."""
    try:
        h._send(200, ideas.read_all())
    except ideas.IdeasUnavailable as e:
        raise ApiError(404, e.status, str(e)) from None


def r_gates(h, args, q):
    with open(os.path.join(EVIDENCE, "acceptance_ledger.json")) as f:
        h._send(200, json.load(f))


ROUTES = {
    ("GET", "health"): r_health,
    ("POST", "session"): r_new_session,
    ("GET", "session"): r_get_session,
    ("POST", "interpret"): r_interpret,
    ("POST", "claim"): r_claim,
    ("POST", "file"): r_file,
    ("POST", "page"): r_page,
    ("POST", "screen"): r_screen,
    ("POST", "plan"): r_plan,
    ("POST", "confirm"): r_confirm,
    ("POST", "run"): r_run,
    ("GET", "run"): r_get_run,
    ("POST", "cancel"): r_cancel,
    ("POST", "reveal"): r_reveal,
    ("GET", "export"): r_export,
    ("POST", "transcribe"): r_transcribe,
    ("POST", "harness"): r_harness_start,
    ("GET", "harness"): r_harness,
    ("GET", "market-scenarios"): r_market_scenarios,
    ("POST", "market-propose"): r_market_propose,
    ("POST", "market-compare"): r_market_compare,
    ("GET", "venues"): r_venues_health,
    ("GET", "gates"): r_gates,
    ("GET", "evidence"): r_evidence,
    ("GET", "market-mappings"): r_market_mappings,
    ("GET", "ideas"): r_ideas,
}


def make_server(port=8765):
    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--ledger", help="existing Referee evidence ledger (.jsonl) to show read-only")
    ap.add_argument("--quote-index", help="board.mappings.json written by live_quotes index (market board); "
                                          "default: the newest data/experience/quotes/*/board.mappings.json")
    ap.add_argument("--ideas", help="Research's idea-family directory (default "
                                    "handoff/research-20261107/evidence/idea-family)")
    ap.add_argument("--api", help=f"Max's dialogue server for the /api pass-through (default {UPSTREAM_DEFAULT})")
    a = ap.parse_args()
    if a.ledger:
        os.environ["HEATCHECK_LEDGER"] = os.path.abspath(a.ledger)
    if a.quote_index:
        os.environ["HEATCHECK_QUOTE_INDEX"] = os.path.abspath(a.quote_index)
    if a.api:
        os.environ["HEATCHECK_DIALOGUE_API"] = a.api
    if a.ideas:
        os.environ["HEATCHECK_IDEAS"] = os.path.abspath(a.ideas)
    upstream_base()  # refuse a non-loopback upstream at start-up
    srv = make_server(a.port)
    print(f"HeatCheck-Experience on http://127.0.0.1:{a.port}/  (demo page; code {CODE_HASH[:12]})")
    print(f"  /api/{{{','.join(sorted(MAX_ENDPOINTS))}}} -> {os.environ.get('HEATCHECK_DIALOGUE_API') or UPSTREAM_DEFAULT}")
    srv.serve_forever()


if __name__ == "__main__":
    main()
