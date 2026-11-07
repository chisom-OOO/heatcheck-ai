"""HTTP API tests against a real server instance on an ephemeral port."""
import http.client
import json
import os
import sys
import threading
import time
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
os.environ["HEATCHECK_QUIET"] = "1"
os.environ.pop("META_API_KEY", None)
os.environ.pop("HEATCHECK_RESEARCH_URL", None)
from server import app  # noqa: E402

HOT = {"kind": "hot_hand", "channel": "SHOT_ASSOCIATION", "population": {"type": "group", "label": "players"},
       "streak_length": 3, "setting": "free throws only", "comparator": "within-player permutation null",
       "direction": "positive", "statement": "Players shoot better after three makes"}


class Api(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = app.make_server(0)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def req(self, method, path, body=None, headers=None, raw=False):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        h = {"Host": f"127.0.0.1:{self.port}", **(headers or {})}
        data = body if isinstance(body, (bytes, bytearray)) else (json.dumps(body).encode() if body is not None else None)
        if data is not None and "Content-Type" not in h:
            h["Content-Type"] = "application/json"
        c.request(method, path, body=data, headers=h)
        r = c.getresponse()
        out = r.read()
        c.close()
        if raw:
            return r.status, dict(r.getheaders()), out
        return r.status, (json.loads(out) if out else None)

    def session(self):
        return self.req("POST", "/api/session", {})[1]["session_id"]

    def confirmed(self, sid, mode="SYNTHETIC"):
        self.assertEqual(self.req("POST", "/api/claim", {"session_id": sid, "fields": HOT})[0], 200)
        st, p = self.req("POST", "/api/plan", {"session_id": sid, "data_mode": mode})
        self.assertEqual(st, 200)
        plan = p["plan"]
        self.assertEqual(self.req("POST", "/api/confirm", {"session_id": sid, "revision": plan["revision"], "plan_hash": plan["canonical_plan_hash"]})[0], 200)
        return plan

    def wait(self, sid, rid, timeout=60):
        t = time.time()
        while time.time() - t < timeout:
            st, r = self.req("GET", f"/api/run/{rid}?session_id={sid}")
            if r["status"] != "RUNNING":
                return r
            time.sleep(0.2)
        self.fail("run did not finish")

    # --- transport security
    def test_host_header_rebinding_refused(self):
        self.assertEqual(self.req("GET", "/api/health", headers={"Host": "attacker.example"})[0], 421)

    def test_cross_origin_post_refused(self):
        self.assertEqual(self.req("POST", "/api/session", {}, headers={"Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.req("POST", "/api/session", {}, headers={"Origin": "chrome-extension://abc"})[0], 201)

    def test_static_traversal_and_headers(self):
        for p in ("/../server/app.py", "/%2e%2e/server/app.py", "/..%2fserver%2fapp.py", "/voice.js/../../README.md"):
            self.assertEqual(self.req("GET", p)[0], 404, p)
        st, h, body = self.req("GET", "/", raw=True)
        self.assertEqual(st, 200)
        self.assertIn("script-src 'self'", h["Content-Security-Policy"])
        self.assertEqual(h["X-Content-Type-Options"], "nosniff")

    def test_methods_and_bad_json(self):
        self.assertEqual(self.req("PUT", "/api/session", {})[0], 405)
        self.assertEqual(self.req("POST", "/api/interpret", b"{bad")[0], 400)
        self.assertEqual(self.req("POST", "/api/interpret", b'{"text": NaN}')[0], 400)
        self.assertEqual(self.req("POST", "/api/interpret", b"[1,2]")[0], 400)

    def test_oversize_json_refused(self):
        self.assertEqual(self.req("POST", "/api/interpret", b'{"text":"' + b"a" * (app.MAX_JSON + 10) + b'"}')[0], 413)

    def test_keepalive_unread_body_does_not_corrupt_next_request(self):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Host": f"127.0.0.1:{self.port}", "Content-Type": "application/json"}
        c.request("POST", "/api/session", body=b'{"ignored": true}', headers=h)
        c.getresponse().read()
        c.request("GET", "/api/health", headers=h)
        r = c.getresponse()
        self.assertEqual(r.status, 200)
        r.read()
        c.close()

    # --- claim / plan / run
    def test_claim_needs_every_field(self):
        sid = self.session()
        st, r = self.req("POST", "/api/claim", {"session_id": sid, "fields": {**HOT, "setting": ""}})
        self.assertEqual((st, r["error"], r["missing"]), (422, "NEEDS_CLARIFICATION", ["setting"]))
        self.assertEqual(self.req("POST", "/api/claim", {"session_id": sid, "fields": {**HOT, "streak_length": 99}})[0], 422)
        self.assertEqual(self.req("POST", "/api/claim", {"session_id": sid, "fields": {**HOT, "kind": "astrology"}})[0], 422)

    def test_full_synthetic_run_reveal_export(self):
        sid = self.session()
        plan = self.confirmed(sid)
        st, early = self.req("POST", "/api/run", {"session_id": sid, "request_id": "bad id!"})
        self.assertEqual(st, 400)
        st, r = self.req("POST", "/api/run", {"session_id": sid, "request_id": "req-api-0001", "blind": {"random": False, "family": "parametric_beta_binomial", "effect": "planted"}})
        self.assertEqual(st, 202)
        rid = r["run"]["run_id"]
        self.assertEqual(self.req("POST", "/api/reveal", {"session_id": sid, "run_id": rid})[0], 409)
        res = self.wait(sid, rid)
        blob = json.dumps({k: v for k, v in res.items() if k != "reveal"})
        self.assertNotIn("planted", blob.replace("planted-truth", ""))    # config never in run payload
        self.assertNotIn("parametric_beta_binomial", blob)
        self.assertIn(res["result"]["decision"], ("SURVIVED_PROTOCOL", "NOT_SUPPORTED", "INSUFFICIENT_EVIDENCE"))
        self.assertEqual(len(res["result"]["attack_envelopes"]), 4)
        st, m = self.req("POST", "/api/reveal", {"session_id": sid, "run_id": rid})
        self.assertEqual((st, m["effect"], m["family"]), (200, "planted", "parametric_beta_binomial"))
        self.assertIn(m["outcome"], ("TRUE_DISCOVERY", "MISSED_EFFECT"))
        st, e = self.req("GET", f"/api/export/{rid}?session_id={sid}")
        self.assertEqual(e["evidence_context"]["plan_hash"], plan["canonical_plan_hash"])
        self.assertEqual(e["reveal"]["effect"], "planted")
        st, h, csv = self.req("GET", f"/api/export/{rid}?session_id={sid}&format=csv", raw=True)
        self.assertTrue(h["Content-Type"].startswith("text/csv"))

    def test_idempotent_run_and_late_edit(self):
        sid = self.session()
        self.confirmed(sid)
        s1, a = self.req("POST", "/api/run", {"session_id": sid, "request_id": "req-api-0002"})
        s2, b = self.req("POST", "/api/run", {"session_id": sid, "request_id": "req-api-0002"})
        self.assertEqual((s1, s2, a["run"]["run_id"]), (202, 200, b["run"]["run_id"]))
        self.assertTrue(b["idempotent_replay"])
        # edit while running: run superseded; completion later is historical only
        self.req("POST", "/api/claim", {"session_id": sid, "fields": {**HOT, "streak_length": 2}})
        time.sleep(3)
        st, r = self.req("GET", f"/api/run/{a['run']['run_id']}?session_id={sid}")
        self.assertEqual((r["status"], r["authority"]), ("SUPERSEDED", "none"))
        st, s = self.req("GET", f"/api/session/{sid}")
        self.assertIsNone(s["confirmation"])
        self.assertEqual(self.req("POST", "/api/run", {"session_id": sid, "request_id": "req-api-0003"})[0], 409)

    def test_stale_confirmation_refused(self):
        sid = self.session()
        self.req("POST", "/api/claim", {"session_id": sid, "fields": HOT})
        plan = self.req("POST", "/api/plan", {"session_id": sid})[1]["plan"]
        self.req("POST", "/api/page", {"session_id": sid, "url": "https://example.com", "selected_text": "x"})
        st, r = self.req("POST", "/api/confirm", {"session_id": sid, "revision": plan["revision"], "plan_hash": plan["canonical_plan_hash"]})
        self.assertEqual(st, 409)

    def test_real_mode_blocked_not_invented(self):
        sid = self.session()
        plan = self.confirmed(sid, "REAL_NBA_RETROSPECTIVE")
        self.assertFalse(plan["executable"])
        rid = self.req("POST", "/api/run", {"session_id": sid, "request_id": "req-api-real"})[1]["run"]["run_id"]
        r = self.wait(sid, rid)
        self.assertEqual(r["result"]["decision"], "BLOCKED")
        self.assertIn("Research engine not connected", r["result"]["reason"])
        self.assertEqual(self.req("POST", "/api/reveal", {"session_id": sid, "run_id": rid})[0], 409)

    def test_cancel(self):
        sid = self.session()
        self.confirmed(sid)
        rid = self.req("POST", "/api/run", {"session_id": sid, "request_id": "req-api-cncl"})[1]["run"]["run_id"]
        st, c = self.req("POST", "/api/cancel", {"session_id": sid, "run_id": rid})
        self.assertEqual(c["run"]["status"], "CANCELLED")
        time.sleep(3)
        r = self.req("GET", f"/api/run/{rid}?session_id={sid}")[1]
        self.assertEqual((r["status"], r["authority"]), ("CANCELLED", "none"))

    # --- sources
    def test_page_and_screen_sources(self):
        sid = self.session()
        for body, code in [({"url": "file:///etc/passwd", "selected_text": "x"}, 422), ({"url": "chrome://flags", "selected_text": "x"}, 422),
                           ({"url": "https://a.com", "selected_text": "  "}, 422), ({"url": "https://a.com", "selected_text": "ok"}, 201),
                           ({"url": "https://a.com", "selected_text": "x" * (app.MAX_PAGE_TEXT + 1)}, 413)]:
            self.assertEqual(self.req("POST", "/api/page", {"session_id": sid, **body})[0], code, body["url"])
        self.assertEqual(self.req("POST", "/api/screen", {"session_id": sid, "pixel_sha256": "zz"})[0], 422)
        st, r = self.req("POST", "/api/screen", {"session_id": sid, "pixel_sha256": "a" * 64, "width": 10, "height": 10})
        self.assertEqual((st, r["source"]["extracted"]), (201, None))

    def test_file_endpoint(self):
        sid = self.session()
        st, r = self.req("POST", f"/api/file?session_id={sid}", b"player,made\nA,1\n", {"Content-Type": "text/csv", "X-File-Name": "..\\..\\x.csv"})
        self.assertEqual((st, r["source"]["file_name"]), (201, "x.csv"))
        st, r = self.req("POST", f"/api/file?session_id={sid}", b"MZ\x90\x00", {"Content-Type": "text/csv", "X-File-Name": "x.csv"})
        self.assertEqual(st, 422)

    def test_transcribe_blocked_without_provider(self):
        st, r = self.req("POST", "/api/transcribe", b"RIFF....WAVE", {"Content-Type": "audio/wav"})
        self.assertEqual((st, r["error"]), (503, "BLOCKED"))
        self.assertEqual(self.req("POST", "/api/transcribe", b"", {"Content-Type": "audio/wav"})[0], 400)

    # --- market
    def test_market_flow(self):
        st, p = self.req("POST", "/api/market-propose", {"source": "fixture:kalshi_ok"})
        self.assertEqual(p["status"], "PROPOSED")
        st, c = self.req("POST", "/api/market-compare", {"proposal_id": p["proposal_id"], "reviewer": "Chisom O"})
        self.assertEqual((c["status"], c["observed_quote"], c["signed_probability_difference"]), ("OK", "0.5500", "0.0400"))
        self.assertEqual(self.req("POST", "/api/market-compare", {"proposal_id": p["proposal_id"], "reviewer": "x", "quote_type": "last"})[0], 400)
        self.assertEqual(self.req("POST", "/api/market-propose", {"source": "fixture:nope"})[0], 400)
        self.assertEqual(self.req("POST", "/api/market-propose", {"source": "https://evil"})[0], 400)
        st, p = self.req("POST", "/api/market-propose", {"source": "live", "venue": "kalshi", "ref": "BAD TICKER/../x"})
        self.assertEqual(p["status"], "MALFORMED")
        st, p = self.req("POST", "/api/market-propose", {"source": "live", "venue": "predictit", "ref": "x"})
        self.assertEqual(p["status"], "UNSUPPORTED")

    def test_gates_endpoint(self):
        st, g = self.req("GET", "/api/gates")
        self.assertEqual(len(g["gates"]), 18)


if __name__ == "__main__":
    unittest.main()
