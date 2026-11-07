@echo off
rem HeatCheck demo: dialogue API (http://127.0.0.1:8770/) + Experience UI (http://127.0.0.1:8765/).
rem Needs uv (https://docs.astral.sh/uv/). Options: --no-llm --no-browser --setup-only --fresh-ledger
cd /d "%~dp0"
uv run --frozen --group research python tools\demo.py %*
