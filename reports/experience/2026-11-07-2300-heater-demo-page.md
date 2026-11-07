# Experience report: Heater demo page, the real pose set and the personality file

Written 2026-11-07 23:00 local time.
- **Branch:** `experience/heater-character`. Base: `origin/max/integrate-r001-e001@9723771`.
- **Commits:**
  - `93566c0`: switch to pose images (see `2026-11-07-2150-heater-poses.md`).
  - `23cf537`: demo page, real poses, personality file, plain-English Ref.
  - The commit that adds this report.
- **Pushed:** this push includes all of the above.
- **Check log:** `logs/2026-11-07-2300-heater-demo-checks.log` (LF). Run at `23cf537` with a clean worktree.

## Inputs

**`heater-poses.zip`** holds 7 JPEGs with WhatsApp file names. All are 687x1024.
- I extracted them into a new empty scratch folder.
- I matched each to a state by what it shows:

| File | State | What it shows |
|---|---|---|
| (1) | listening | hand to his ear |
| (2) | thinking | spinning the ball |
| (3) | hot_take | shouting, reaching out |
| (4) | heat_check | glitched outline |
| (5) | vindicated | jumping with the ball |
| (6) | cooled | slumped |
| no number | idle | dribbling |

- I converted them to WebP (quality 0.9) with the installed Edge, using `canvas.toDataURL`. No package was installed and nothing was downloaded.

**`heater_personality.json`** is a byte copy at `apps/web/web/heater/heater_personality.json`. The user wrote `apps/web/heater/`; the server serves `apps/web/web/`.

## Demo page: `/demo.html`

| Requirement | Where |
|---|---|
| Full-viewport #12121A stage, soft orange spotlight, faint court lines | `demo.css`, plus an inline SVG court in `demo.html` |
| Heater large on the left, full body, no box | The pose is about 730 px tall at 1440x900. The light is `.h-spot` inside his figure, and the pose blends into it with `lighten`, so the image's dark background takes the light. A first try lit the stage behind him instead, and his image area showed as a darker box; this was fixed and checked on the phone screenshot |
| Comic speech bubble (orange border, condensed, 28 px) | `.bubble` |
| Ref card (teal, calm, smaller) | `.ref` |
| Verdict stamp slams on with scale and shake, in the verdict colour, as Heater changes pose | `.stamp` with keyframes `slam`. It is set in the same tick as `setState(endState)` |
| Stamp text | From `verdict_stamps` in the personality file. BLOCKED shows **"NO RULING"**: that is what the file says, and the message listed "BLOCKED" |
| Wide input "Ask Heater anything about the NBA…", mic button, three chips | `.ask`. The mic uses the existing `voice.js`: browser speech where available, otherwise `/api/transcribe` |
| Ref in plain English, numbers second, all from the record | `refPlain()`. For HH-K2: "The data says no. Making two in a row didn't make the next shot more likely (p = 0.24, 181 shots, one game)." The p-value is the record's `p_value` 0.239, rounded |
| Technical detail collapsed | "Show the evidence": claim statement, verdict and raw reason, effect, p-value, permutations, data, each attack with status and reason, receipt (evidence id), plan hash, data hash, hash status, limits |
| Nothing debug-like by default; drawer with `?debug=1` | The drawer holds: claim id, registry text, phase, pose, evidence id, ledger source, hash status, line source, API URL, record picker, voice toggle, log |
| Display titles | `CLAIM_TITLES`, for example HH-K2 "Hot hand: two makes in a row" |
| Heater's lines from the personality file when the API is unavailable | `takeFor`/`reactFor`. The API's `heater_text` is used when Max's server answers |

**How the three chips resolve offline** (fixture ledger):

| Chip | Claim | Ref result | Stamp | End pose |
|---|---|---|---|---|
| Is the hot hand real? | HH-K2 | NOT_SUPPORTED | NOT SUPPORTED | cooled |
| Do home teams win more? | CONF-HA | No record exists: "No ruling yet…" | grey NOT TESTED YET | thinking stand-in |
| Does rest matter? | GP-REST | BLOCKED: "No ruling. This test needs season-long game results, and those aren't loaded yet." | NO RULING | listening stand-in |

No verdict is invented for CONF-HA.

**Other changes:**
- `app.py`: the CSP's `connect-src` now also allows `http://127.0.0.1:8770` and `http://localhost:8770`, so the page can call the dialogue API. Before, it was `'self'` only.
- `heater.css`: colour filters moved onto the pose images, so they no longer tint the spotlight. The cooled brightness is now 0.88 (was 0.72), so the cooled pose stays readable. It is still desaturated.

## Checks

| Check | Command | Result |
|---|---|---|
| ruff | `uv run ruff check apps/web` | PASS |
| node tests | `cd apps\web && node --test tests/heater.test.mjs tests/referee.test.mjs` | PASS: 30/30, 0 TODO. The pose TODO is gone; all 7 poses are 687x1024 WebP |
| apps/web unittest | `cd apps\web && uv run python -m unittest discover -s tests -q` | PASS: 80 OK |
| Screenshots | `cd apps\web && uv run --group browser python tools/heater_screens.py` (run before the commit, so the PNGs are in it) | PASS: 16 written, `unexpected_errors: []`. Expected errors: the 404 probe of `/api/evidence`, and the refused connection to `:8770` when the API is down |
| Full exchange in the in-app browser, HH-K2, voices off | | PASS: the poses ran listening → thinking → hot_take → heat_check → thinking → cooled; stamp NOT SUPPORTED; react line "The data is WRONG. I watched the games!" |
| Default view has no debug text | Browser `innerText`, plus a test on `demo.html` | PASS: only the brand, the hint, the input, Ask and the 3 chips. The screen-reader-only label "Your question" is also in `innerText` |
| `?debug=1` drawer | Browser | PASS: the drawer exists, with 3 records in the picker |
| With Max's dialogue API running | | **NOT_RUN**. The server was not started here. The fallback path is what was exercised |
| Voices and mic in a real session | | **NOT_RUN** in headless capture; speech was off for the screenshots |

## Screenshots (`apps/web/evidence/heater/`)

- `demo-hot-hand.png`: 1440x900, a full question-to-verdict exchange.
- `demo-home.png`, `demo-rest.png`: the other two example chips.
- `demo-hot-hand-phone.png`: 390 px wide.
- `state-*.png`, `card-*.png`: the dev state sheet.
