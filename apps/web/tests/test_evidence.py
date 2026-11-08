"""Read-only evidence-ledger access (server/evidence.py) against Max's committed ledger."""
import http.client
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
os.environ["HEATCHECK_QUIET"] = "1"
from server import app, evidence  # noqa: E402

LEDGER = os.path.join(evidence.REPO, "reports", "max", "logs", "2026-11-07-loop", "evidence_real_game.jsonl")


@unittest.skipUnless(os.path.isfile(LEDGER), "Max's committed ledger not present on this branch")
class TestEvidenceReader(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def copy(self):
        p = os.path.join(self.tmp, "ledger.jsonl")
        shutil.copyfile(LEDGER, p)
        return p

    def test_committed_ledger_verifies(self):
        out = evidence.read_verified(LEDGER)
        self.assertEqual([e["identity"]["claim"]["claim_id"] for e in out["entries"]], ["HH-K3", "HH-K2", "GP-REST"])
        self.assertEqual([e["identity"]["decision"] for e in out["entries"]],
                         ["INSUFFICIENT_EVIDENCE", "NOT_SUPPORTED", "BLOCKED"])
        self.assertEqual(out["ledger"], "reports/max/logs/2026-11-07-loop/evidence_real_game.jsonl")

    @staticmethod
    def state(p):
        with open(p, "rb") as f:
            return f.read(), os.stat(p).st_mtime_ns

    def test_read_never_writes(self):
        p = self.copy()
        before = self.state(p)
        evidence.read_verified(p)
        self.assertEqual(self.state(p), before)
        missing = os.path.join(self.tmp, "absent.jsonl")
        with self.assertRaises(evidence.EvidenceUnavailable) as e:
            evidence.read_verified(missing)
        self.assertEqual(e.exception.status, "NOT_FOUND")
        self.assertFalse(os.path.exists(missing))      # the writer's constructor would have created it

    def test_tampered_decision_refused(self):
        p = self.copy()
        with open(p, encoding="utf-8") as f:
            lines = f.read().splitlines()
        e = json.loads(lines[1])
        e["identity"]["decision"] = "SURVIVED_PROTOCOL"
        lines[1] = json.dumps(e, sort_keys=True, separators=(",", ":"))
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(lines) + "\n")
        with self.assertRaises(evidence.EvidenceUnavailable) as ex:
            evidence.read_verified(p)
        self.assertEqual(ex.exception.status, "TAMPERED")

    def test_unconfigured_and_wrong_type(self):
        for path, status in ((None, "NOT_CONFIGURED"), (os.path.join(ROOT, "web", "app.js"), "NOT_FOUND")):
            with self.subTest(path=path), self.assertRaises(evidence.EvidenceUnavailable) as e:
                evidence.read_verified(path)
            self.assertEqual(e.exception.status, status)


@unittest.skipUnless(os.path.isfile(LEDGER), "Max's committed ledger not present on this branch")
class TestEvidenceApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = app.make_server(0)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def get(self):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        c.request("GET", "/api/evidence", headers={"Host": f"127.0.0.1:{self.port}"})
        r = c.getresponse()
        body = json.loads(r.read())
        c.close()
        return r.status, body

    def test_endpoint(self):
        old = os.environ.pop("HEATCHECK_LEDGER", None)
        try:
            st, body = self.get()
            self.assertEqual((st, body["error"]), (404, "NOT_CONFIGURED"))
            os.environ["HEATCHECK_LEDGER"] = LEDGER
            st, body = self.get()
            self.assertEqual(st, 200)
            self.assertEqual(len(body["entries"]), 3)
            self.assertIn("heatcheck.ledger.evidence", body["verified_by"])
        finally:
            os.environ.pop("HEATCHECK_LEDGER", None)
            if old is not None:
                os.environ["HEATCHECK_LEDGER"] = old


if __name__ == "__main__":
    unittest.main()
