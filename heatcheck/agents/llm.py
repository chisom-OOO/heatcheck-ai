"""Server-side Meta Model API client for the dialogue layer (Heater, Challenger, Ref phrasing).

Not a kernel: this module does HTTP and appends to a usage log. Nothing here decides a verdict.

* The key comes from META_API_KEY in the server's environment only. It is never logged,
  returned or placed in an exception message.
* Every call has a hard wall-clock deadline (default 8 s). On timeout, HTTP error, network
  error, empty text or a finish_reason other than "stop", ``complete`` raises LLMUnavailable
  and the caller falls back to its deterministic stand-in or template.
* Every attempted call appends one JSON line to the usage log (tokens, latency, status,
  estimated cost). Prompts and responses are not written to the usage log.

Config found in reports/max/2026-11-07-1716-meta-config-search.md: muse-spark-1.3,
reasoning_effort "minimal", max_completion_tokens 1024 (first streamed text ~1.4 s).
"""

from __future__ import annotations

import concurrent.futures as cf
import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

BASE_URL = "https://api.meta.ai/v1"
DEFAULT_MODEL = "muse-spark-1.3"
DEFAULT_EFFORT = "minimal"
DEFAULT_MAX_COMPLETION_TOKENS = 1024
DEFAULT_TIMEOUT_S = 8.0
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_USAGE_LOG = ROOT / "logs" / "llm_usage.jsonl"

# USD per 1M tokens, Standard mode, dev.meta.ai/docs/pricing-rate-limits read 2026-11-07.
PRICES = {"muse-spark-1.3": (1.25, 0.15, 4.25), "muse-spark-1.2": (1.25, 0.15, 4.25),
          "muse-spark-1.1": (1.25, 0.15, 4.25), "muse-wonder-1.0": (4.00, 0.20, 20.00)}
# Contributor variants let Meta train on our data (Max role doc §07 forbids that opt-in).
FORBIDDEN_MODEL_SUFFIXES = ("-contributor",)


