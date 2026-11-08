"""POST /api/transcribe: Meta Voice Transcribe behind Max's API, with a mocked provider."""
from __future__ import annotations

import io
import json
import threading
import urllib.error
import urllib.request
import wave

import pytest

from heatcheck.api.dialogue_server import serve
from heatcheck.api.transcription import (
    ENDPOINT,
    MAX_BYTES,
    REQUEST_PART,
    RateLimiter,
    TranscribeError,
    Transcriber,
    estimated_cost,
    multipart,
    wav_seconds,
)

KEY = "test-key-not-real-0123456789"


def wav(seconds=1.0, rate=16000, channels=1, width=2) -> bytes:
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(b"\x00\x01" * int(seconds * rate) * channels * (width // 2 or 1))
    return b.getvalue()


class FakeMeta:
    def __init__(self, status=200, body=None, exc=None):
        self.status, self.body, self.exc, self.calls = status, body, exc, []

    def __call__(self, url, headers, body, timeout):
        self.calls.append((url, headers, body, timeout))
        if self.exc:
            raise self.exc
        return self.status, json.dumps(self.body if self.body is not None else {"transcript": "spurs vs blazers"}).encode()


def make(tmp_path, meta=None, limiter=None):
    meta = meta or FakeMeta()
    return Transcriber(KEY, post=meta, usage_log=tmp_path / "usage.jsonl", limiter=limiter), meta


def log(tmp_path):
    return [json.loads(x) for x in (tmp_path / "usage.jsonl").read_text().splitlines()]


# ------------------------------------------------------------------ request shape

def test_request_is_the_documented_multipart_with_the_key_only_in_the_header(tmp_path):
    t, meta = make(tmp_path)
    audio = wav(1.2)
    out = t.transcribe(audio)
    assert out["transcript"] == "spurs vs blazers" and out["raw_audio_retained"] is False
    url, headers, body, timeout = meta.calls[0]
    assert url == ENDPOINT == "https://api.meta.ai/v1/asr/transcribe" and timeout == 30
    assert headers["Authorization"] == f"Bearer {KEY}"
    assert headers["Content-Type"].startswith("multipart/form-data; boundary=")
    assert KEY.encode() not in body
    assert b'name="request"' in body and json.dumps(REQUEST_PART).encode() in body
    assert REQUEST_PART == {"model": "muse-voice-transcribe-1.0", "audioEncoding": "WAV", "mode": "PUSH_TO_TALK"}
    assert b'name="audio"; filename="answer.wav"' in body and b"Content-Type: audio/wav" in body
    assert audio in body


def test_multipart_is_well_formed():
    body, ctype = multipart(b"WAVDATA", "BOUNDARY")
    assert ctype == "multipart/form-data; boundary=BOUNDARY"
    assert body.startswith(b"--BOUNDARY\r\n") and body.endswith(b"\r\n--BOUNDARY--\r\n")
    assert body.count(b"--BOUNDARY\r\n") == 2


# ------------------------------------------------------------------ input checks (no call made)

@pytest.mark.parametrize("audio,code", [
    (b"", "NO_AUDIO"),
    (b"x" * (MAX_BYTES + 1), "TOO_LARGE"),
    (b"RIFF....WAVE", "BAD_AUDIO"),
    (wav(1, rate=44100), "BAD_AUDIO"),
    (wav(1, channels=2), "BAD_AUDIO"),
    (wav(0.05), "NOTHING_HEARD"),
    (wav(31.5), "TOO_LARGE"),
], ids=["empty", "over-2MB", "not-wav", "44k", "stereo", "too-short", "over-30s"])
def test_bad_clips_are_refused_before_any_call(tmp_path, audio, code):
    t, meta = make(tmp_path)
    with pytest.raises(TranscribeError) as e:
        t.transcribe(audio)
    assert e.value.code == code and meta.calls == []
    assert KEY not in e.value.message


def test_wav_seconds_of_a_good_clip():
    assert wav_seconds(wav(2.5)) == pytest.approx(2.5)


# ------------------------------------------------------------------ provider answers

@pytest.mark.parametrize("meta,status,code", [
    (FakeMeta(200, {"transcript": "  "}), 422, "NOTHING_HEARD"),
    (FakeMeta(200, {}), 422, "NOTHING_HEARD"),
    (FakeMeta(400, {"error": {"message": "bad audio"}}), 502, "SERVICE_UNAVAILABLE"),
    (FakeMeta(401, {"error": "unauthorized"}), 502, "SERVICE_UNAVAILABLE"),
    (FakeMeta(429, {}), 429, "RATE_LIMITED"),
    (FakeMeta(500, {}), 502, "SERVICE_UNAVAILABLE"),
    (FakeMeta(exc=urllib.error.URLError("dns")), 502, "SERVICE_UNAVAILABLE"),
], ids=["blank", "no-field", "400", "401", "429", "500", "network"])
def test_provider_failures_are_clear_and_never_carry_the_key(tmp_path, meta, status, code):
    t, _ = make(tmp_path, meta)
    with pytest.raises(TranscribeError) as e:
        t.transcribe(wav(1))
    assert (e.value.status, e.value.code) == (status, code)
    assert KEY not in e.value.message
    assert KEY not in (tmp_path / "usage.jsonl").read_text()


def test_no_key_means_off_and_no_call(tmp_path):
    meta = FakeMeta()
    t = Transcriber("", post=meta, usage_log=tmp_path / "u.jsonl")
    with pytest.raises(TranscribeError) as e:
        t.transcribe(wav(1))
    assert (e.value.status, e.value.code) == (503, "SERVICE_UNAVAILABLE") and meta.calls == []


# ------------------------------------------------------------------ logging, cost, rate limit

def test_usage_log_has_duration_and_cost_and_no_audio(tmp_path):
    t, _ = make(tmp_path)
    t.transcribe(wav(3.0))
    rec = log(tmp_path)[-1]
    assert rec["role"] == "transcribe" and rec["status"] == "OK" and rec["audio_seconds"] == 3.0
    assert rec["est_cost_usd"] == estimated_cost(3.0) == 0.0005
    assert "not a published price" in rec["est_cost_basis"] and rec["audio_stored"] is False
    assert set(rec) <= {"utc", "role", "model", "status", "http_status", "latency_ms", "audio_seconds",
                        "audio_bytes", "est_cost_usd", "est_cost_basis", "request_id", "audio_stored"}


def test_failed_calls_are_logged_too(tmp_path):
    t, _ = make(tmp_path, FakeMeta(500, {}))
    with pytest.raises(TranscribeError):
        t.transcribe(wav(1))
    assert log(tmp_path)[-1]["status"] == "HTTP_500"


def test_rate_limit(tmp_path):
    now = [0.0]
    t, meta = make(tmp_path, limiter=RateLimiter(2, 60, clock=lambda: now[0]))
    t.transcribe(wav(1))
    t.transcribe(wav(1))
    with pytest.raises(TranscribeError) as e:
        t.transcribe(wav(1))
    assert e.value.code == "RATE_LIMITED" and len(meta.calls) == 2
    now[0] = 61
    t.transcribe(wav(1))
    assert len(meta.calls) == 3


# ------------------------------------------------------------------ HTTP route on Max's server

class _NoDialogue:
    def turn(self, q):
        raise AssertionError("not used")


@pytest.fixture
def server(tmp_path):
    def start(transcriber):
        srv = serve(_NoDialogue(), 0, None, None, None, transcriber)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        servers.append(srv)
        return f"http://127.0.0.1:{srv.server_address[1]}"
    servers = []
    yield start
    for s in servers:
        s.shutdown()
        s.server_close()


def post_audio(base, body, ctype="audio/wav"):
    req = urllib.request.Request(base + "/api/transcribe", data=body, method="POST", headers={"Content-Type": ctype})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_http_route_returns_the_transcript(tmp_path, server):
    t, meta = make(tmp_path)
    base = server(t)
    status, out = post_audio(base, wav(1))
    assert status == 200 and out["transcript"] == "spurs vs blazers"


def test_http_route_errors(tmp_path, server):
    base = server(make(tmp_path)[0])
    assert post_audio(base, wav(1), "text/plain")[0] == 415
    assert post_audio(base, b"x" * (MAX_BYTES + 10))[1]["error"] == "TOO_LARGE"
    assert post_audio(base, wav(0.05))[1]["error"] == "NOTHING_HEARD"
    off = server(None)
    assert post_audio(off, wav(1)) == (503, {"error": "SERVICE_UNAVAILABLE",
                                            "message": "Voice transcription is off on this server."})
