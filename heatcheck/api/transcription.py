"""Server-side voice transcription for the demo page: POST /api/transcribe (Max, 8 Nov 2026).

The page records one push-to-talk clip, encodes it in the browser as 16 kHz mono 16-bit PCM WAV and
posts the bytes here. This module checks the clip, forwards it to Meta's Voice Transcribe API as
multipart/form-data and returns ``{"transcript": ...}``. The page puts the transcript in the
question box for the user to confirm or edit; nothing is asked automatically.

- The key is read from META_API_KEY on the server and only ever sent in the Authorization header.
  Error messages and the usage log never contain it.
- Audio is never stored: it is held in memory for one request and dropped. The usage log records
  duration, size, status and estimated cost only.
- Clips are capped at 2 MB and 30 s, and a sliding-window rate limit applies per server process.

API shape (request part, audio part, endpoint) follows the team's earlier project Unbluffable
(github.com/chisom-OOO/unbluffable, voice/provider.py transcribe()), used as a reference for the
API call only; this is HeatCheck's own code.
"""
from __future__ import annotations

import io
import json
import os
import threading
import time
import uuid
import wave
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from heatcheck.agents.llm import DEFAULT_USAGE_LOG

ENDPOINT = "https://api.meta.ai/v1/asr/transcribe"
MODEL = "muse-voice-transcribe-1.0"
REQUEST_PART = {"model": MODEL, "audioEncoding": "WAV", "mode": "PUSH_TO_TALK"}
MAX_BYTES = 2 * 1024 * 1024
MAX_SECONDS = 30.0
MIN_SECONDS = 0.2
RATE = 16000
TIMEOUT_S = 30
# Voice Transcribe reports no tokens and no published per-minute price was found. Same stand-in as
# the team's earlier project, labelled as such in every log line.
USD_PER_MINUTE = 0.01
COST_BASIS = "stand-in $0.01/min, not a published price"
RATE_LIMIT = (12, 60.0)  # at most 12 clips per 60 s per server process

Post = Callable[[str, dict, bytes, float], tuple[int, bytes]]


