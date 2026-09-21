# Registers (or refreshes) the "ProfitRtdCollector" scheduled task that keeps
# the Profit RTD B3 tape collector alive. Run once, from Windows:
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File <path>\install_rtd_watchdog_task.ps1
#
# The task fires watchdog_rtd.ps1 every minute in the interactive user session
# (so it can see Profit and the \\wsl.localhost share). -MultipleInstances
# IgnoreNew means a slow run never stacks up. Re-running this script is safe;
# -Force replaces the existing task.
$ErrorActionPreference = 'Stop'

$watchdog = '\\wsl.localhost\Ubuntu-22.04\home\diego\trading-buddy\collector\watchdog_rtd.ps1'
$taskName = 'ProfitRtdCollector'

$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$watchdog`""

# One trigger that starts now and repeats every minute, indefinitely. After a
# reboot the schedule resumes once the user logs back on, so the collector is
# restored within ~1 minute without an explicit logon trigger.
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 1)

$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName $taskName `
    -Description 'Keeps the Profit RTD B3 tape collector running (Players tab).' `
    -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null

Write-Host "Scheduled task '$taskName' registered (runs watchdog_rtd.ps1 every minute)."
