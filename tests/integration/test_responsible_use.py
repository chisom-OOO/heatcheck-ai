"""Safer-gambling wording and guards (Max, 8 Nov 2026). No numbers or verdicts change here.

- apps/web/web/responsible_use.json is the one source of the wording; README.md and
  docs/SUBMISSION.md carry the full text verbatim.
- Every Heater line, model-written or template, is checked for betting-encouragement wording.
- No page file or served market data links to Polymarket's or Kalshi's trading pages.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from heatcheck.agents import dialogue as D
from heatcheck.agents import market_investigation as M
from heatcheck.agents import scenario as S
from heatcheck.agents.dialogue import betting_words

ROOT = Path(__file__).resolve().parents[2]
RU = ROOT / "apps" / "web" / "web" / "responsible_use.json"

SHORT = ("Statistics demo, not betting advice. Prices shown read-only; no orders. 18+. Gambling problems? "
         "National Gambling Helpline 0808 8020 133 (free, 24/7).")
FULL = ("Responsible use. HeatCheck is a statistics demo. It is not a betting or trading service, not financial "
        "advice, and not a recommendation to bet or trade. Market prices are shown read-only, for comparison only; "
        "HeatCheck never places orders, takes money or links to betting or trading. Nothing shows this model beats "
        "the market: a gap between the forecast and the price is a question to look into, not an edge. The "
        "HeatCheck team accepts no responsibility for any decision anyone makes using it; use at your own risk. "
        "Betting and prediction-market trading are for adults only (18+, or 21+ where the law requires), and only "
        "where they are legal. If gambling stops being fun, the National Gambling Helpline (GamCare) is free, "
        "confidential and open 24/7: 0808 8020 133, gamcare.org.uk (checked 8 November 2026).")


# ------------------------------------------------------------------ one source, docs verbatim

def test_responsible_use_file_is_the_agreed_text():
    doc = json.loads(RU.read_text(encoding="utf-8"))
    assert doc == {"short": SHORT, "full": FULL}


@pytest.mark.parametrize("path", ["README.md", "docs/SUBMISSION.md"])
def test_docs_carry_the_full_text_verbatim_with_the_read_only_line(path):
    text = (ROOT / path).read_text(encoding="utf-8")
    full = json.loads(RU.read_text(encoding="utf-8"))["full"]
    assert full in text
    section = text[text.index("Responsible use\n"):]
    assert "no order path" in section and "Kalshi quotes stay unverified" in section


# ------------------------------------------------------------------ Heater betting guard

BANNED = ["bet", "bets", "betting", "wager", "value bet", "free money", "guaranteed", "sure thing",
          "can't lose", "cannot lose", "a lock", "lock it in", "mortal lock"]


@pytest.mark.parametrize("phrase", BANNED)
def test_each_betting_phrase_is_caught_in_any_case(phrase):
    for text in (phrase, phrase.upper(), phrase.title(), f"Honestly, {phrase}!"):
        assert betting_words(text), text


@pytest.mark.parametrize("text", ["better", "between", "lockdown", "The Lakers look better tonight",
                                  "locked in the vault", "a locker room", "alphabet", "lockout"])
def test_ordinary_words_pass(text):
    assert betting_words(text) == []


def _all_strings(x):
    if isinstance(x, str):
        yield x
    elif isinstance(x, dict):
        for v in x.values():
            yield from _all_strings(v)
    elif isinstance(x, list):
        for v in x:
            yield from _all_strings(v)


def _server_heater_templates() -> list[str]:
    games = json.loads((ROOT / "data" / "live" / "forecasts.json").read_text(encoding="utf-8"))["games"]
    row = games[0]
    lines = [D.HEATER_TAKE_FALLBACK, *D.HEATER_REACTION.values(), *M.HEATER_REACTION.values(),
             M.HOME_BIAS_HEATER, M.SAMPLE_HEATER, M.HYPOTHETICAL_ANSWER.format(inputs="Elo rating (home)"),
             S.board_intro(14), S.board_intro(1), S.card_intro(row), S.card_intro(row, "2099-01-01T00:00:00Z")]
    for msg in ("What if Boston played on a neutral floor?", "Assume it costs Boston 5%", "gibberish change"):
        r = S.route(msg, games, "2026-11-08T00:40:00Z")
        g = next((x for x in games if x["game_id"] == r["game_id"]), row)
        lines.append(S.parse_scenario(msg, g, "f" * 64)["heater_text"])
    return lines


def test_every_server_heater_template_and_fallback_is_clean():
    lines = _server_heater_templates()
    assert len(lines) >= 20
    assert [(t, betting_words(t)) for t in lines if betting_words(t)] == []


def test_heater_personality_file_is_clean():
    doc = json.loads((ROOT / "apps" / "web" / "web" / "heater" / "heater_personality.json").read_text(encoding="utf-8"))
    lines = list(_all_strings(doc))
    assert lines and [(t, betting_words(t)) for t in lines if betting_words(t)] == []


# Market templates for every flag, run through investigate(): tests/integration/test_market_investigation.py


def test_market_guard_rejects_betting_wording():
    for phrase in ("value bet", "a lock", "can't lose", "free money", "lock it in"):
        problems = M.heater_guard(f"Indiana is {phrase} tonight?", [], {})
        assert any("betting" in p for p in problems), phrase
    assert not any("betting" in p for p in M.heater_guard("Indiana look better between games?", [], {}))


# ------------------------------------------------------------------ no outbound trading links

TRADING_LINK = re.compile(r"https?://(?:www\.)?(?:polymarket|kalshi)\.com", re.IGNORECASE)


def test_no_page_file_links_to_a_trading_page():
    web = ROOT / "apps" / "web" / "web"
    hits = [str(p.relative_to(ROOT)) for p in web.rglob("*")
            if p.is_file() and p.suffix in (".html", ".js", ".mjs", ".json", ".css")
            and TRADING_LINK.search(p.read_text(encoding="utf-8", errors="ignore"))]
    assert hits == []


def test_no_server_code_or_served_market_data_links_to_a_trading_page():
    files = [*(ROOT / "heatcheck").rglob("*.py"), *(ROOT / "apps" / "web" / "server").rglob("*.py"),
             *(ROOT / "data" / "experience" / "quotes").rglob("board.mappings.json")]
    hits = [str(p.relative_to(ROOT)) for p in files if TRADING_LINK.search(p.read_text(encoding="utf-8", errors="ignore"))]
    assert hits == []
