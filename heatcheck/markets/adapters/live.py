"""Read-only live HTTP client for public venue market data (ported from the Experience build).

Only HTTPS ``GET`` to an allowlisted host and exact path pattern. No redirects, no cookies, no
credentials, no private or loopback addresses, and a response size cap. There is no
route that writes to a venue. Nothing in this repository calls it automatically: a live
capture needs the user's explicit authorisation on the machine that runs it (E-001).
"""

from __future__ import annotations

import ipaddress
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime

from heatcheck.markets.adapters.common import AdapterError

MAX_RESPONSE = 2 * 1024 * 1024
# One identifier path segment: letters, digits, '-' and '_' only. No '.', '..', '%' or '/',
# so neither a dot segment nor an encoded slash can reach another endpoint (RV-E1).
_SEG = r"[A-Za-z0-9][A-Za-z0-9_-]{0,199}"
# Whole-path patterns, matched exactly (no prefix matching): each is one public read.
ALLOW: dict[str, tuple[re.Pattern[str], ...]] = {
    "gamma-api.polymarket.com": tuple(
        re.compile(p) for p in (rf"/markets/slug/{_SEG}", r"/markets", r"/events")
    ),
    "clob.polymarket.com": (re.compile(r"/book"),),
    "api.elections.kalshi.com": tuple(
        re.compile(p)
        for p in (
            rf"/trade-api/v2/markets(/{_SEG}(/orderbook)?)?",
            rf"/trade-api/v2/events(/{_SEG})?",
        )
    ),
}


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def check_request(method: str, url: str) -> str:
    """Return the host if (method, url) is an allowed public read; raise otherwise."""
    if method != "GET":
        raise AdapterError(f"method {method!r} refused: this client is read-only (GET only)")
    u = urllib.parse.urlsplit(url)
    if u.scheme != "https":
        raise AdapterError(f"scheme {u.scheme!r} refused: https only")
    if u.username or u.password or u.port not in (None, 443):
        raise AdapterError("credentials or a non-standard port in the URL are refused")
    host = (u.hostname or "").lower()
    if host not in ALLOW:
        raise AdapterError(f"host {host!r} is not on the read-only allowlist")
    if not any(p.fullmatch(u.path) for p in ALLOW[host]):
        raise AdapterError(f"path {u.path!r} is not an allowlisted public read endpoint")
    return host


def _assert_public(host: str) -> None:
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise AdapterError(f"DNS failure for {host}: {exc}") from None
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise AdapterError(f"{host} resolved to non-public address {ip}")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        raise AdapterError(f"redirect to {newurl!r} refused (HTTP {code})")


class ReadOnlyClient:
    """``request`` returns (http_status, body_bytes, fetch_start_utc, received_utc)."""

    def __init__(self, timeout: float = 8.0):
        self.timeout = timeout
        self._opener = urllib.request.build_opener(_NoRedirect)

    def request(self, method: str, url: str) -> tuple[int, bytes, str, str]:
        host = check_request(method, url)
        _assert_public(host)
        req = urllib.request.Request(
            url,
            method="GET",
            headers={"Accept": "application/json", "User-Agent": "heatcheck-experience read-only"},
        )
        start = utc_now()
        try:
            with self._opener.open(req, timeout=self.timeout) as resp:
                body = resp.read(MAX_RESPONSE + 1)
                status = resp.status
        except urllib.error.HTTPError as exc:
            status, body = exc.code, b""
        except (urllib.error.URLError, OSError) as exc:
            raise AdapterError(f"network error: {getattr(exc, 'reason', exc)}") from None
        received = utc_now()
        if len(body) > MAX_RESPONSE:
            raise AdapterError(f"response over {MAX_RESPONSE} bytes refused")
        return status, body, start, received

    def get(self, url: str) -> tuple[int, bytes, str, str]:
        return self.request("GET", url)
