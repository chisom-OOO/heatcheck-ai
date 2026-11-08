# MARKET_COMPARISON live and recorded, 8 November 2026 (00:17Z to 00:27Z)

Forecast: Research's real `data/live/forecasts.json` (research/live-forecast@e03629d, 14 games, cutoff
2026-11-07T07:00Z, validator PASS). Quotes: read-only Polymarket/Kalshi captures 20261108T001759Z and
20261108T001942Z. Polymarket mappings VERIFIED 16/16 against stored rules text; Kalshi PROPOSED.
No LLM (`--no-llm`), headless Chromium via Playwright, Windows 11.

## Live (before tip; CLE and OKC tip 01:00Z)
- `investigate_live_0022600191.json`: CLE 0.662 vs Polymarket bid 0.36 / ask 0.37, quote 13 s old.
  Worth investigating · Edge unverified (ledger 0bbb970d).
- `investigate_live_0022600192.json`: OKC 0.936 vs bid 0.82 / ask 0.83. Worth investigating · Edge
  unverified (ledger 0655d3fe).
- `live_board.png`, `live_card_CLE.png`, `live_ask_CLE.png`: demo.cmd (live mode), capture taken
  immediately before the screenshot (board at +11 s). DEN at IND says Can't compare (already started).

## Recorded (`serve_dialogue --recorded`, 00:26Z)
- `investigate_recorded_0022600192.json`: OKC evaluated as of its capture 00:19:45Z. Worth
  investigating · Edge unverified; Ref text ends "RECORDED: price received 2026-11-08T00:19:45Z, not
  live." (ledger 8439aecc).
- `recorded_board.png`, `recorded_card_OKC.png`, `recorded_ask_OKC.png`: demo.cmd --recorded-market.
  The card shows a RECORDED badge and "Price received ... (RECORDED, not live)"; the Ref line ends with
  the RECORDED sentence (user request, 00:23Z). Before this change RECORDED was only under "Show the
  evidence".

## Idea board (Experience 6ad128e, Research a84bd64)
- `idea_board.png`, `idea_card.png`, `idea_ask.png`, `idea_evidence.png`: 12 development ideas, 4
  worth a proper test. Ask on "Elo favourite by 100+": Ref "Worth a proper test ... p = 0.012 after
  allowing for the 12 ideas ... A lead, not a finding". Requests: GET /api/ideas, /api/evidence only.
  Browser console empty. No stamp was visible in the screenshot.

## Observation, not a finding
On 12 of the 13 games that could be compared, the model's home-team probability sits above the market
ask (one below the bid). A gap that one-sided across a slate looks more like a model bias (stale Elo from
132 early-season games, a home-court term, no injury or lineup data) than 12 separate edges. Nothing here
shows the model beats the market.

## Checks on this commit's tree
pytest 597 passed, 0 failed, 29 skipped, 16 xfailed; ruff clean; apps/web node 46/46; apps/web unittest
103 OK. Fixed in this commit: test pinned verification count at 7 (now 35 real records, each still
checked).
