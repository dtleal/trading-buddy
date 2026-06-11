# Watchdog for the MT5 order-flow collector.
#
# Runs every minute via the "MT5OrderflowCollector" scheduled task. If the
# collector python process is not alive, (re)launch it. Idempotent: does
# nothing when it's already running, so it's safe to fire on a tight schedule.
#
# This is what makes the flow self-healing: after a reboot, after the window
# is closed, or after a crash, the collector is back within ~1 minute without
# anyone touching it. MT5 must still be open and logged in for it to read data;
# if MT5 is down the collector exits and the watchdog keeps retrying until it's
# up again.
$ErrorActionPreference = 'SilentlyContinue'

$running = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
    Where-Object { $_.CommandLine -like '*mt5_orderflow_collector*' }

if (-not $running) {
    $bat = '\\wsl.localhost\Ubuntu-22.04\home\diego\trading-buddy\collector\run_supervised.bat'
    Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', $bat -WindowStyle Minimized
}
