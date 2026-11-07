"""E-001 A5: the adapters are read-only. No module calls an order, cancel, sign, withdraw
or deposit route, and the live client refuses non-GET methods and off-allowlist URLs
before any network access."""

from __future__ import annotations

import ast
import re

import pytest
from conftest import ROOT

from heatcheck.markets.adapters.common import AdapterError
from heatcheck.markets.adapters.live import ALLOW, ReadOnlyClient, check_request

ADAPTERS = sorted((ROOT / "heatcheck" / "markets" / "adapters").glob("*.py"))
FORBIDDEN = {"order", "orders", "cancel", "sign", "withdraw", "deposit", "transfer", "wallet"}
WRITE_ROUTE = re.compile(r"/(orders?|portfolio|cancel|withdraw|deposit|transfers?)(/|\?|$)")
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def call_name(node: ast.Call) -> str:
    f = node.func
    return f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")


@pytest.mark.parametrize("path", ADAPTERS, ids=lambda p: p.name)
def test_a5_no_write_calls_routes_or_methods(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            tokens = set(call_name(node).lower().split("_"))
            assert not tokens & FORBIDDEN, f"{path.name}:{node.lineno} calls {call_name(node)}"
            for kw in node.keywords:
                if kw.arg == "method":
                    assert isinstance(kw.value, ast.Constant) and kw.value.value == "GET"
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert not WRITE_ROUTE.search(node.value), f"{path.name}:{node.lineno} write route"
            assert node.value not in WRITE_METHODS, f"{path.name}:{node.lineno} write method"


def test_allowlist_has_only_public_read_paths():
    for prefixes in ALLOW.values():
        for p in prefixes:
            assert not WRITE_ROUTE.search(p)


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "get"])
def test_a5_live_client_refuses_non_get(method, no_network):
    with pytest.raises(AdapterError, match="read-only"):
        ReadOnlyClient().request(method, "https://clob.polymarket.com/book?token_id=1")


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/markets",
        "https://clob.polymarket.com/order",
        "https://api.elections.kalshi.com/trade-api/v2/portfolio/orders",
        "http://clob.polymarket.com/book?token_id=1",
        "https://user:pw@clob.polymarket.com/book?token_id=1",
        "https://clob.polymarket.com:8443/book?token_id=1",
    ],
)
def test_a5_live_client_refuses_off_allowlist_url(url, no_network):
    with pytest.raises(AdapterError):
        ReadOnlyClient().get(url)


def test_allowed_read_passes_the_check_without_network(no_network):
    assert check_request("GET", "https://clob.polymarket.com/book?token_id=1") == (
        "clob.polymarket.com"
    )
