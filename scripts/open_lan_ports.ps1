# Opens the Windows firewall for trading-buddy LAN access (frontend :3000,
# backend :8000). Must run elevated (it touches the firewall).
#
#   Right-click > Run with PowerShell (as admin), or:
#   Start-Process powershell -Verb RunAs -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File','<this path>'
#
# The rule is scoped to RemoteAddress=LocalSubnet, so even though the active
# network is classified "Public" the ports are only reachable from devices on
# the same local network — never the open internet. Idempotent: re-running
# replaces the rule.
$ErrorActionPreference = 'Stop'
$name = 'trading-buddy LAN (3000/8000)'

Remove-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue

New-NetFirewallRule -DisplayName $name -Direction Inbound -Action Allow `
    -Protocol TCP -LocalPort 3000,8000 -Profile Any -RemoteAddress LocalSubnet | Out-Null
Write-Host "Host firewall rule added: $name"

# WSL mirrored networking is filtered by a separate Hyper-V firewall. Allow the
# same inbound ports there too, scoped to the local subnet. Older builds don't
# have these cmdlets — ignore if absent (the host rule alone is then enough).
try {
    $vm = '{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}'  # WSL's Hyper-V firewall VMCreatorId
    New-NetFirewallHyperVRule -Name 'trading-buddy-lan' -DisplayName $name `
        -Direction Inbound -Action Allow -Protocol TCP -LocalPorts '3000,8000' `
        -VMCreatorId $vm -RemoteAddresses LocalSubnet -ErrorAction Stop | Out-Null
    Write-Host "Hyper-V (WSL mirrored) firewall rule added."
} catch {
    Write-Host "Hyper-V firewall rule skipped ($($_.Exception.Message))."
}

Write-Host "Done. Access the dashboard from another LAN device at http://192.168.15.5:3000"
