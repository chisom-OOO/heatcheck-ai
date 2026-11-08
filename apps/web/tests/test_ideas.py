"""GET /api/ideas: Research's idea-family results, read-only, every hash binding checked.

Fixture: byte copies of research/idea-family@a84bd64 (tests/fixtures/idea_family/PROVENANCE.md).
Tampered copies live in a temporary directory; the fixture is never written.
"""
import hashlib
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
from server import app, ideas  # noqa: E402

FIX = os.path.join(ROOT, "tests", "fixtures", "idea_family")
API_CAPTURE = os.path.join(ROOT, "tests", "fixtures", "idea_family_api.json")


def snapshot(root):
    out = {}
    for base, _, fs in os.walk(root):
        for f in fs:
            p = os.path.join(base, f)
            with open(p, "rb") as fh:
                out[p] = (hashlib.sha256(fh.read()).hexdigest(), os.stat(p).st_mtime_ns)
    return out


class TestReader(unittest.TestCase):
    """Research's families only. Since Max's 1941cdc, read_all(<explicit dir>) carries no
    "proposals" (they belong to the served board); HEATCHECK_PROPOSALS is still pointed at an empty
    directory so a served-board call here could not pick up Max's files. TestProposals covers them."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.copy = os.path.join(self.tmp, "idea-family")
        shutil.copytree(FIX, self.copy)
        self._old_proposals = os.environ.get("HEATCHECK_PROPOSALS")
        os.environ["HEATCHECK_PROPOSALS"] = os.path.join(self.tmp, "no-proposals")

    def tearDown(self):
        if self._old_proposals is None:
            os.environ.pop("HEATCHECK_PROPOSALS", None)
        else:
            os.environ["HEATCHECK_PROPOSALS"] = self._old_proposals
        shutil.rmtree(self.tmp)

    def edit(self, rel, fn, raw=False):
        p = os.path.join(self.copy, rel)
        with open(p, "rb") as f:
            b = f.read()
        if raw:
            b = fn(b)
        else:
            b = json.dumps(fn(json.loads(b)), indent=1).encode()
        with open(p, "wb") as f:
            f.write(b)

    def refused(self):
        return {x["name"]: x["reason"] for x in ideas.read_all(self.copy)["refused"]}

    def test_research_families_verify_and_development_comes_first(self):
        before = snapshot(FIX)
        d = ideas.read_all(FIX)
        self.assertEqual(snapshot(FIX), before)  # read-only
        self.assertEqual(d["refused"], [])
        self.assertEqual([f["name"] for f in d["families"]], ["dev_example", "synthetic_gamma0", "synthetic_gamma030"])
        dev = d["families"][0]
        self.assertEqual((dev["mode"], dev["label"], dev["n_ideas"]), ("development", "EXPLORATORY", 12))
        self.assertEqual(dev["data"]["season"], "2023-24")
        self.assertEqual([r["verdict"] for r in dev["results"]].count("CANDIDATE"), 4)
        self.assertIsNone(dev["scoreboard"])
        g030 = d["families"][2]
        self.assertEqual(g030["scoreboard"]["tally"], {"planted_effects_found": 1, "planted_effects_missed": 8,
                                                       "nulls_correctly_not_flagged": 4, "false_candidates": 0})
        self.assertEqual(g030["truth"]["gamma_logodds"], 0.3)

    def test_committed_api_capture_equals_the_reader_output(self):
        with open(API_CAPTURE, encoding="utf-8") as f:
            self.assertEqual(json.load(f), json.loads(json.dumps(ideas.read_all(FIX))))
        self.assertNotIn("proposals", ideas.read_all(FIX))  # explicit directory: Research's results only

    def test_changed_registration_is_refused(self):
        self.edit("dev_example/registration.json", lambda b: b.replace(b'"B": 999', b'"B": 99'), raw=True)
        self.assertIn("registration_hash differs", self.refused()["dev_example"])

    def test_results_must_list_exactly_the_registered_ideas(self):
        self.edit("dev_example/results.json", lambda d: {**d, "results": d["results"][:-1]})
        self.assertIn("not exactly the registered ideas", self.refused()["dev_example"])

    def test_scoreboard_and_truth_must_cite_these_results(self):
        self.edit("synthetic_gamma030/scoreboard.json", lambda d: {**d, "results_sha256": "0" * 64})
        self.assertIn("scoreboard.json is not bound", self.refused()["synthetic_gamma030"])
        self.edit("synthetic_gamma0/truth.json", lambda d: {**d, "results_sha256": "0" * 64})
        self.assertIn("truth.json is not bound", self.refused()["synthetic_gamma0"])

    def test_scoreboard_without_truth_is_refused(self):
        os.remove(os.path.join(self.copy, "synthetic_gamma0", "truth.json"))
        self.assertIn("without truth.json", self.refused()["synthetic_gamma0"])

    def test_a_confirmatory_word_is_not_an_idea_verdict(self):
        reg = os.path.join(self.copy, "dev_example", "registration.json")

        def change(d):
            d["results"][0]["verdict"] = "SURVIVED_PROTOCOL"
            return d
        self.edit("dev_example/results.json", change)
        # results.json changed but still cites the registration: the verdict rule refuses it
        self.assertTrue(os.path.isfile(reg))
        self.assertIn("is not one of", self.refused()["dev_example"])

    def test_non_strict_json_is_refused(self):
        self.edit("dev_example/results.json", lambda b: b.replace(b'"p_raw": 0.162', b'"p_raw": NaN', 1), raw=True)
        self.assertIn("not strict JSON", self.refused()["dev_example"])
        self.edit("synthetic_gamma0/results.json", lambda b: b.replace(b'"mode": "synthetic"', b'"mode": "synthetic", "mode": "development"', 1), raw=True)
        self.assertIn("duplicate key", self.refused()["synthetic_gamma0"])

    def test_missing_directory_is_a_plain_404_reason(self):
        with self.assertRaises(ideas.IdeasUnavailable) as c:
            ideas.read_all(os.path.join(self.tmp, "nope"))
        self.assertIn("not merged", str(c.exception))


class TestProposals(unittest.TestCase):
    """Heater-proposed families (Max's read_proposals): shown NOT_RUN only when the request
    file's ideas equal the model's parsed ideas. Uses Max's committed files in data/max/idea_requests."""
    REQ_DIR = ideas.PROPOSALS_DIR
    NAME = "does_rest_matter_heater_dev"

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._old = os.environ.pop("HEATCHECK_PROPOSALS", None)

    def tearDown(self):
        os.environ.pop("HEATCHECK_PROPOSALS", None)
        if self._old is not None:
            os.environ["HEATCHECK_PROPOSALS"] = self._old
        shutil.rmtree(self.tmp)

    def test_committed_model_proposal_is_listed_not_run(self):
        if not os.path.isfile(os.path.join(self.REQ_DIR, self.NAME + ".model_output.json")):
            self.skipTest("no committed model proposal in data/max/idea_requests")
        out, refused = ideas.read_proposals()
        self.assertEqual(refused, [])
        p = next(x for x in out if x["name"] == self.NAME)
        self.assertEqual(p["status"], "NOT_RUN")
        with open(os.path.join(self.REQ_DIR, self.NAME + ".json"), "rb") as f:
            req = f.read()
        self.assertEqual(p["request_sha256"], hashlib.sha256(req).hexdigest())
        self.assertEqual(len(p["ideas"]), len(json.loads(req)["ideas"]))
        # the keyword-fallback request has no model output beside it, so it is not listed
        self.assertNotIn("does_rest_matter_dev", [x["name"] for x in out])

    def test_request_not_matching_the_model_output_is_refused(self):
        if not os.path.isfile(os.path.join(self.REQ_DIR, self.NAME + ".model_output.json")):
            self.skipTest("no committed model proposal in data/max/idea_requests")
        d = os.path.join(self.tmp, "req")
        os.mkdir(d)
        for suffix in (".json", ".model_output.json"):
            shutil.copyfile(os.path.join(self.REQ_DIR, self.NAME + suffix), os.path.join(d, self.NAME + suffix))
        p = os.path.join(d, self.NAME + ".json")
        with open(p, encoding="utf-8") as f:
            req = json.load(f)
        req["ideas"] = req["ideas"][:-1]
        with open(p, "w", encoding="utf-8") as f:
            json.dump(req, f)
        os.environ["HEATCHECK_PROPOSALS"] = d
        out, refused = ideas.read_proposals()
        self.assertEqual(out, [])
        self.assertEqual(refused, [{"name": self.NAME, "reason": "proposal: request file does not match the model's parsed ideas"}])


class TestRoute(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = app.make_server(0)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        os.environ.pop("HEATCHECK_IDEAS", None)

    def get(self):
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_address[1], timeout=10)
        c.request("GET", "/api/ideas")
        r = c.getresponse()
        out = (r.status, json.loads(r.read()))
        c.close()
        return out

    def test_route_serves_the_verified_families(self):
        os.environ["HEATCHECK_IDEAS"] = FIX
        status, body = self.get()
        self.assertEqual(status, 200)
        self.assertEqual(len(body["families"]), 3)

    def test_route_says_why_when_there_are_no_results(self):
        os.environ["HEATCHECK_IDEAS"] = os.path.join(FIX, "does-not-exist")
        status, body = self.get()
        self.assertEqual((status, body["error"]), (404, "NOT_FOUND"))
        self.assertIn("research/idea-family is not merged", body["message"])


if __name__ == "__main__":
    unittest.main()
