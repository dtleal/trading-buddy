# Registers (or refreshes) the "MT5OrderflowCollector" scheduled task that
# keeps the MT5 order-flow collector alive. Run once, from Windows:
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File <path>\install_watchdog_task.ps1
#
# The task fires watchdog.ps1 every minute in the interactive user session
# (so it can see MT5 and the \\wsl.localhost share). -MultipleInstances
# IgnoreNew means a slow run never stacks up. Re-running this script is safe;
# -Force replaces the existing task.
$ErrorActionPreference = 'Stop'

$watchdog = '\\wsl.localhost\Ubuntu-22.04\home\diego\trading-buddy\collector\watchdog.ps1'
$taskName = 'MT5OrderflowCollector'

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
    -Description 'Keeps the MT5 order-flow collector running (self-heals after reboot/close/crash).' `
    -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null

Write-Host "Scheduled task '$taskName' registered (runs watchdog.ps1 every minute)."
