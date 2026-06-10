@echo off
REM ----------------------------------------------------------------------
REM  Start the MT5 order-flow collector (MT5 -> backend on Docker/WSL).
REM  Prerequisites:
REM    1. MetaTrader 5 OPEN and LOGGED IN to the broker that has the data.
REM    2. Deps installed: python -m pip install -r requirements.txt
REM    3. config.json present (copy from config.example.json).
REM  Keep this window OPEN while you want live flow on the dashboard.
REM  See README.md -> Troubleshooting if it exits or the dashboard stays empty.
REM ----------------------------------------------------------------------
pushd "%~dp0"
echo Starting MT5 -> backend order-flow collector ...
python mt5_orderflow_collector.py --config config.json
echo.
echo Collector stopped. Read the message above (e.g. MT5 closed / not logged in).
pause
popd
