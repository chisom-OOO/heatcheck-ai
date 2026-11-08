@echo off
rem Fresh read-only venue quotes for tonight's games + Max's mapping verification. Then: demo.cmd --recorded-market
rem Options: --forecast PATH  --no-verify
cd /d "%~dp0"
uv run --frozen python tools\capture_quotes.py %*
