"""One Meta Model API probe call. Never prints the key.

usage: probe.py OUT.json MODEL EFFORT|- MAX_COMPLETION_TOKENS STREAM(0/1)
       probe.py OUT.json --list-models
"""
import json, os, sys, time, urllib.request, urllib.error

BASE = "https://api.meta.ai/v1"
key = os.environ.get("META_API_KEY")
if not key:
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as h:
        key = winreg.QueryValueEx(h, "META_API_KEY")[0]
H = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
PROMPT = ("You are Heater, a loud, original sports-debate pundit. In at most two short "
          "sentences, give a hot take on: 'Is the hot hand in basketball real?'")
out_path = sys.argv[1]
rec = {"utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
t0 = time.perf_counter()
try:
    if sys.argv[2] == "--list-models":
        rec["request"] = "GET /v1/models"
        with urllib.request.urlopen(urllib.request.Request(BASE + "/models", headers=H), timeout=30) as r:
            rec["http_status"], rec["response_raw"] = r.status, r.read().decode()
    else:
        model, effort, mct, stream = sys.argv[2], sys.argv[3], int(sys.argv[4]), sys.argv[5] == "1"
        body = {"model": model, "messages": [{"role": "user", "content": PROMPT}],
                "max_completion_tokens": mct}
        if effort != "-":
            body["reasoning_effort"] = effort
        if stream:
            body["stream"] = True
            body["stream_options"] = {"include_usage": True}
        rec["request"] = body
        req = urllib.request.Request(BASE + "/chat/completions", data=json.dumps(body).encode(),
                                     method="POST", headers=H)
        with urllib.request.urlopen(req, timeout=60) as r:
            rec["http_status"] = r.status
            if not stream:
                raw = r.read().decode()
                rec["response_raw"] = raw
                d = json.loads(raw)
                rec["text"] = d["choices"][0]["message"]["content"]
                rec["finish_reason"] = d["choices"][0]["finish_reason"]
                rec["usage"] = d.get("usage")
            else:
                text, first, events = [], None, 0
                for line in r:
                    line = line.decode().strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    events += 1
                    d = json.loads(data)
                    if d.get("usage"):
                        rec["usage"] = d["usage"]
                    for c in d.get("choices") or []:
                        piece = (c.get("delta") or {}).get("content")
                        if piece:
                            if first is None:
                                first = time.perf_counter()
                            text.append(piece)
                        if c.get("finish_reason"):
                            rec["finish_reason"] = c["finish_reason"]
                rec["text"] = "".join(text) or None
                rec["sse_events"] = events
                rec["first_text_ms"] = round((first - t0) * 1000, 1) if first else None
except urllib.error.HTTPError as e:
    rec["http_status"], rec["response_raw"] = e.code, e.read().decode("utf-8", "replace")
except Exception as e:
    rec["http_status"], rec["error"] = None, f"{type(e).__name__}: {e}"
rec["total_ms"] = round((time.perf_counter() - t0) * 1000, 1)
s = json.dumps(rec, indent=2).replace(key, "[REDACTED]")
open(out_path, "w", encoding="utf-8").write(s)
print(s[:1500])
