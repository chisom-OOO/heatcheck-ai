# Rehearsal fixes, 8 November 2026 (Max)

Three bugs from the live rehearsal (demo.cmd --recorded-market, model on, quotes captured 03:48Z).

## 1. Mic button: no prompt, nothing happens

Reproduced in Edge (Playwright `channel="msedge"`):
- **mic available (fake device):** recognition worked. The test audio was transcribed and sent as a
  question.
- **mic blocked:** the page showed the raw code "Speech recognition error: not-allowed".
- **silent paths:**
  - An end with no result and no error left no message.
  - A browser whose API exists but never starts left "Listening" with nothing happening. This is
    the known problem in Opera and Brave.
  - With no speech API (Firefox) the page fell back to `/api/transcribe`, which returns 502 in the
    demo because no transcription provider is configured.

The click handler already reached `rec.start()` with no `await` before it, and the CSP and
Permissions-Policy (`microphone=(self)`) do not block it.

**Fix** (`apps/web/web/voice.js`, `apps/web/web/demo.js`):
- `voiceSupport()` treats no API, Opera and Brave as unsupported. The page then hides the mic
  button and shows "Voice input not supported in this browser, use Edge or Chrome".
- `micErrorMessage()` maps each error code to a line: not-allowed → "Mic blocked: allow it in site
  settings", no-speech → "Didn't catch that", audio-capture, network. Only a user abort is silent.
- `micEndMessage()`: an end with no result says "Didn't catch that".
- A 4 s watchdog: if no `start` event arrives, it says "Voice input isn't responding in this
  browser, use Edge or Chrome".
- The status line shows "Listening…".

**Tests:** `apps/web/tests/voice.test.mjs`, 8 tests. They include `start()` being called before the
click handler returns, and the watchdog.

**Browser (Edge):**

| Case | Result |
|---|---|
| Mic blocked | "Mic blocked: allow it in site settings" |
| Fake mic | transcript asked as a question |
| Opera UA | button hidden, unsupported line |
| No API | button hidden, unsupported line |
| API that never starts | "isn't responding" line |

No page errors (`mic_*.png`, `mic_probe3.py`). A real microphone was NOT tested by Max: no
physical mic session is available to this agent.

## 2. "spurs vs trailblazers?" did not open SAS@POR

`route()` already returned OPEN_CARD for it, because "spurs" alone matched. The real failure was in
the page:
- The board fetched every card's comparison one after another.
- With the model on, each `/api/investigate` call took about 4.2 s, because the server asked the
  model for Heater's line on every card at board load, with an empty message.
- So the named card was focused only after about a minute. The 9 s reproduction showed the board
  open with no card focused and no Heater line.

**Fixes:**
- `market_investigation.investigate` calls the model only for a non-empty fan message. Board load
  now uses the template.
- `heatcheck/agents/scenario.py`:
  - all 30 teams match by full name, city, nickname and short forms ("trailblazers", "blazers",
    "sixers", "cavs", "mavs", "wolves", "t-wolves", "pels", "clips", "wiz", "rip city"…);
  - matching ignores case, spacing and punctuation;
  - safe abbreviations match in any case ("okc"), but "was", "min" and "den" stay ordinary words.
- `route()` returns `under_way`. `card_intro` says "This game is under way, so there's no pre-game
  comparison."

**Browser (second instance on 8775/8776, no model):**
- "spurs vs trailblazers?" focused the SAS@POR card in 8.0 s.
- Heater: "Here's San Antonio Spurs at Portland Trail Blazers. This game is under way, so there's
  no pre-game comparison." (`route_spurs_fixed.png`, `verify2.py`)

## 3. Heater mentioned the Ref's verdict before the Ref spoke

- **Dialogue:**
  - The dialogue's Heater line was written with `refs_verdict` in the model input, and its
    fallbacks quoted the Ref ("the Ref says there's no registered test…").
  - Now `heater_text` is the hot take only. The model gets `{"fan_question"}` only, the fallback is
    verdict-free, and a guard (`take_mentions_ref`) rejects a take that mentions the Ref, a verdict,
    a test, the evidence or the checks.
  - The old verdict lines are now `heater_reaction`, for after the stamp.
- **Market card:**
  - The home-bias sentence moves from `heater_text` to `heater_reaction`.
  - The model no longer gets `refs_verdict` or `known_model_bias`, and the same guard applies.

**Browser:**
- Dialogue: Heater's take is shown before the Ref appears. Ref: NOT ENOUGH EVIDENCE. The page's
  reaction comes after the stamp.
- Market Ask: the first line has no Ref mention.

## For Experience (page changes needed)

1. **Market card reaction:** `askMarket` should speak `resp.heater_reaction` after the stamp. It
   carries the home-bias reaction on home-above-ask cards. Until then, the reaction is not heard.
   The card's caveat text still shows.
2. **Model line on Ask:** to have the model voice a market card, "Ask Heater about this game" should
   POST `/api/investigate` again with a non-empty `message`, e.g. "Walk me through this game", and
   use that response. Board load stays model-free.
3. **Dialogue (optional):** the dialogue API now returns `heater_reaction`, which `ask()` can use
   instead of `reactFor` when present.
4. **Mic:** merge `max/mic-status` (voice.js, demo.js, tests/voice.test.mjs) into
   experience/market-board.

## Checks

| Check | Result |
|---|---|
| Scaffold check | PASS |
| ruff | clean |
| pytest | 778 passed, 29 skipped, 16 xfailed |
| apps/web unittest | OK |
| node | 87 pass |

The running rehearsal demo on 8765 still serves the OLD server Python, because it was not
restarted, as the user asked. The mic fix is live there already, since the page JS is served from
disk.
