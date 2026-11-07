#!/usr/bin/env bash
# Runs every check and logs actual output to evidence/test_run.log. Usage: bash tools/run_checks.sh
set -u
cd "$(dirname "$0")/.."
LOG=evidence/test_run.log
PORT=${PORT:-8765}
{
  echo "# HeatCheck-Experience check run"
  echo "date_utc: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "host: $(uname -srm)"
  echo "python: $(python3 --version 2>&1) numpy: $(python3 -c 'import numpy;print(numpy.__version__)') scipy: $(python3 -c 'import scipy;print(scipy.__version__)')"
  echo "node: $(node --version 2>&1)  chrome: $(/usr/bin/google-chrome --version 2>&1)"
  echo
  echo "## python -m unittest discover -s tests -v"
  python3 -m unittest discover -s tests -v 2>&1
  echo "exit: $?"
  echo
  pkill -f "server.app --port $PORT" 2>/dev/null; sleep 0.5
  HEATCHECK_QUIET=1 python3 -m server.app --port "$PORT" > /tmp/hc_server.log 2>&1 &
  SRV=$!
  sleep 1.5
  echo "## node tests/e2e_browser.mjs"
  node tests/e2e_browser.mjs "http://127.0.0.1:$PORT" 2>&1
  echo "exit: $?"
  echo
  echo "## node tests/e2e_extension.mjs"
  node tests/e2e_extension.mjs "http://127.0.0.1:$PORT" 2>&1
  echo "exit: $?"
  kill $SRV 2>/dev/null
} | tee "$LOG"
