"""Read-only access to Research's idea-family results for the demo page's idea board.

Format: heatcheck-idea-family/1 (docs/IDEA_GRAMMAR.md on research/idea-family). Each family
directory holds ``registration.json`` (written before any computation), ``results.json``
(written once, bound to the registration by ``registration_hash`` = sha256 of its bytes) and,
for a synthetic family, ``truth.json`` and ``scoreboard.json`` (both bound to the results by
``results_sha256``). A family is shown only when every binding holds; otherwise it is listed
under ``refused`` with the reason, and nothing from it is shown. Nothing here computes a verdict
or a number: the board words Research's.
"""
import hashlib
import json
import os

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
DEFAULT_DIR = os.path.join(REPO, "handoff", "research-20261107", "evidence", "idea-family")
FORMAT = "heatcheck-idea-family/1"
VERDICTS = ("CANDIDATE", "NOT_A_CANDIDATE", "INSUFFICIENT_EVIDENCE")
TEMPLATES = {"GAME_HOME_WIN_SPLIT": "feature", "SHOT_MAKE_AFTER_CONDITION": "condition"}
RESULT_FIELDS = ("idea_hash", "template", "params", "status", "n_condition", "n_rest", "rate_condition",
                 "rate_rest", "T", "null_mean", "B_effective", "p_raw", "p_holm", "verdict")
MAX_BYTES = 2 * 1024 * 1024


class IdeasUnavailable(Exception):
    def __init__(self, status, msg):
        super().__init__(msg)
        self.status = status


class Refused(Exception):
    pass


PROPOSALS_DIR = os.path.join(REPO, "data", "max", "idea_requests")


def read_proposals(root=None):
    """Heater-proposed families not yet run by Research: each ``<name>.model_output.json`` (the
    model's raw text and call record) with its ``<name>.json`` request. Shown only when the request's
    ideas equal the ideas parsed from the model output; otherwise listed as refused. NOT_RUN always."""
    root = root or os.environ.get("HEATCHECK_PROPOSALS") or PROPOSALS_DIR
    out, refused = [], []
    if not os.path.isdir(root):
        return out, refused
    for name in sorted(os.listdir(root)):
        if not name.endswith(".model_output.json"):
            continue
        stem = name[: -len(".model_output.json")]
        try:
            _, raw = _load(os.path.join(root, name))
            req_path = os.path.join(root, stem + ".json")
            with open(req_path, "rb") as fh:
                req_bytes = fh.read()
            _, req = _load(req_path)
            parsed = [x["idea"] for x in raw.get("parsed_ideas") or []]
            if not str(raw.get("source", "")).startswith("LLM"):
                raise Refused("not proposed by the model (keyword fallback)")
            if req.get("format") != FORMAT or req.get("ideas") != parsed:
                raise Refused("request file does not match the model's parsed ideas")
            calls = raw.get("llm_calls") or []
            out.append({"name": stem, "message": raw.get("message"), "mode": raw.get("mode"),
                        "created_utc": raw.get("created_utc"), "status": "NOT_RUN",
                        "request_file": os.path.relpath(req_path, REPO).replace(os.sep, "/"),
                        "request_sha256": hashlib.sha256(req_bytes).hexdigest(),
                        "model": calls[-1].get("model") if calls else None,
                        "ideas": [{"template": i["template"], "params": i["params"]} for i in req["ideas"]]})
        except (Refused, OSError, ValueError, KeyError, TypeError) as e:
            refused.append({"name": stem, "reason": f"proposal: {e}"})
    return out, refused


def configured_dir():
    return os.environ.get("HEATCHECK_IDEAS") or DEFAULT_DIR


def _reject(c):
    raise ValueError(f"non-finite number {c}")


