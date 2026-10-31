# Lets CyberScan X restart the PrimeFilm 1800 AFL's USB device without unplugging it.
#
# Run once from an administrator PowerShell:
#   powershell -ExecutionPolicy Bypass -File scripts\install-scanner-reset.ps1
# Remove with:
#   Unregister-ScheduledTask -TaskName 'Reset PF1800 AFL' -TaskPath '\FRAME\' -Confirm:$false
#
# It registers one scheduled task, owned by you and run with your administrator rights
# only when started. The task restarts USB devices with ID 2770:0119 (this scanner) and
# nothing else. It has no trigger; CyberScan X starts it with "schtasks /Run" when a scan
# stalls at "Preparing film scanner", the same as turning the scanner off and on.
#Requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'

$command = @'
Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -like 'USB\VID_2770&PID_0119\*' } |
  ForEach-Object { pnputil.exe /restart-device $_.InstanceId | Out-Null }
'@
$encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($command))
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -WindowStyle Hidden -EncodedCommand $encoded"
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 2) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName 'Reset PF1800 AFL' -TaskPath '\FRAME\' -Action $action -Principal $principal `
  -Settings $settings -Description 'Restarts the PrimeFilm 1800 AFL (USB 2770:0119) for CyberScan X.' -Force | Out-Null
Write-Host 'Installed \FRAME\Reset PF1800 AFL. CyberScan X can now recover a stalled scanner by itself.'
