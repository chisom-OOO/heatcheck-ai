# Sunday board before the demo (Max, 8 Nov 2026, 10:03–10:15 UTC)

- **Merges and fixes:**
  - `experience/frost@0055f45` merged unchanged as `d23dace` (every file identical).
  - Board fix `5955bbd` (user): `GET /api/live-forecast` for the board returns only games whose
    `tip_utc` is after now, plus `earlier {count, games}`. The forecast file is unchanged and still
    validated whole. Routing and scenarios still read every game.
  - The page shows earlier games as one collapsed row, labelled "Earlier: N games, tipped off"
    rather than "final", because a game that tipped recently may still be on.
  - `demo.py` prints the counts at start.
- **Quotes and restart:** `capture_quotes.cmd` at 10:05:43 UTC: 7/7 Polymarket bundles VERIFIED, no
  key in 116 files. Then `demo.cmd --recorded-market --fresh-ledger`, model on:
  `[demo] board: 7 games still to tip; 7 earlier (tipped off) hidden as one row`.
- **Browser check** (`board_check.py`, Edge 1440x900 headless): 7 cards plus the row "Earlier: 7 games,
  tipped off". No page errors.

| Game (tip UTC) | Polymarket bid / ask (RECORDED 10:05) | Verdict |
|---|---|---|
| 76ers at Bulls (20:30) | 0.21 / 0.22 | Worth investigating · Edge unverified |
| Lakers at Pistons (23:00) | 0.62 / 0.63 | Worth investigating · Edge unverified |
| Jazz at Timberwolves (00:00) | 0.83 / 0.84 | Worth investigating · Edge unverified |
| Nets at Mavericks (00:30) | 0.77 / 0.78 | Worth investigating · Edge unverified |
| Celtics at Bucks (01:00) | 0.13 / 0.14 | Worth investigating · Edge unverified |
| Pelicans at Clippers (02:00) | 0.47 / 0.48 | Worth investigating · Edge unverified |
| Heat at Kings (02:00) | 0.23 / 0.24 | Worth investigating · Edge unverified |

- **Ref box** (76ers at Bulls card): badge THE REF; title "EDGE UNVERIFIED — Philadelphia 76ers at
  Chicago Bulls · forecast vs. market"; "Show the evidence" dropdown. Opened, it lists the verdict,
  RECORDED data, compared-as-of time, and GAME_MATCH, OUTCOME_MATCH, QUOTE_FRESH, QUOTE_SIDE,
  FORECAST_CUTOFF and MISSING_INPUTS (`board-card-ref-evidence.png`).
- **Recorded, not live:** prices are RECORDED, as of each capture. LIVE mode refuses quotes older than
  60 s, so a capture would read "Can't compare" a minute later.
- **Recapture:** scheduled for 10:45 UTC (`capture_quotes.cmd`). The server re-reads quotes per request
  and uses the newest capture, so the demo needs no restart.