def _dupes(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise ValueError(f"duplicate key {k!r}")
        out[k] = v
    return out


def _load(path):
    """(bytes, object) with strict JSON: no NaN/Infinity, no duplicate keys."""
    with open(path, "rb") as f:
        raw = f.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise Refused(f"{os.path.basename(path)} is larger than {MAX_BYTES} bytes")
    try:
        return raw, json.loads(raw.decode("utf-8"), parse_constant=_reject, object_pairs_hook=_dupes)
    except (UnicodeDecodeError, ValueError) as e:
        raise Refused(f"{os.path.basename(path)} is not strict JSON ({e})") from None


def _sha(b):
    return hashlib.sha256(b).hexdigest()


def _num(x):
    return x is None or (isinstance(x, (int, float)) and not isinstance(x, bool))


def _result(r, i):
    if not isinstance(r, dict) or not all(k in r for k in ("idea_hash", "template", "params", "verdict", "p_holm")):
        raise Refused(f"results[{i}] lacks a required field")
    if r["template"] not in TEMPLATES:
        raise Refused(f"results[{i}].template {r['template']!r} is unknown")
    p = r["params"]
    key = TEMPLATES[r["template"]]
    if (not isinstance(p, dict) or set(p) != {key, "level", "alternative"}
            or not all(isinstance(v, str) for v in p.values())):
        raise Refused(f"results[{i}].params do not follow the grammar")
    if r["verdict"] not in VERDICTS:
        raise Refused(f"results[{i}].verdict {r['verdict']!r} is not one of {list(VERDICTS)}")
    for k in ("n_condition", "n_rest", "rate_condition", "rate_rest", "T", "null_mean", "p_raw", "p_holm"):
        if not _num(r.get(k)):
            raise Refused(f"results[{i}].{k} is not a number")
    return {k: r.get(k) for k in RESULT_FIELDS}


def read_family(d):
    """One verified family, or raise Refused."""
    reg_raw, reg = _load(os.path.join(d, "registration.json"))
    res_raw, res = _load(os.path.join(d, "results.json"))
    for name, doc in (("registration", reg), ("results", res)):
        if not isinstance(doc, dict) or doc.get("format") != FORMAT:
            raise Refused(f"{name}.json is not {FORMAT}")
    if res.get("registration_hash") != _sha(reg_raw):
        raise Refused("results.json does not cite this registration.json (registration_hash differs)")
    if res.get("mode") not in ("development", "synthetic") or res.get("mode") != reg.get("mode"):
        raise Refused("mode missing or differs between registration and results")
    if res.get("label") != "EXPLORATORY":
        raise Refused("results label is not EXPLORATORY")
    rows = res.get("results")
    if not isinstance(rows, list) or not rows:
        raise Refused("results.json lists no ideas")
    registered = [x.get("idea_hash") for x in reg.get("ideas") or [] if isinstance(x, dict)]
    if sorted(registered) != sorted(r.get("idea_hash") for r in rows if isinstance(r, dict)):
        raise Refused("the ideas in results.json are not exactly the registered ideas")
    if not (res.get("n_ideas") == reg.get("n_ideas") == len(rows)):
        raise Refused("n_ideas differs between registration, results and the list")
    results = [_result(r, i) for i, r in enumerate(rows)]
    res_sha = _sha(res_raw)
    fam = {"name": os.path.basename(d), "mode": res["mode"], "label": res["label"], "n_ideas": res["n_ideas"],
           "alpha": res.get("alpha"), "B": res.get("B"), "data_scope": res.get("data_scope"),
           "verdict_meaning": res.get("verdict_meaning"), "created_utc": res.get("created_utc"),
           "multiplicity": reg.get("multiplicity"), "registered_utc": reg.get("created_utc"),
           "registration_hash": res["registration_hash"], "results_sha256": res_sha,
           "data": {k: (reg.get("data_identity") or {}).get(k) for k in ("season", "split", "n_games", "n_fga")},
           "results": results, "truth": None, "scoreboard": None,
           "checks": ["registration_hash matches registration.json", "ideas match the registration"]}
    note_path = os.path.join(d, "NOTE.json")
    if os.path.isfile(note_path):  # Research's plain-words note on the family (e.g. "lead, not finding")
        fam["research_note"] = None
        try:
            _, note = _load(note_path)
            text = note.get("note") if isinstance(note, dict) else None
            if not isinstance(note, dict) or note.get("format") != "heatcheck-idea-family-note/1":
                raise Refused("NOTE.json is not heatcheck-idea-family-note/1")
            if note.get("cites_results_sha256") != res_sha:
                raise Refused("NOTE.json does not cite these results (cites_results_sha256 differs)")
            if not isinstance(text, str) or not text.strip() or len(text) > 2000:
                raise Refused("NOTE.json has no usable note text")
            fam["research_note"] = text
            fam["checks"].append("Research's note cites these results")
        except (Refused, OSError) as e:
            fam["checks"].append(f"Research's note not shown: {e}")
    if res["mode"] == "synthetic":
        has_sb = os.path.isfile(os.path.join(d, "scoreboard.json"))
        has_truth = os.path.isfile(os.path.join(d, "truth.json"))
        if has_sb and not has_truth:
            raise Refused("scoreboard.json without truth.json")
        if has_truth:
            _, truth = _load(os.path.join(d, "truth.json"))
            if not isinstance(truth, dict) or truth.get("results_sha256") != res_sha or truth.get("revealed_after") != "results.json":
                raise Refused("truth.json is not bound to these results (results_sha256 / revealed_after)")
            fam["truth"] = {k: truth.get(k) for k in ("simulator_family", "gamma_logodds", "seed", "planted_label",
                                                      "synthetic_period_labels", "created_utc")}
            fam["checks"].append("truth.json was written after and cites these results")
        if has_sb:
            _, sb = _load(os.path.join(d, "scoreboard.json"))
            if not isinstance(sb, dict) or sb.get("results_sha256") != res_sha:
                raise Refused("scoreboard.json is not bound to these results (results_sha256)")
            tally = sb.get("tally")
            if not isinstance(tally, dict) or not all(isinstance(v, int) for v in tally.values()):
                raise Refused("scoreboard tally is not a set of counts")
            per = [{k: x.get(k) for k in ("idea_hash", "params", "truth", "true_direction", "verdict", "p_holm", "outcome")}
                   for x in sb.get("per_idea") or [] if isinstance(x, dict)]
            if sorted(x["idea_hash"] for x in per) != sorted(r["idea_hash"] for r in results):
                raise Refused("scoreboard ideas are not the family's ideas")
            fam["scoreboard"] = {"tally": tally, "per_idea": per}
            fam["checks"].append("scoreboard.json cites these results")
    return fam


def _link_runs(proposals, families, root):
    """A proposal is RAN only when Research's PROVENANCE_*.json in the idea-family directory names this
    proposal's exact request_sha256 and a family that passed every binding check here, with exactly the
    proposal's ideas. Then the proposal carries that family's results (Research's verdicts)."""
    by_name = {f["name"]: f for f in families}
    for name in sorted(os.listdir(root)):
        if not (name.startswith("PROVENANCE_") and name.endswith(".json")):
            continue
        try:
            _, prov = _load(os.path.join(root, name))
        except Refused:
            continue
        fam = by_name.get(prov.get("family_dir")) if isinstance(prov, dict) else None
        if fam is None:
            continue
        for p in proposals:
            if p["status"] != "NOT_RUN" or prov.get("request_sha256") != p["request_sha256"]:
                continue
            ran = [{"template": r["template"], "params": r["params"]} for r in fam["results"]]
            if ran != p["ideas"]:
                continue  # same hash cited but different ideas: not linked
            p.update(status="RAN", family=fam["name"], provenance=name, results=fam["results"],
                     n_candidates=sum(r["verdict"] == "CANDIDATE" for r in fam["results"]))


def read_all(root=None):
    root = root or configured_dir()
    if not os.path.isdir(root):
        raise IdeasUnavailable("NOT_FOUND", "no idea-family results in this checkout "
                                            "(Research's research/idea-family is not merged here)")
    families, refused = [], []
    for name in sorted(os.listdir(root)):
        d = os.path.join(root, name)
        if not os.path.isfile(os.path.join(d, "results.json")):
            continue
        try:
            families.append(read_family(d))
        except (Refused, OSError) as e:
            refused.append({"name": name, "reason": str(e)})
    proposals, p_refused = read_proposals()
    refused += p_refused
    _link_runs(proposals, families, root)
    if not families and not refused and not proposals:
        raise IdeasUnavailable("NOT_FOUND", "the idea-family directory holds no results.json")
    families.sort(key=lambda f: (f["mode"] != "development", f["name"]))
    rel = os.path.relpath(root, REPO).replace(os.sep, "/")
    return {"format": FORMAT, "source": rel if not rel.startswith("..") else os.path.basename(root),
            "families": families, "refused": refused, "proposals": proposals}