class TranscribeError(Exception):
    """A clear, user-facing failure. ``code`` is stable for the page; ``message`` is safe to show."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message

    def body(self) -> dict:
        return {"error": self.code, "message": self.message}


# ------------------------------------------------------------------ pure checks

def wav_seconds(audio: bytes) -> float:
    """Duration of a 16 kHz mono 16-bit PCM WAV; anything else is refused (never converted)."""
    if not audio:
        raise TranscribeError(400, "NO_AUDIO", "No audio was received. Hold the mic button and speak.")
    if len(audio) > MAX_BYTES:
        raise TranscribeError(413, "TOO_LARGE", "That recording is too long. Keep it under 30 seconds.")
    try:
        with wave.open(io.BytesIO(audio), "rb") as w:
            ch, width, rate, frames = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
            comp = w.getcomptype()
    except (wave.Error, EOFError) as e:
        raise TranscribeError(415, "BAD_AUDIO", f"The recording is not a valid WAV ({type(e).__name__}).") from None
    if (ch, width, rate, comp) != (1, 2, RATE, "NONE"):
        raise TranscribeError(415, "BAD_AUDIO", "Send 16 kHz mono 16-bit PCM WAV.")
    seconds = frames / rate
    if seconds < MIN_SECONDS:
        raise TranscribeError(422, "NOTHING_HEARD", "Didn't catch that: the recording was too short.")
    if seconds > MAX_SECONDS + 0.5:
        raise TranscribeError(413, "TOO_LARGE", "That recording is too long. Keep it under 30 seconds.")
    return seconds


def multipart(audio: bytes, boundary: str) -> tuple[bytes, str]:
    """The two-part body: "request" (JSON settings) and "audio" (answer.wav, audio/wav)."""
    head = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"request\"\r\n"
            f"Content-Type: application/json\r\n\r\n{json.dumps(REQUEST_PART)}\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"audio\"; filename=\"answer.wav\"\r\n"
            f"Content-Type: audio/wav\r\n\r\n").encode()
    return head + audio + f"\r\n--{boundary}--\r\n".encode(), f"multipart/form-data; boundary={boundary}"


def estimated_cost(seconds: float) -> float:
    return round(seconds / 60 * USD_PER_MINUTE, 6)


# ------------------------------------------------------------------ rate limit

class RateLimiter:
    def __init__(self, limit: int = RATE_LIMIT[0], window_s: float = RATE_LIMIT[1], clock=time.monotonic):
        self.limit, self.window_s, self.clock = limit, window_s, clock
        self._hits: deque[float] = deque()
        self._lock = threading.Lock()

    def allow(self) -> bool:
        with self._lock:
            now = self.clock()
            while self._hits and now - self._hits[0] >= self.window_s:
                self._hits.popleft()
            if len(self._hits) >= self.limit:
                return False
            self._hits.append(now)
            return True


# ------------------------------------------------------------------ the call

def _urllib_post(url: str, headers: dict, body: bytes, timeout: float) -> tuple[int, bytes]:
    import urllib.error
    import urllib.request
    req = urllib.request.Request(url, data=body, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(1_000_000)
    except urllib.error.HTTPError as e:
        return e.code, e.read(100_000)


class Transcriber:
    def __init__(self, api_key: str | None = None, *, post: Post | None = None,
                 usage_log: Path = DEFAULT_USAGE_LOG, limiter: RateLimiter | None = None):
        self._key = api_key if api_key is not None else os.environ.get("META_API_KEY")
        self._post = post or _urllib_post
        self.usage_log = Path(usage_log)
        self.limiter = limiter or RateLimiter()
        self._lock = threading.Lock()

    @property
    def configured(self) -> bool:
        return bool(self._key)

    def transcribe(self, audio: bytes) -> dict:
        if not self._key:
            raise TranscribeError(503, "SERVICE_UNAVAILABLE", "Voice transcription is off on this server.")
        seconds = wav_seconds(audio)
        if not self.limiter.allow():
            raise TranscribeError(429, "RATE_LIMITED", "Too many recordings in a minute. Wait a moment and try again.")
        body, ctype = multipart(audio, uuid.uuid4().hex)
        headers = {"Authorization": f"Bearer {self._key}", "Content-Type": ctype, "Accept": "application/json"}
        t0 = time.perf_counter()
        status, raw, rid = None, b"", None
        try:
            status, raw = self._post(ENDPOINT, headers, body, TIMEOUT_S)
        except Exception as e:  # network failure: never echo anything that could carry the key
            self._log("NETWORK_ERROR", t0, seconds, len(audio), None, None)
            raise TranscribeError(502, "SERVICE_UNAVAILABLE",
                                  f"The voice service could not be reached ({type(e).__name__}).") from None
        try:
            data = json.loads(raw or b"{}")
        except ValueError:
            data = {}
        rid = data.get("request_id") or data.get("id") if isinstance(data, dict) else None
        if status != 200:
            self._log(f"HTTP_{status}", t0, seconds, len(audio), status, rid)
            if status == 429:
                raise TranscribeError(429, "RATE_LIMITED", "The voice service is busy. Try again in a moment.")
            raise TranscribeError(502, "SERVICE_UNAVAILABLE", f"The voice service answered HTTP {status}.")
        text = data.get("transcript") if isinstance(data, dict) else None
        self._log("OK" if isinstance(text, str) and text.strip() else "EMPTY", t0, seconds, len(audio), status, rid)
        if not isinstance(text, str) or not text.strip():
            raise TranscribeError(422, "NOTHING_HEARD", "Didn't catch that. Try again, a little closer to the mic.")
        return {"transcript": text.strip(), "provider": MODEL, "audio_seconds": round(seconds, 2),
                "provider_ms": round((time.perf_counter() - t0) * 1000), "raw_audio_retained": False}

    def _log(self, status, t0, seconds, size, http_status, rid):
        rec = {"utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"), "role": "transcribe",
               "model": MODEL, "status": status, "http_status": http_status,
               "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
               "audio_seconds": round(seconds, 3), "audio_bytes": size,
               "est_cost_usd": estimated_cost(seconds), "est_cost_basis": COST_BASIS,
               "request_id": rid, "audio_stored": False}
        self.usage_log.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, open(self.usage_log, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(rec, sort_keys=True) + "\n")
