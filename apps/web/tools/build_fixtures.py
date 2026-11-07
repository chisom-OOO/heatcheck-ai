"""Regenerate fixtures/envelopes/{valid,invalid} from real outputs of this build.

Valid fixtures are produced by the code paths themselves; invalid ones are single-defect
mutations. Run from apps/web:  python -I tools/build_fixtures.py
"""
import copy
import hashlib
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
V = os.path.join(ROOT, "fixtures", "envelopes", "valid")
INVALID = os.path.join(ROOT, "fixtures", "envelopes", "invalid")


def dump(directory, name, obj, quotes):
    with open(os.path.join(directory, name), "w", encoding="utf-8", newline="\n") as f:
        json.dump(quotes.to_jsonable(obj), f, indent=1, sort_keys=True)


def load(directory, name):
    with open(os.path.join(directory, name), encoding="utf-8") as f:
        return json.load(f)


def main():
    sys.path.insert(0, ROOT)
    import numpy as np
    from server import app, comparison, engine_fixture, quotes, venue_fixtures
    from server.authority import Session
    from server.contracts import REQUIRED
    from server.venues import adapter

    for d in (V, INVALID):
        os.makedirs(d, exist_ok=True)
        for f in os.listdir(d):
            os.remove(os.path.join(d, f))

    s = Session("fixture-session")
    s.edit(claim={"kind": "hot_hand", "channel": "SHOT_ASSOCIATION",
                  "population": {"type": "group", "label": "players"},
                  "streak_length": 3, "setting": "free throws only",
                  "comparator": "within-player permutation null", "direction": "positive",
                  "statement": "Players shoot better after three makes",
                  "claim_id": "clm_fixture"})
    plan = app.build_plan(s, "SYNTHETIC")
    dump(V, "ClaimPlan.json", plan, quotes)
    s.confirm(plan["revision"], plan["canonical_plan_hash"])
    run, _ = s.start_run("req-fixture-0001")
    cust = engine_fixture.Custodian(42, "parametric_beta_binomial", "planted")
    data = cust.generate()
    res = engine_fixture.analyse({"sequences": data["sequences"], "shooters": data["shooters"]},
                                 plan, lambda *a: None, lambda: False)
    dh = hashlib.sha256(np.ascontiguousarray(data["sequences"]).tobytes()).hexdigest()
    dump(V, "EvaluationRun.json", app.evaluation_envelope(s, run["run_id"], plan, res, dh), quotes)
    dump(V, "AttackResult.json", app.attack_envelopes(plan, res, dh)[0], quotes)

    t = venue_fixtures.transport("kalshi_ok")
    p = comparison.propose("kalshi", venue_fixtures.K_TICKER, venue_fixtures.GAME,
                           venue_fixtures.FORECAST, t)
    spec = dict(p["spec"])
    dump(V, "MarketSpec.json", spec, quotes)
    dump(V, "EventMapping.json", p["mapping"], quotes)
    snap = adapter("kalshi", venue_fixtures.transport("kalshi_ok")).get_book(
        spec, venue_fixtures.K_TICKER + ":yes")
    dump(V, "BookSnapshot.json", snap, quotes)
    cmp_ = comparison.compare(spec, p["mapping"], venue_fixtures.FORECAST,
                              venue_fixtures.transport("kalshi_ok"), "Fixture Reviewer", "midpoint")
    dump(V, "MarketComparison.json", cmp_, quotes)

    # invalid: one defect each
    for name in sorted(os.listdir(V)):
        env = name[:-5]
        obj = load(V, name)
        first = sorted(REQUIRED[env])[0]
        bad = copy.deepcopy(obj)
        del bad[first]
        dump(INVALID, f"{env}__missing_{first}.json", bad, quotes)
    for env, field, val in [("MarketComparison", "forecast_probability", 1.7),
                            ("EvaluationRun", "decision", "LUCKY"),
                            ("MarketComparison", "data_mode", "LIVE"),
                            ("ClaimPlan", "protocol_version", "heatcheck-nba/0")]:
        obj = load(V, env + ".json")
        obj[field] = val
        dump(INVALID, f"{env}__bad_{field}.json", obj, quotes)
    with open(os.path.join(V, "AttackResult.json"), encoding="utf-8") as f:
        text = f.read().replace('"statistic": ', '"statistic": NaN, "_was": ', 1)
    with open(os.path.join(INVALID, "AttackResult__nan_statistic.json"), "w", encoding="utf-8",
              newline="\n") as f:
        f.write(text)
    print("valid:", sorted(os.listdir(V)))
    print("invalid:", len(os.listdir(INVALID)))


if __name__ == "__main__":
    main()
