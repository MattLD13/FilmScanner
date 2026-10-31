# Adds FRAME to the Start menu and desktop, opening the scanner workspace.
#
#   powershell -ExecutionPolicy Bypass -File scripts\install-cyberscan-shortcut.ps1
#
# Per-user only: two .lnk files, no administrator rights. Delete them to remove.
# The shortcut starts this checkout's Electron shell with --frame-scanner; the shell starts
# the local FRAME service itself. Run "npm run setup" and "npm run build" first.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$electron = Join-Path $root 'apps\desktop-shell\node_modules\electron\dist\electron.exe'
$shell = Join-Path $root 'apps\desktop-shell'
$icon = Join-Path $root 'apps\desktop-shell\assets\frame.ico'
if (-not (Test-Path $electron)) { throw "Electron is not installed. Run npm run setup in $root first." }
if (-not (Test-Path (Join-Path $root 'apps\web\dist\index.html'))) { throw "The client is not built. Run npm run build in $root first." }

$wsh = New-Object -ComObject WScript.Shell
$places = @([Environment]::GetFolderPath('Programs'), [Environment]::GetFolderPath('Desktop'))
foreach ($folder in $places) {
  $link = $wsh.CreateShortcut((Join-Path $folder 'FRAME.lnk'))
  $link.TargetPath = $electron
  $link.Arguments = "`"$shell`" --frame-scanner"
  $link.WorkingDirectory = $root
  $link.IconLocation = "$icon,0"
  $link.Description = 'FRAME film scanning and darkroom workspace'
  $link.Save()
  Write-Host "Created $($link.FullName)"
  # Retire only this checkout's previous branded shortcut. Leave unrelated or
  # customised shortcuts untouched, including links to other installations.
  $legacyPath = Join-Path $folder 'CyberScan X.lnk'
  if (Test-Path -LiteralPath $legacyPath) {
    $legacyLink = $wsh.CreateShortcut($legacyPath)
    if ($legacyLink.TargetPath -eq $electron -and $legacyLink.WorkingDirectory -eq $root -and
        $legacyLink.Arguments -eq "`"$shell`" --cyberscan") {
      Remove-Item -LiteralPath $legacyPath
      Write-Host "Replaced the previous CyberScan X shortcut with FRAME."
    }
  }
}
