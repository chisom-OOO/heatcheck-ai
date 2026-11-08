# Safer-gambling wording and guards (Max, 8 Nov 2026, 05:14 UTC)

No numbers, forecasts, quotes or verdicts change. This is not legal advice: the user and the adviser
review the final wording before the demo.

**Why.** HeatCheck reads Polymarket's public prices read-only: no orders, no account, no money and no
trading links. Polymarket is still a place where people put money on outcomes, so the market side
is treated as close to gambling and says so plainly.

## 1. The text (one source)

`apps/web/web/responsible_use.json`:

- **short:** "Statistics demo, not betting advice. Prices shown read-only; no orders. 18+. Gambling
  problems? National Gambling Helpline 0808 8020 133 (free, 24/7)."
- **full:** "Responsible use. HeatCheck is a statistics demo. It is not a betting or trading service,
  not financial advice, and not a recommendation to bet or trade. Market prices are shown
  read-only, for comparison only; HeatCheck never places orders, takes money or links to betting or
  trading. Nothing shows this model beats the market: a gap between the forecast and the price is a
  question to look into, not an edge. The HeatCheck team accepts no responsibility for any decision
  anyone makes using it; use at your own risk. Betting and prediction-market trading are for adults
  only (18+, or 21+ where the law requires), and only where they are legal. If gambling stops being
  fun, the National Gambling Helpline (GamCare) is free, confidential and open 24/7: 0808 8020 133,
  gamcare.org.uk (checked 8 November 2026)."

## 2. Where it appears

| Place | Text | By |
|---|---|---|
| `apps/web/web/responsible_use.json` | short + full | Max (this change) |
| `README.md`, section "Responsible use" | full, verbatim, plus a read-only line | Max |
| `docs/SUBMISSION.md`, section "11. Responsible use" | full, verbatim, plus a read-only line | Max |
| Page footer (`demo.html` `#ru-footer`, fixed, every view) | short; static HTML so it shows even if scripts fail; a test checks it equals the JSON | **Max edited Experience's page file** (update, 06:15 UTC) |
| "Tonight's games" board header (`market/board.js`, `.board-ru`) | full, under "Descriptive only, never a betting tip." | **Max** |
| Market Ask, once per session (`demo.js` `askMarket`, `#ru-notice` in `demo.html`) | full, the first time a market card is asked about (sessionStorage; once per page if storage is blocked) | **Max** |

The read-only line in both docs: "Read-only by design: HeatCheck holds no venue keys or accounts and
has no order path; the independent gate review's order-capability scan (`place_order`, `/orders`,
POST in market code) found none (`reports/review/2026-11-08-0310-gate-review.md`). Kalshi quotes
stay unverified (only Polymarket mappings are verified)."

**Update 06:15 UTC.** The first version left the page to Experience, following the earlier task text.
The fuller task says either side may edit the page, as long as the report says so. Max edited
`demo.html`, `demo.css`, `demo.js` and `market/board.js`, and added `responsible.js`. Experience:
please don't change these hunks at the same time; merge from `max/integrate-r001-e001`. The footer
is small and muted, and the notices use muted text with a thin left border, not an ad style.
Screenshots of the home and board views at 1440×900 were checked; the footer no longer overlaps
the chips. The first-Ask notice was checked by unit test only, not seen in a browser: tonight's
recorded board had no priced card in the first screen.

## 3. Helpline check

- **User/adviser:** verified the helpline on gamcare.org.uk on 8 November 2026, as instructed and
  recorded here.
- **Max's own check, 8 Nov ~05:10 UTC:**
  - Fetching gamcare.org.uk returned HTTP 403 to the agent's fetcher, so Max did not see GamCare's
    own page.
  - GambleAware's service listing for "GamCare National Gambling Helpline" states: "The free
    National Gambling Helpline is also available 24/7 on 0808 8020 133."
  - URL: https://www.gambleaware.org/tools-and-support/support-in-your-area/service-finder-results/gamcare-national-gambling-helpline/

## 4. Polymarket terms (read 8 Nov 2026; effective 11 August 2026)

**Finding: the terms neither clearly allow nor clearly forbid showing its public prices in a public
demo. Several clauses are relevant. Decision for the user and adviser.**

Sources: https://polymarket.com/tos and https://docs.polymarket.com/api-reference/geoblock.
docs.polymarket.com states no separate API licence, rate-limit terms or display terms.

**Clauses that bear on us** (quoted from the fetched page; quotes were split by the fetch tool):

