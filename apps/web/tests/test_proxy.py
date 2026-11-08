"""The UI server's pass-through to Max's dialogue API, against a mock of Max's server.

The mock answers with responses captured from Max's real server code
(tests/fixtures/max_api/captures.json, written by tools/capture_max_api.py). The page calls
relative /api/... URLs only; these tests check that the UI server forwards Max's endpoints with
method, body, status and Content-Type unchanged, that the demo page is what / serves, and that the
page code holds no absolute API URL. No real network and no real Max server are used.
"""
import http.client
import json
import os
import re
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
os.environ["HEATCHECK_QUIET"] = "1"
from server import app  # noqa: E402

CAPTURES = os.path.join(ROOT, "tests", "fixtures", "max_api", "captures.json")
with open(CAPTURES, encoding="utf-8") as _f:
    EXCHANGES = json.load(_f)["exchanges"]


def exchange(name):
    return next(e for e in EXCHANGES if e["name"] == name)


class MockMax(BaseHTTPRequestHandler):
    """Answers like Max's server: the captured response for a matching method, path and body."""
    protocol_version = "HTTP/1.1"
    seen = []

    def log_message(self, *a):
        pass

    def _answer(self, method):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        req = json.loads(raw) if raw else None
        MockMax.seen.append({"method": method, "path": self.path, "body": raw,
                             "content_type": self.headers.get("Content-Type"),
                             "origin": self.headers.get("Origin")})
        hit = next((e for e in EXCHANGES if e["method"] == method and e["path"] == self.path
                    and e["request"] == req and not e.get("test_forecast")), None)
        status, body = (hit["status"], hit["body"]) if hit else (404, {"error": "not found"})
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self._answer("GET")

    def do_POST(self):
        self._answer("POST")


def serve(server):
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server


