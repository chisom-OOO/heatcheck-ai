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
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.copy = os.path.join(self.tmp, "idea-family")
        shutil.copytree(FIX, self.copy)

    def tearDown(self):
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

    def _write_note(self, fam, **over):
        with open(os.path.join(self.copy, fam, "results.json"), "rb") as f:
            sha = hashlib.sha256(f.read()).hexdigest()
        note = {"format": "heatcheck-idea-family-note/1", "kind": "LEAD_NOT_FINDING",
                "cites_results_sha256": sha, "note": "Lead, not finding. Holm is applied within each family."}
        note.update(over)
        with open(os.path.join(self.copy, fam, "NOTE.json"), "w") as f:
            json.dump(note, f)

    def _family(self, name):
        return next(f for f in ideas.read_all(self.copy)["families"] if f["name"] == name)

    def test_research_note_is_shown_only_when_it_cites_these_results(self):
        self.assertNotIn("research_note", self._family("dev_example"))           # no note: field absent
        self._write_note("dev_example")
        f = self._family("dev_example")
        self.assertTrue(f["research_note"].startswith("Lead, not finding."))
        self.assertIn("Research's note cites these results", f["checks"])
        self._write_note("dev_example", cites_results_sha256="0" * 64)          # stale note
        f = self._family("dev_example")
        self.assertIsNone(f["research_note"])
        self.assertTrue(any("not shown" in c and "cites_results_sha256" in c for c in f["checks"]))
        self._write_note("dev_example", format="other/1")
        self.assertIsNone(self._family("dev_example")["research_note"])

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