- **§4.2, Data:** you may not "Access or use any data, content, or information contained on our
  Site, any Interface or Features directly or through an API … (the "Data") if you are (i) a
  non-retail, professional entity that engages in capital markets activities … (each, a "Capital
  Market Client"), or (ii) a market data distributor … unless otherwise agreed to in writing".
  - HeatCheck is not a Capital Market Client.
  - Whether a public demo that shows prices counts as a "market data distributor" is undefined in
    the terms.
- **§4.2, automated collection:** you may not "Use any data mining tools, robots, crawlers, or
  similar data gathering and extraction tools to scrape or otherwise remove data from the Site, any
  other Interface, or Features".
  - `capture_quotes.cmd` reads the public Gamma/CLOB read endpoints automatically, a few dozen
    requests per capture.
  - Whether calling the published public API is "scraping … Features" is not stated.
- **§5.1, licence:** a "personal, limited, revocable, non-exclusive, non-sublicensable,
  non-transferable license to use, copy, and distribute in connection with such use the Site, any
  other Interface, and Features".
- **§4.1, jurisdictions:** "you are not permitted to access, use or trade with the Contracts on the
  Platform if you are residing in … or located in any jurisdiction identified as a restricted
  jurisdiction" on the geoblock list.
  - **The United Kingdom (GB) is listed** as "Regulatory-Restricted (Close-Only on Frontend and
    API)".
  - The team and the helpline are UK-based. Whether reading public prices (not trading) is "access,
    use … the Contracts" is a legal question this report does not answer.
- **§4.1, age:** "intended only for users who are 18 years of age or older". The short and full
  text say 18+.

**Options for the user and adviser** (none taken by Max):
- keep the market board as is, with the disclaimer;
- show only recorded prices with attribution in the demo, and not deploy publicly;
- ask Polymarket in writing (an outside message: the user's decision);
- drop the market board from any public deployment.

Kalshi's terms were not read; Kalshi quotes stay unverified.

## 5. Event rules

The event's rules on betting or prediction-market content are **not yet known**: gate G18 is
NOT_RUN (`ACCEPTANCE.json`). Nothing here claims compliance with them.

## 6. Heater guard

`heatcheck/agents/dialogue.py` `BETTING_WORDS` / `betting_words()`:
- Whole words or phrases, case-insensitive: bet, bets, betting, wager, "value bet", "free money",
  guaranteed, "sure thing", "can't lose", "cannot lose", and lock only as "a lock", "lock it in" or
  "mortal lock".
- Used for the dialogue Heater's model line, where a match falls back to the template, and in
  `market_investigation.heater_guard`, where a match rejects the model line and keeps the template.
- The market guard's older, broader list (e.g. "lock", "value", "edge") is unchanged.
- The Ref's text is not covered; "not a betting signal" stays.

**Open item for Experience:** `apps/web/web/heater/heater-model.js` `PLACEHOLDER_LINES` contain
"Bet the rested team, every time!" (GP-REST) and "This one is a LOCK!" ("*"). They are used only if
`heater_personality.json` fails to load. The demo's personality file is clean (tested). The check
is recorded as a node `todo` test until Experience rewords those lines.

## 7. Outbound links

No page file (`apps/web/web/**`), server code (`heatcheck/**`, `apps/web/server/**`) or served
board mapping (`data/experience/quotes/**/board.mappings.json`) contains a link to
`polymarket.com` or `kalshi.com`. The pattern matches the trading-page hosts, not API hosts like
`gamma-api.polymarket.com`.

## 8. Tests added

- **`tests/integration/test_responsible_use.py`:**
  - the JSON equals the agreed text;
  - README and SUBMISSION contain the full text verbatim, plus the read-only line;
  - every banned phrase is caught in any case;
  - "better", "between", "lockdown", "locked in the vault", "locker room", "alphabet" and "lockout"
    pass;
  - every server Heater template and fallback is clean: dialogue take/reactions, market
    reactions/home-bias/sample/hypothetical, board/card intros, scenario read-backs;
  - the personality file is clean;
  - the market guard rejects betting wording;
  - no trading links in pages, server code or served mappings.
- **`tests/integration/test_market_investigation.py`:** templates and reactions are clean for above
  ask, below bid, inside spread, after tip, sample and hypothetical; a model line with "a lock",
  "value bet", "can't lose" or "lock it in" falls back to the template.
- **`tests/integration/test_dialogue.py`:** a model take with betting wording falls back to the
  template; "better … between … LOCKDOWN" is kept.
- **`apps/web/tests/responsible.test.mjs`:** the footer equals the JSON short text and sits
  outside every view; the CSS keeps it fixed; the JSON loader returns null on any failure; the Ask
  notice shows once per session and once per page when storage is blocked.
- **`apps/web/tests/board.test.mjs`** (one test added): the board header shows the full text next
  to "never a betting tip", and nothing when the text didn't load.
- **`apps/web/tests/safer_gambling.test.mjs`:** the same word list in JS; the personality file is
  clean; responsible_use.json has short and full; the PLACEHOLDER_LINES `todo` described above.