class TestPassThrough(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mock = serve(ThreadingHTTPServer(("127.0.0.1", 0), MockMax))
        os.environ["HEATCHECK_DIALOGUE_API"] = f"http://127.0.0.1:{cls.mock.server_address[1]}"
        cls.ui = serve(app.make_server(0))
        cls.port = cls.ui.server_address[1]

    @classmethod
    def tearDownClass(cls):
        for s in (cls.ui, cls.mock):
            s.shutdown()
            s.server_close()
        os.environ.pop("HEATCHECK_DIALOGUE_API", None)

    def setUp(self):
        MockMax.seen.clear()

    def req(self, method, path, body=None, raw=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
        h = {"Content-Type": "application/json"} if data is not None else {}
        h.update(headers or {})
        c.request(method, path, body=data, headers=h)
        r = c.getresponse()
        out = (r.status, r.getheader("Content-Type"), r.read())
        c.close()
        return out

    def test_every_captured_exchange_passes_through_unchanged(self):
        for e in EXCHANGES:
            if e.get("test_forecast") or e["name"] == "unknown_path":
                continue
            with self.subTest(e["name"]):
                status, ctype, data = self.req(e["method"], e["path"], e["request"])
                self.assertEqual(status, e["status"])
                self.assertEqual(ctype, "application/json")
                self.assertEqual(data, json.dumps(e["body"]).encode())  # bytes exactly as Max sent them

    def test_request_body_and_method_reach_max_unchanged(self):
        raw = b'{"game_id": "nba:0022600190", "mapping_id": "x",   "message": "rest?"}'
        self.req("POST", "/api/investigate", raw=raw)
        self.assertEqual(MockMax.seen[-1]["method"], "POST")
        self.assertEqual(MockMax.seen[-1]["path"], "/api/investigate")
        self.assertEqual(MockMax.seen[-1]["body"], raw)
        self.assertEqual(MockMax.seen[-1]["content_type"], "application/json")
        self.assertIsNone(MockMax.seen[-1]["origin"])  # server to server: no browser Origin

    def test_max_error_statuses_come_back_as_is(self):
        e = exchange("dialogue_bad_body")
        status, _, data = self.req("POST", "/api/dialogue", e["request"])
        self.assertEqual((status, json.loads(data)), (400, e["body"]))
        e = exchange("investigate_unknown_game")
        status, _, data = self.req("POST", "/api/investigate", e["request"])
        self.assertEqual((status, json.loads(data)), (404, e["body"]))

    def test_home_advantage_answer_is_the_confirmatory_survived_record(self):
        status, _, data = self.req("POST", "/api/dialogue", {"question": "Do home teams win more?"})
        body = json.loads(data)
        self.assertEqual(status, 200)
        self.assertEqual((body["claim_id"], body["verdict"], body["lane"]),
                         ("CONF-HA", "SURVIVED_PROTOCOL", "CONFIRMATORY"))
        self.assertIn("unseen 2024-25 games", body["ref_text"])

    def test_same_origin_post_is_accepted_cross_origin_refused(self):
        e = exchange("dialogue_home_advantage")
        ok = self.req("POST", "/api/dialogue", e["request"], headers={"Origin": f"http://127.0.0.1:{self.port}"})
        self.assertEqual(ok[0], 200)
        bad = self.req("POST", "/api/dialogue", e["request"], headers={"Origin": "http://evil.example"})
        self.assertEqual(bad[0], 403)
        self.assertEqual(len(MockMax.seen), 1)  # the refused request never reached Max

    def test_scenario_is_forwarded_with_its_query_string(self):
        # Max's server has no /api/scenario yet: his own 404 must come back unchanged.
        status, _, data = self.req("GET", "/api/scenario?game_id=nba%3A0022600190")
        self.assertEqual((status, json.loads(data)), (404, exchange("unknown_path")["body"]))
        self.assertEqual(MockMax.seen[-1]["method"], "GET")
        self.assertEqual(MockMax.seen[-1]["path"], "/api/scenario?game_id=nba%3A0022600190")

    def test_local_routes_are_not_forwarded(self):
        status, _, _ = self.req("GET", "/api/health")
        self.assertEqual(status, 200)
        status, _, data = self.req("GET", "/api/nope")  # not one of Max's endpoints: the UI's own 404
        self.assertEqual((status, json.loads(data)["error"]), (404, "NO_ROUTE"))
        self.assertEqual(MockMax.seen, [])

    def test_upstream_down_is_a_plain_502(self):
        dead = ThreadingHTTPServer(("127.0.0.1", 0), MockMax)
        port = dead.server_address[1]
        dead.server_close()  # nothing listens there now
        old = os.environ["HEATCHECK_DIALOGUE_API"]
        os.environ["HEATCHECK_DIALOGUE_API"] = f"http://127.0.0.1:{port}"
        try:
            status, _, data = self.req("GET", "/api/live-forecast")
        finally:
            os.environ["HEATCHECK_DIALOGUE_API"] = old
        self.assertEqual(status, 502)
        self.assertEqual(json.loads(data)["error"], "UPSTREAM_UNAVAILABLE")

    def test_upstream_must_be_loopback(self):
        old = os.environ["HEATCHECK_DIALOGUE_API"]
        try:
            for bad in ("http://example.com:8770", "https://127.0.0.1:8770", "http://10.0.0.1:8770",
                        "http://127.0.0.1:8770/other"):
                os.environ["HEATCHECK_DIALOGUE_API"] = bad
                with self.subTest(bad):
                    self.assertEqual(self.req("GET", "/api/live-forecast")[0], 500)
        finally:
            os.environ["HEATCHECK_DIALOGUE_API"] = old
        self.assertEqual(MockMax.seen, [])

    def test_root_serves_the_demo_page(self):
        status, ctype, data = self.req("GET", "/")
        with open(os.path.join(ROOT, "web", "demo.html"), "rb") as f:
            self.assertEqual(data, f.read())
        self.assertEqual((status, ctype), (200, "text/html; charset=utf-8"))
        self.assertEqual(self.req("GET", "/index.html")[0], 200)  # the older workspace UI stays reachable

    def test_csp_allows_same_origin_only(self):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request("GET", "/demo.html")
        r = c.getresponse()
        r.read()
        csp = r.getheader("Content-Security-Policy")
        c.close()
        self.assertIn("connect-src 'self';", csp)
        self.assertNotIn("8770", csp)
        # Google Fonts only, and only for styles and font files (the two name-label fonts)
        directives = dict(d.strip().split(" ", 1) for d in csp.split(";"))
        self.assertEqual(directives["script-src"], "'self'")
        self.assertEqual(directives["style-src"], "'self' https://fonts.googleapis.com")
        self.assertEqual(directives["font-src"], "'self' https://fonts.gstatic.com")
        self.assertEqual(directives["default-src"], "'self'")


class TestPageUsesRelativeUrls(unittest.TestCase):
    def test_no_absolute_api_url_in_page_code(self):
        files = ["demo.js", "demo.html", os.path.join("market", "board.js"), os.path.join("market", "board-model.js"),
                 os.path.join("market", "scenario.js"), os.path.join("market", "scenario-model.js"),
                 os.path.join("ideas", "idea-board.js"), os.path.join("ideas", "idea-model.js")]
        for name in files:
            with open(os.path.join(ROOT, "web", name), encoding="utf-8") as f:
                src = f.read()
            with self.subTest(name):
                self.assertIsNone(re.search(r"https?://(127\.0\.0\.1|localhost)", src))
                self.assertNotIn("8770", src)


class TestMappingIndex(unittest.TestCase):
    def test_default_index_is_the_newest_capture_run_and_has_no_prices(self):
        os.environ.pop("HEATCHECK_QUOTE_INDEX", None)
        p = app.newest_quote_index()
        self.assertIsNotNone(p)
        self.assertTrue(p.endswith("board.mappings.json"))
        with open(p, encoding="utf-8") as f:
            text = f.read()
        for word in ("best_bid", "best_ask", "price", "p_home_win"):
            self.assertNotIn(f'"{word}"', text)


if __name__ == "__main__":
    unittest.main()
