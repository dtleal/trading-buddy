@echo off
REM ----------------------------------------------------------------------
REM  Unattended launcher for the MT5 order-flow collector.
REM  Auto-started by watchdog.ps1 via the "MT5OrderflowCollector" scheduled
REM  task. Unlike start_collector.bat there is NO `pause`: when python exits
REM  (MT5 closed / fatal error) the window closes cleanly and the watchdog
REM  relaunches within a minute. Use start_collector.bat for manual/debug runs.
REM  `pushd "%~dp0"` maps the \\wsl.localhost UNC dir to a temp drive so the
REM  relative config path resolves (plain UNC as CWD is unsupported by cmd).
REM ----------------------------------------------------------------------
pushd "%~dp0"
"C:\Users\diego\AppData\Local\Programs\Python\Python312\python.exe" mt5_orderflow_collector.py --config config.json
popd