class LLMUnavailable(RuntimeError):
    """The provider gave no usable text. ``reason`` is safe to show (never contains the key)."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass
class LLMResult:
    text: str
    model: str
    effort: str
    latency_ms: float
    first_text_ms: float | None
    usage: dict[str, Any]
    request_id: str | None


class Transport(Protocol):
    """POST JSON, yield response lines (streaming) or return the body. Injectable for tests."""

    def post(self, url: str, headers: dict, body: bytes, timeout: float) -> tuple[int, Iterator[bytes]]: ...


class UrllibTransport:
    def post(self, url, headers, body, timeout):
        req = urllib.request.Request(url, data=body, method="POST", headers=headers)
        try:
            r = urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            return e.code, iter([e.read()])
        return r.status, iter(r)


def _cost(model: str, usage: dict) -> float | None:
    p = PRICES.get(model)
    if not p or not usage:
        return None
    cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
    prompt = (usage.get("prompt_tokens") or 0) - cached
    return round((prompt * p[0] + cached * p[1] + (usage.get("completion_tokens") or 0) * p[2]) / 1e6, 8)


@dataclass
class MetaChat:
    model: str = DEFAULT_MODEL
    effort: str = DEFAULT_EFFORT
    max_completion_tokens: int = DEFAULT_MAX_COMPLETION_TOKENS
    timeout_s: float = DEFAULT_TIMEOUT_S
    usage_log: Path = DEFAULT_USAGE_LOG
    transport: Transport = field(default_factory=UrllibTransport)
    api_key: str | None = None  # tests only; production reads META_API_KEY at call time
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self):
        if self.model.endswith(FORBIDDEN_MODEL_SUFFIXES):
            raise ValueError(f"model {self.model!r} is a contributor (training opt-in) variant")

    @property
    def identity(self) -> dict:
        return {"provider": "meta", "base_url": BASE_URL, "model": self.model,
                "reasoning_effort": self.effort, "max_completion_tokens": self.max_completion_tokens}

    # ------------------------------------------------------------------ public

    def complete(self, role: str, messages: list[dict], *, response_format: dict | None = None,
                 stream: bool = False, on_text: Callable[[str], None] | None = None) -> LLMResult:
        """One chat completion with a hard deadline. Raises LLMUnavailable on any failure."""
        key = self.api_key or os.environ.get("META_API_KEY")
        t0 = time.perf_counter()
        if not key:
            self._log(role, stream, "NO_KEY", t0, None, {}, None)
            raise LLMUnavailable("META_API_KEY not set on the server")
        body = {"model": self.model, "messages": messages,
                "max_completion_tokens": self.max_completion_tokens,
                "reasoning_effort": self.effort}
        if response_format:
            body["response_format"] = response_format
        if stream:
            body["stream"] = True
            body["stream_options"] = {"include_usage": True}
        deadline = t0 + self.timeout_s
        pool = cf.ThreadPoolExecutor(max_workers=1)
        fut = pool.submit(self._call, key, body, stream, deadline, on_text)
        try:
            status, res = fut.result(timeout=self.timeout_s)
        except cf.TimeoutError:
            self._log(role, stream, "TIMEOUT", t0, None, {}, None)
            raise LLMUnavailable(f"no complete reply within {self.timeout_s:g} s") from None
        except LLMUnavailable as e:
            self._log(role, stream, e.reason.split(":")[0], t0, None, {}, None)
            raise
        except Exception as e:  # network error etc.; message may not contain the key
            self._log(role, stream, "ERROR", t0, None, {}, None)
            raise LLMUnavailable(f"provider error: {type(e).__name__}") from None
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        res.latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        self._log(role, stream, status, t0, res.first_text_ms, res.usage, res.request_id)
        if status != "OK":
            raise LLMUnavailable(status)
        return res

    # ------------------------------------------------------------------ internals

    def _call(self, key, body, stream, deadline, on_text):
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        t0 = time.perf_counter()
        remaining = max(0.1, deadline - t0)
        code, lines = self.transport.post(BASE_URL + "/chat/completions", headers,
                                          json.dumps(body).encode(), remaining)
        if code != 200:
            raw = b"".join(lines)[:300].decode("utf-8", "replace").replace(key, "[REDACTED]")
            raise LLMUnavailable(f"HTTP_{code}: {raw}")
        if not stream:
            d = json.loads(b"".join(lines))
            ch = d["choices"][0]
            res = LLMResult(ch["message"].get("content") or "", body["model"], body["reasoning_effort"],
                            0.0, None, d.get("usage") or {}, d.get("id"))
            return self._status(res, ch.get("finish_reason")), res
        parts, first, finish, usage, rid = [], None, None, {}, None
        for raw in lines:
            if time.perf_counter() > deadline:
                raise LLMUnavailable("TIMEOUT: stream exceeded deadline")
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            d = json.loads(data)
            rid = rid or d.get("id")
            usage = d.get("usage") or usage
            for c in d.get("choices") or []:
                piece = (c.get("delta") or {}).get("content")
                if piece:
                    if first is None:
                        first = round((time.perf_counter() - t0) * 1000, 1)
                    parts.append(piece)
                    if on_text:
                        on_text(piece)
                finish = c.get("finish_reason") or finish
        res = LLMResult("".join(parts), body["model"], body["reasoning_effort"], 0.0, first, usage, rid)
        return self._status(res, finish), res

    @staticmethod
    def _status(res: LLMResult, finish) -> str:
        if not res.text.strip():
            return f"EMPTY_TEXT (finish_reason={finish})"
        if finish != "stop":
            return f"FINISH_{finish}"
        return "OK"

    def _log(self, role, stream, status, t0, first_ms, usage, rid):
        u = usage or {}
        rec = {"utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"), "role": role,
               "model": self.model, "reasoning_effort": self.effort, "stream": stream,
               "status": status, "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
               "first_text_ms": first_ms, "prompt_tokens": u.get("prompt_tokens"),
               "completion_tokens": u.get("completion_tokens"),
               "reasoning_tokens": (u.get("completion_tokens_details") or {}).get("reasoning_tokens"),
               "cached_tokens": (u.get("prompt_tokens_details") or {}).get("cached_tokens"),
               "est_cost_usd": _cost(self.model, u), "request_id": rid}
        self.usage_log.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, open(self.usage_log, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(rec, sort_keys=True) + "\n")


def prompt_sha256(messages: list[dict], response_format: dict | None = None) -> str:
    return hashlib.sha256(json.dumps([messages, response_format], sort_keys=True,
                                     ensure_ascii=False).encode()).hexdigest()


def usage_summary(path: Path = DEFAULT_USAGE_LOG) -> dict:
    """Totals from the usage log, for spend checks."""
    calls = ok = 0
    cost = 0.0
    tokens = {"prompt": 0, "completion": 0, "reasoning": 0}
    if Path(path).exists():
        for line in Path(path).read_text("utf-8").splitlines():
            r = json.loads(line)
            calls += 1
            ok += r["status"] == "OK"
            cost += r.get("est_cost_usd") or 0.0
            tokens["prompt"] += r.get("prompt_tokens") or 0
            tokens["completion"] += r.get("completion_tokens") or 0
            tokens["reasoning"] += r.get("reasoning_tokens") or 0
    return {"calls": calls, "ok": ok, "est_cost_usd": round(cost, 6), "tokens": tokens}
