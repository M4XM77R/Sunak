# Remove Sunak from Windows 10/11. Your chats, settings and keys are kept unless you say otherwise.
#
#   irm https://raw.githubusercontent.com/M4XM77R/sunak/main/uninstall.ps1 | iex
#
# Set $env:SUNAK_YES = "1" for no questions (removes the program, keeps your data),
# $env:SUNAK_PURGE = "1" to also delete your data. The same as "sunak uninstall".
$ErrorActionPreference = "Stop"
$Repo = if ($env:SUNAK_REPO) { $env:SUNAK_REPO } else { "M4XM77R/sunak" }
$Branch = if ($env:SUNAK_BRANCH) { $env:SUNAK_BRANCH } else { "main" }
$HomeDir = Join-Path $env:LOCALAPPDATA "sunak"

function Find-Python {
  foreach ($c in @("py -3", "python", "python3")) {
    $parts = $c.Split(" ")
    $rest = @()
    if ($parts.Length -gt 1) { $rest = $parts[1..($parts.Length - 1)] }
    try {
      $out = & $parts[0] @rest -c "import sys; print(sys.version_info >= (3, 9))" 2>$null
      if ("$out".Trim() -eq "True") { return ,$parts }
    } catch { }
  }
  return $null
}
function Has-Uninstaller($dir) { return $dir -and (Test-Path (Join-Path $dir "sunak\uninstall.py")) }

$py = Find-Python
if (-not $py) { Write-Host "Python is not installed, so Sunak cannot be either. Delete $HomeDir if it exists."; return }

# The uninstaller is part of Sunak: use this clone, else the installed app, else download it.
$src = $null
$tmp = $null
if (Has-Uninstaller $PSScriptRoot) { $src = $PSScriptRoot }
elseif (Has-Uninstaller (Join-Path $HomeDir "app")) { $src = Join-Path $HomeDir "app" }
else {
  $tmp = Join-Path $env:TEMP "sunak-uninstall"
  if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
  $zip = "$tmp.zip"
  try {
    Invoke-WebRequest -UseBasicParsing "https://codeload.github.com/$Repo/zip/refs/heads/$Branch" -OutFile $zip
    Expand-Archive $zip -DestinationPath $tmp
    $src = (Get-ChildItem $tmp | Select-Object -First 1).FullName
  } catch {
    Write-Host "Could not download the uninstaller. Remove Sunak by hand: delete $HomeDir and the Sunak icons."
    Write-Host "Your data is in $(Join-Path $HOME '.sunak')."
    return
  } finally { Remove-Item -Force -ErrorAction SilentlyContinue $zip }
}

$flags = @()
if ($env:SUNAK_YES -eq "1") { $flags += "--yes" }
if ($env:SUNAK_PURGE -eq "1") { $flags += "--purge" }
$rest = @()
if ($py.Length -gt 1) { $rest = $py[1..($py.Length - 1)] }
Set-Location $HOME
$env:PYTHONPATH = $src
& $py[0] @rest -m sunak uninstall @flags
if ($tmp) { Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $tmp }
