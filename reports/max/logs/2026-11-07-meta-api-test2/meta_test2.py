"""One minimal Meta Model API call. Never prints the key."""
import json, os, sys, time, urllib.request, urllib.error

def get_key():
    k = os.environ.get("META_API_KEY")
    if k:
        return k, "process"
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as h:
        return winreg.QueryValueEx(h, "META_API_KEY")[0], "HKCU\\Environment"

key, src = get_key()
url = "https://api.meta.ai/v1/chat/completions"
EFFORT = sys.argv[2]
body = {"model": "muse-spark-1.3",
        "messages": [{"role": "user", "content": "Reply with exactly: pong"}],
        "max_tokens": 256, "reasoning_effort": EFFORT}
req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                             headers={"Authorization": f"Bearer {key}",
                                      "Content-Type": "application/json"})
t0 = time.perf_counter()
try:
    with urllib.request.urlopen(req, timeout=60) as r:
        status, raw = r.status, r.read().decode("utf-8", "replace")
except urllib.error.HTTPError as e:
    status, raw = e.code, e.read().decode("utf-8", "replace")
except Exception as e:  # network-level
    status, raw = None, f"{type(e).__name__}: {e}"
ms = (time.perf_counter() - t0) * 1000
raw = raw.replace(key, "[REDACTED]")
out = {"reasoning_effort": EFFORT, "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "key_source": src,
       "url": url, "request_body": body, "http_status": status,
       "latency_ms": round(ms, 1), "response_raw": raw}
json.dump(out, open(sys.argv[1], "w", encoding="utf-8"), indent=2)
print(json.dumps({k: v for k, v in out.items() }, indent=2))
