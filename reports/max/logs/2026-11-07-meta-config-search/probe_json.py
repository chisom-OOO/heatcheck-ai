"""One structured-output probe: map a user question to a registered claim id or NONE.

usage: probe_json.py OUT.json MODEL EFFORT QUESTION
"""
import json, os, sys, time, urllib.request, urllib.error

key = os.environ["META_API_KEY"]
CAT = [{"claim_id": "HH-K3", "statement": "Within a player-game, a field goal after 3 straight makes is made more often than one after 3 straight misses."},
       {"claim_id": "HH-K2", "statement": "Same as HH-K3 with streak length 2."},
       {"claim_id": "GP-REST", "statement": "Rest-day difference and back-to-backs improve pre-tip win forecasts over Elo."}]
schema = {"type": "object", "additionalProperties": False, "required": ["claim_id"],
          "properties": {"claim_id": {"type": "string", "enum": [c["claim_id"] for c in CAT] + ["NONE"]}}}
body = {"model": sys.argv[2], "reasoning_effort": sys.argv[3], "max_completion_tokens": 512,
        "messages": [{"role": "system", "content": "Map the user's question to exactly one registered claim id, or NONE if no claim tests it. Registered claims: " + json.dumps(CAT)},
                     {"role": "user", "content": sys.argv[4]}],
        "response_format": {"type": "json_schema", "json_schema": {"name": "claim_mapping", "strict": True, "schema": schema}}}
rec = {"utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "request": body}
t0 = time.perf_counter()
try:
    req = urllib.request.Request("https://api.meta.ai/v1/chat/completions", data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        rec["http_status"], raw = r.status, r.read().decode()
    d = json.loads(raw)
    rec.update(text=d["choices"][0]["message"]["content"], finish_reason=d["choices"][0]["finish_reason"], usage=d.get("usage"))
except urllib.error.HTTPError as e:
    rec["http_status"], rec["response_raw"] = e.code, e.read().decode("utf-8", "replace")
except Exception as e:
    rec["http_status"], rec["error"] = None, f"{type(e).__name__}: {e}"
rec["total_ms"] = round((time.perf_counter() - t0) * 1000, 1)
s = json.dumps(rec, indent=2).replace(key, "[REDACTED]")
open(sys.argv[1], "w", encoding="utf-8").write(s)
print(json.dumps({k: rec.get(k) for k in ("http_status", "text", "finish_reason", "usage", "total_ms", "response_raw", "error")}, indent=1))
