"""Screenshot every Heater state and the speech card for each committed ledger record.

Starts the app server on a local port, drives the installed Microsoft Edge headless through
Playwright (no browser download), and writes PNGs to apps/web/evidence/heater/.

    uv run --group browser python apps/web/tools/heater_screens.py [--channel msedge]

Each state is captured at a fixed time after it starts, so one-shot states show their
characteristic frame (e.g. heat_check during the glitch).
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

APP = Path(__file__).resolve().parents[1]
OUT = APP / "evidence" / "heater"
# state -> milliseconds after mount to capture
STATES = {
    "idle": 900, "listening": 900, "thinking": 900, "hot_take": 700, "heat_check": 70,
    "vindicated": 450, "cooled": 2000, "unsure": 900, "blocked": 900,
}
CLAIMS = ["HH-K3", "HH-K2", "GP-REST"]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_up(url: str, timeout: float = 20.0) -> None:
    end = time.time() + timeout
    while time.time() < end:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    return
        except OSError:
            time.sleep(0.2)
    raise SystemExit(f"server did not start: {url}")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", default="msedge")
    args = ap.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    port = free_port()
    env = {**os.environ, "HEATCHECK_QUIET": "1"}
    srv = subprocess.Popen([sys.executable, "-m", "server.app", "--port", str(port)], cwd=APP, env=env)
    written = []
    try:
        base = f"http://127.0.0.1:{port}"
        wait_up(f"{base}/heater/states.html")
        with sync_playwright() as p:
            browser = p.chromium.launch(channel=args.channel, headless=True)
            page = browser.new_page(viewport={"width": 520, "height": 620}, device_scale_factor=2)
            errors: list[str] = []
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            for state, ms in STATES.items():
                # the glitch lasts 210 ms; hold its second frame so the capture shows it
                freeze = "&freeze=1" if state == "heat_check" else ""
                page.goto(f"{base}/heater/states.html?shot={state}{freeze}")
                page.wait_for_selector("body[data-ready='1']")
                page.wait_for_timeout(ms)
                path = OUT / f"state-{state}.png"
                page.locator("#shot").screenshot(path=str(path))
                written.append(path)
            for claim in CLAIMS:
                page.goto(f"{base}/heater/states.html?shot=card&claim={claim}")
                page.wait_for_selector("body[data-ready='1']")
                page.wait_for_timeout(900)
                path = OUT / f"card-{claim}.png"
                page.locator("#shot").screenshot(path=str(path))
                written.append(path)
            browser.close()
    finally:
        srv.terminate()
        srv.wait(timeout=10)
    # The only expected console error is the 404 from probing /api/evidence on a server
    # started without a ledger; anything else is reported.
    unexpected = [e for e in errors if "404" not in e]
    print(json.dumps({"written": [str(p.relative_to(APP)) for p in written],
                      "console_errors": errors, "unexpected_errors": unexpected}, indent=2))
    return 1 if unexpected else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
