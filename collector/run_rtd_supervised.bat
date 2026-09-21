@echo off
REM ----------------------------------------------------------------------
REM  Unattended launcher for the Profit RTD B3 tape collector.
REM  Auto-started by watchdog_rtd.ps1 via the "ProfitRtdCollector" scheduled
REM  task. No `pause`: when python exits (Profit closed, no Times & Trades
REM  window linked, fatal error) the window closes and the watchdog relaunches
REM  within a minute.
REM  `pushd "%~dp0"` maps the \\wsl.localhost UNC dir to a temp drive so the
REM  relative config path resolves (plain UNC as CWD is unsupported by cmd).
REM ----------------------------------------------------------------------
pushd "%~dp0"
"C:\Users\diego\AppData\Local\Programs\Python\Python312\python.exe" profit_rtd_collector.py --config config.json
popd
