# Voice input via Meta transcription (Max, 8 Nov 2026)

**Default in every browser:**
1. The mic records with getUserMedia: tap to start and stop, or hold and release; it stops at 30 s.
2. The page encodes 16 kHz mono 16-bit PCM WAV in the browser (`encodeWav`).
3. It POSTs the clip to `/api/transcribe`. The page server forwards it to Max's API.
4. `heatcheck/api/transcription.py` sends multipart to `https://api.meta.ai/v1/asr/transcribe`:
   - a `request` part: `{"model":"muse-voice-transcribe-1.0","audioEncoding":"WAV","mode":"PUSH_TO_TALK"}`;
   - an `audio` part: `answer.wav`, `audio/wav`;
   - the header `Authorization: Bearer META_API_KEY`, server-side only.
5. The transcript goes into the question box, to confirm or edit before Ask.

**Guards:**
- Clips are capped at 2 MB, between 0.2 s and 30 s, and must be 16 kHz mono 16-bit PCM.
- Rate limit: 12 clips per 60 s per process. There is no tunnel in this repo, so there is no
  tunnel limit to join.
- Each call is logged to `logs/llm_usage.jsonl` with role `transcribe`, duration, bytes, status and
  est_cost_usd. The cost is a stand-in of $0.01/min, labelled "not a published price": no
  published per-minute price was found, and Unbluffable used the same stand-in.
- `audio_stored` is always false. The key never appears in errors or logs (tested).
- Clear errors: mic blocked, no microphone, didn't catch that, too long, busy, service unavailable.

**Fallback:**
- If the service fails, the next tap uses the browser's own speech recognition where it runs.
- Opera and Brave expose the speech API without running it, so they get no fallback. Their
  recording path works.
- The "not supported in this browser" message for Opera is removed.

**The old 502:** the page server's own `/api/transcribe` is replaced by forwarding to Max's API. The
502 seen earlier came from Max's probe posting the 1-byte body "x", not a WAV.

**Reference:** the API call shape follows Unbluffable `voice/provider.py` `transcribe()` (API call
only). The code is HeatCheck's own, and the README disclosures credit it.

## Real test (one real Meta call per browser)

There is no physical microphone on this machine. Windows text-to-speech produced
"Spurs versus Trail Blazers. Who wins tonight?" as a 16 kHz WAV, and the browser was given it as
its microphone (`--use-file-for-fake-audio-capture`). The real page then recorded it, encoded it and
posted it through a keyed verification instance (ports 8775/8776) to the real API.

| Browser | Transcript | Audio | Provider time |
|---|---|---|---|
| Edge | "Spurs versus Trailblazers who wins tonight." | 4.44 s | 2.0 s |
| Opera 139 (`OPR/139`) | "Spurs versus Trailblazers. Who wins tonight? Spurs versus" (the fake mic loops the file) | 6.0 s | 1.4 s |

- The status went Listening → Transcribing → "Check the question, edit it if needed, then press
  Ask". Nothing was asked automatically, and there were no page errors.
- `real_voice_box.png`, `real_voice_opera.png`, `real_voice.py`, `real_voice_opera.py`.
- The transcript routes to SAS@POR (OPEN_CARD nba:0022600195).

A human-voice test with a real microphone is NOT done by Max: the user can do it on the demo.

## Tests

- `tests/integration/test_transcription.py`, 23 tests: multipart shape, key only in the header,
  every refusal before any call, provider errors, usage log, rate limit, HTTP route.
- `apps/web/tests/voice.test.mjs`, 10 tests: support (Opera, Firefox, Chrome), WAV bytes, error
  lines, the default path posting WAV, fallback after a service failure, mic blocked, auto-stop.
- `apps/web/tests/test_api.py`: the page server forwards `/api/transcribe` and caps it at 2 MB.

**A defect found and fixed:** the route answered 413 or 503 before reading the upload, so the
client sometimes saw a reset connection (2 failures in 15 runs). The route now reads (or drains up
to 8 MB) before answering; 20 of 20 runs pass afterwards.
