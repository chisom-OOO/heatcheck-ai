# demo.cmd end to end, 7 November 2026 (~23:35Z)

Code: max/integrate-r001-e001 after merging experience/market-board@8f89df7 (a3997d5), plus the
SAMPLE Heater fix in the same commit as this folder. Windows 11, headless Chromium (Playwright),
no LLM (`--no-llm`: Heater and Ref templates), no live venue requests.

Run 1, the real configuration: `demo.cmd --fresh-ledger --no-browser --no-llm`
- chip1.png: "Is the hot hand real?" -> HH-K3, Ref "Can't tell yet" (14 after three makes,
  18 after three misses; 30 of each needed).
- chip2.png: "Do home teams win more?" -> CONF-HA SURVIVED_PROTOCOL (54.5%, 1,224 games 2024-25, Holm p 0.005).
- chip3.png: "Does rest matter?" -> GP-REST INSUFFICIENT_EVIDENCE.
- board_no_forecast.png: "Tonight's games" says "No live forecast: forecasts.json not found."
  Research's data/live/forecasts.json does not exist yet (waits for the cdn.nba.com schedule).

Run 2, market card on SAMPLE input: `demo.cmd --no-browser --no-llm --recorded-market
--live-forecast tests/fixtures/live/forecasts.SAMPLE.json`
- board.png: six cards, every one labelled SAMPLE, real recorded Polymarket bid/ask (22:29Z
  capture), difference withheld, verdict Can't compare.
- market_card_ask.png: "Ask Heater about this game" on BKN at ATL. Heater: SAMPLE, no numbers.
  Ref: "Can't compare: the forecast is a SAMPLE with made-up numbers."

Defect found in run 2 and repaired: Heater's template voiced the SAMPLE value ("The model has
Atlanta Hawks at 50.0% to win"). Root cause: investigate() built the Heater line without checking
is_sample. Repair: fixed SAMPLE line, no LLM call; regression test in
tests/integration/test_market_investigation.py::test_sample_forecast_cannot_compare. The
screenshots above are from the rerun after the repair.

All page requests were same-origin: GET /api/evidence, GET /api/live-forecast,
GET /api/market-mappings, POST /api/investigate on 127.0.0.1:8765. Browser console: no messages.
Not shown: a "Worth investigating" card (needs Research's real forecast), the SAMPLE stamp
(Experience's report mentions one; none was visible after the Ref line in this run).
