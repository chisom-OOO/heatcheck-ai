# Heater

HeatCheck's animated pundit. Open `states.html` on the web app (`/heater/states.html`) to see:
- every state in its own cell;
- the full per-question sequence on a real evidence record.

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

The Ref's verdict and every number come from the evidence record.

Heater's line is a hot take:
- It comes from `web/heater_personality.json`, served at `/heater_personality.json`.
- Until that file is added, the line comes from the labelled placeholder lines in `heater-model.js`.
- Later, it will come from Max's dialogue endpoint.

Accepted file shapes:
- `{"HH-K2": ["…"], "default": ["…"]}`;
- the same table under `"lines"`;
- the same table under `"claims"`.

## Tests

From `apps/web`, run `node --test tests/heater.test.mjs`. To regenerate the screenshots, run `uv run --group browser python tools/heater_screens.py`; this writes `evidence/heater/*.png`.
