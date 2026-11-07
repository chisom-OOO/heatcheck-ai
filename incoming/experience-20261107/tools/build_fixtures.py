"""Regenerate contracts/fixtures/{valid,invalid} from real outputs of this build.
Valid fixtures are produced by the code paths themselves; invalid ones are single-defect mutations.
Run: python3 -I tools/build_fixtures.py  (from the repo root)"""
import copy, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
from server import app, comparison, engine_fixture, quotes, venue_fixtures
from server.authority import Session

V = os.path.join(ROOT, "contracts", "fixtures", "valid")
I = os.path.join(ROOT, "contracts", "fixtures", "invalid")
for d in (V, I):
    os.makedirs(d, exist_ok=True)
    for f in os.listdir(d):
        os.remove(os.path.join(d, f))

def dump(d, name, obj):
    with open(os.path.join(d, name), "w") as f:
        json.dump(quotes.to_jsonable(obj), f, indent=1, sort_keys=True)

s = Session("fixture-session")
s.edit(claim={"kind": "hot_hand", "channel": "SHOT_ASSOCIATION", "population": {"type": "group", "label": "players"},
              "streak_length": 3, "setting": "free throws only", "comparator": "within-player permutation null",
              "direction": "positive", "statement": "Players shoot better after three makes", "claim_id": "clm_fixture"})
plan = app.build_plan(s, "SYNTHETIC")
dump(V, "ClaimPlan.json", plan)
s.confirm(plan["revision"], plan["canonical_plan_hash"])
run, _ = s.start_run("req-fixture-0001")
cust = engine_fixture.Custodian(42, "parametric_beta_binomial", "planted")
data = cust.generate()
res = engine_fixture.analyse({"sequences": data["sequences"], "shooters": data["shooters"]}, plan, lambda *a: None, lambda: False)
import hashlib, numpy as np
dh = hashlib.sha256(np.ascontiguousarray(data["sequences"]).tobytes()).hexdigest()
dump(V, "EvaluationRun.json", app.evaluation_envelope(s, run["run_id"], plan, res, dh))
dump(V, "AttackResult.json", app.attack_envelopes(plan, res, dh)[0])

t = venue_fixtures.transport("kalshi_ok")
p = comparison.propose("kalshi", venue_fixtures.K_TICKER, venue_fixtures.GAME, venue_fixtures.FORECAST, t)
spec = {k: v for k, v in p["spec"].items()}
dump(V, "MarketSpec.json", spec)
dump(V, "EventMapping.json", p["mapping"])
from server.venues import adapter
snap = adapter("kalshi", venue_fixtures.transport("kalshi_ok")).get_book(spec, venue_fixtures.K_TICKER + ":yes")
dump(V, "BookSnapshot.json", snap)
cmp_ = comparison.compare(spec, p["mapping"], venue_fixtures.FORECAST, venue_fixtures.transport("kalshi_ok"), "Fixture Reviewer", "midpoint")
dump(V, "MarketComparison.json", cmp_)

# invalid: one defect each
for name in os.listdir(V):
    env = name[:-5]
    obj = json.load(open(os.path.join(V, name)))
    from server.contracts import REQUIRED
    first = sorted(REQUIRED[env])[0]
    bad = copy.deepcopy(obj); del bad[first]
    dump(I, f"{env}__missing_{first}.json", bad)
for env, field, val in [("MarketComparison", "forecast_probability", 1.7), ("EvaluationRun", "decision", "LUCKY"),
                        ("MarketComparison", "data_mode", "LIVE"), ("ClaimPlan", "protocol_version", "heatcheck-nba/0")]:
    obj = json.load(open(os.path.join(V, env + ".json"))); obj[field] = val
    dump(I, f"{env}__bad_{field}.json", obj)
with open(os.path.join(I, "AttackResult__nan_statistic.json"), "w") as f:
    f.write(open(os.path.join(V, "AttackResult.json")).read().replace('"statistic": ', '"statistic": NaN, "_was": ', 1))
print("valid:", sorted(os.listdir(V))); print("invalid:", len(os.listdir(I)))
