# Heater

HeatCheck's animated pundit.

- **Demo page:** `/demo.html` (`apps/web/web/demo.html`). It is built for a judge watching for 10 seconds:
  - Heater on the left;
  - his take in a speech bubble;
  - the Ref's plain-English ruling;
  - a verdict stamp that lands as Heater changes pose;
  - one input with a mic button and three example chips.
  - The internals (claim ids, registry text, phases, record picker, voice toggle, hash status) are in a drawer opened with `?debug=1`. `?voice=0` mutes speech, and `?ask=…` asks on load.
- **State sheet (dev page):** `/heater/states.html` shows every state in its own cell and the full sequence on a real evidence record.

## Art

**The character art is AI-generated (Google Gemini).** The pose images are 687x1024 WebP, one per pose, in `poses/`:

| Pose file | Used for state(s) |
|---|---|
| `idle.webp` | idle |
| `listening.webp` | listening; blocked (stand-in) |
| `thinking.webp` | thinking; unsure (stand-in) |
| `hot_take.webp` | hot_take |
| `heat_check.webp` | heat_check |
| `vindicated.webp` | vindicated |
| `cooled.webp` | cooled |

The single pose map is `POSE_FOR_STATE` in `heater-model.js`. When unsure and blocked get their own images, change those two entries.

A missing image is labelled on the stage (`pose image missing: poses/<name>.webp`). It is never silently replaced by another pose.

## Motion

All motion is CSS on top of the image (`heater.css`):

| State | Motion |
|---|---|
| Any change | Pose crossfade (200 ms) |
| idle | Slow bob |
| hot_take | Squash-bounce on each `speechSynthesis` word boundary; ±3 px shake on CAPS words |
| heat_check | 0.6 s slice-glitch with teal and violet fringes, plus the Ref's scanline |
| vindicated | Scale-pop and a screen-blended glow |
| cooled | Slow sink and desaturate |
| All states | Sparks rise from the head; fewer when cooled, none when blocked |

`prefers-reduced-motion: reduce` keeps the crossfades and colour changes. It stops every animation and hides the sparks and the glitch.

## Lines

**The Ref.** The verdict and every number come from the evidence record. `refPlain()` in `heater-model.js` writes the plain words first and the numbers second. It fills the `ref_templates` from the record's own fields:
- the permutation p-value, rounded to two decimals;
- `n_attempts` and `n_games`;
- the sample-size counts;
- `min_n_each_side`.

The raw reason, the attacks, the effect, the receipt and the hashes are under "Show the evidence".

**Heater.** The line comes from the dialogue API's `heater_text` when Max's server answers on `127.0.0.1:8770`. Otherwise it comes from `heater/heater_personality.json`:
- `claims` gives the take;
- `react` gives his reaction after the verdict;
- `verdict_stamps` gives the stamp text.

**Offline routing.** With the API down, a question is routed to a claim by keywords (`routeQuestion`). The page then shows the newest ledger entry for that claim. A claim with no entry gets "No ruling yet" and a grey "NOT TESTED YET" stamp, never an invented verdict.

## Tests

From `apps/web`, run `node --test tests/heater.test.mjs`. To regenerate the screenshots, run `uv run --group browser python tools/heater_screens.py`; this writes `evidence/heater/*.png`.
