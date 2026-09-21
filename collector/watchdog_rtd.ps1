# Watchdog for the Profit RTD B3 tape collector (Players tab).
#
# Runs every minute via the "ProfitRtdCollector" scheduled task. If the
# collector python process is not alive, (re)launch it. Idempotent: does
# nothing when it's already running, so it's safe to fire on a tight schedule.
#
# It only launches when ProfitChart is already open, for the same reason the
# collector checks it too: the RTD CLSID is registered against profitchart.exe,
# so touching COM with Profit closed would START Profit. The watchdog must
# never do that on its own.
#
# This is independent of the MT5 collector watchdog — the Players tab works
# with the MT5 collector switched off.
$ErrorActionPreference = 'SilentlyContinue'

$profit = Get-Process profitchart -ErrorAction SilentlyContinue
if (-not $profit) { return }

$running = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
    Where-Object { $_.CommandLine -like '*profit_rtd_collector*' }

if (-not $running) {
    $bat = '\\wsl.localhost\Ubuntu-22.04\home\diego\trading-buddy\collector\run_rtd_supervised.bat'
    Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', $bat -WindowStyle Minimized
}
