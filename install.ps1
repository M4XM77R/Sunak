# Sunak installer for Windows 10/11.
#
#   irm https://raw.githubusercontent.com/M4XM77R/sunak/main/install.ps1 | iex
#
# Set $env:SUNAK_YES = "1" before running for an unattended install,
# $env:SUNAK_AUTOSTART = "1" to start Sunak at every login, $env:SUNAK_NO_SHORTCUT = "1" for no icons,
# $env:SUNAK_DESKTOP = "1" to also install the optional desktop app (otherwise you are asked, default no).
$ErrorActionPreference = "Stop"
$Repo = if ($env:SUNAK_REPO) { $env:SUNAK_REPO } else { "M4XM77R/sunak" }
$Branch = if ($env:SUNAK_BRANCH) { $env:SUNAK_BRANCH } else { "main" }
$HomeDir = Join-Path $env:LOCALAPPDATA "sunak"
$AppDir = Join-Path $HomeDir "app"

function Say($m) { Write-Host "$([char]0x26F5) $m" -ForegroundColor Magenta }
function Ask($q) {
  if ($env:SUNAK_YES -eq "1") { return $true }
  $a = Read-Host "$q [Y/n]"
  return -not ($a -match '^[nN]')
}
function Find-Python {
  foreach ($c in @("py -3", "python", "python3")) {
    $parts = $c.Split(" ")
    $rest = @()
    if ($parts.Length -gt 1) { $rest = $parts[1..($parts.Length - 1)] }
    try {
      $out = & $parts[0] @rest -c "import sys; print(sys.version_info >= (3, 9))" 2>$null
      if ("$out".Trim() -eq "True") { return $c }
    } catch { }
  }
  return $null
}

Write-Host "`n  Sunak - your private AI workspace`n" -ForegroundColor Magenta

# 1. Python
$py = Find-Python
if (-not $py) {
  if (Ask "Python 3.9+ is needed. Install Python 3.12 with winget?") {
    winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" + [Environment]::GetEnvironmentVariable("Path", "Machine")
    $py = Find-Python
  }
  if (-not $py) { throw "Python not found. Install it from https://python.org (tick 'Add to PATH') and run this again." }
}
Say "Python: OK"

# 2. App
New-Item -ItemType Directory -Force -Path $HomeDir | Out-Null
$local = if ($PSScriptRoot -and (Test-Path (Join-Path $PSScriptRoot "sunak\server.py"))) { $PSScriptRoot } else { $null }
$tmp = "$AppDir.new"
if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
if ($local) {
  Say "Installing from $local"
  New-Item -ItemType Directory -Force -Path $tmp | Out-Null
  Copy-Item -Recurse -Path (Join-Path $local "*") -Destination $tmp -Exclude ".git", "data"
  # remember the clone, so "sunak update" can pull it (also works for private repositories)
  if (Test-Path (Join-Path $local ".git")) { Set-Content -Encoding UTF8 (Join-Path $HomeDir "source.txt") $local }
  else { Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $HomeDir "source.txt") }
  # installed commit, for the "Update available" check in the app
  try { $c = git -C $local rev-parse HEAD 2>$null; if ($LASTEXITCODE -eq 0 -and $c) { Set-Content -Encoding ASCII (Join-Path $tmp ".commit") $c } } catch {}
} else {
  Say "Downloading Sunak..."
  Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $HomeDir "source.txt")  # no clone to update from
  $zip = Join-Path $env:TEMP "sunak.zip"
  try { Invoke-WebRequest -UseBasicParsing "https://codeload.github.com/$Repo/zip/refs/heads/$Branch" -OutFile $zip }
  catch { throw "Download failed. If the repository is private, clone it and run .\install.ps1 inside it." }
  $ex = Join-Path $env:TEMP "sunak-x"
  if (Test-Path $ex) { Remove-Item -Recurse -Force $ex }
  Expand-Archive $zip -DestinationPath $ex
  Move-Item (Get-ChildItem $ex | Select-Object -First 1).FullName $tmp
  Remove-Item -Recurse -Force $ex, $zip
}
if (Test-Path $AppDir) { Remove-Item -Recurse -Force $AppDir }
Move-Item $tmp $AppDir
Say "App installed in ${AppDir}: OK"

# 3. Launcher + shortcuts
$pyCmd = $py
$cmd = Join-Path $HomeDir "sunak.cmd"
@"
@echo off
rem Sunak launcher: sunak, sunak stop, sunak status, sunak version, sunak gpu, sunak shortcut, sunak autostart on/off, sunak update, sunak uninstall (all: sunak -h)
rem paths relative to this file (%~dp0), so user names with umlauts survive the ASCII file
set "PYTHONPATH=%~dp0app;%PYTHONPATH%"
rem uninstall deletes this file: the block is read in one go and "exit /b" ends it before cmd reads further
if /I "%~1"=="uninstall" (
  $pyCmd -m sunak %*
  exit /b
)
if /I "%~1"=="update" if /I "%~2"=="-h" set "SUNAK_HELP=1"
if /I "%~1"=="update" if /I "%~2"=="--help" set "SUNAK_HELP=1"
if defined SUNAK_HELP (
  set "SUNAK_HELP="
  $pyCmd -m sunak help update
  exit /b
)
set "SUNAK_ASK=--confirm"
if /I "%~1"=="update" if /I "%~2"=="-y" set "SUNAK_ASK=--confirm --yes"
if /I "%~1"=="update" if /I "%~2"=="--yes" set "SUNAK_ASK=--confirm --yes"
if /I "%~1"=="update" (
  $pyCmd -m sunak changelog %SUNAK_ASK%
  if errorlevel 3 exit /b 0
  $pyCmd -m sunak stop >nul 2>&1
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0update.ps1"
  $pyCmd -m sunak desktop update --auto
  echo Updated. Start Sunak again with the desktop icon or: sunak
  exit /b
)
$pyCmd -m sunak %*
"@ | Set-Content -Encoding ASCII $cmd

# update.ps1: pull the remembered clone and reinstall from it, else download the latest installer
@'
$ErrorActionPreference = "Stop"
$env:SUNAK_YES = "1"; $env:SUNAK_NO_START = "1"; $env:SUNAK_NO_SHORTCUT = "1"; $env:SUNAK_NO_OLLAMA = "1"
$src = Get-Content (Join-Path $PSScriptRoot "source.txt") -ErrorAction SilentlyContinue | Select-Object -First 1
if ($src -and (Test-Path (Join-Path $src ".git"))) {
  Write-Host "Updating from $src"
  $ErrorActionPreference = "Continue"  # PowerShell 5.1 would treat git's progress on stderr as an error
  git -C $src pull --ff-only 2>&1 | Out-Host
  $ErrorActionPreference = "Stop"
  if ($LASTEXITCODE -ne 0) { throw "git pull failed in $src" }
  & (Join-Path $src "install.ps1")
} else {
  try { $script = Invoke-RestMethod "https://raw.githubusercontent.com/REPO/BRANCH/install.ps1" }
  catch { throw "Download failed. For a private repository: git pull in your clone, then run .\install.ps1 there." }
  Invoke-Expression $script
}
'@.Replace("REPO", $Repo).Replace("BRANCH", $Branch) | Set-Content -Encoding UTF8 (Join-Path $HomeDir "update.ps1")

$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if (-not ($userPath -split ";" | Where-Object { $_ -eq $HomeDir })) {
  [Environment]::SetEnvironmentVariable("Path", "$userPath;$HomeDir", "User")
}
Say "Command sunak installed: OK"

# Desktop + Start Menu icons start Sunak without a console window (or open it when it already runs).
# Run from the app folder so the icons point at the installed copy.
Push-Location $AppDir
if ($env:SUNAK_NO_SHORTCUT -ne "1") {
  & $cmd shortcut | Out-Null
  Say "Icons on Desktop and Start Menu: OK"
}
if ($env:SUNAK_AUTOSTART -eq "1" -or ($env:SUNAK_YES -ne "1" -and (Read-Host "Start Sunak automatically in the background when you log in? [y/N]") -match '^[yY]')) {
  & $cmd autostart on | Out-Null
  Say "Autostart: OK (turn off with: sunak autostart off)"
}
Pop-Location

# 4. Ollama
# Ollama uses a GPU on its own (CUDA for NVIDIA, ROCm for AMD); its installer brings what the GPU needs.
Push-Location $AppDir
try { & $cmd gpu | ForEach-Object { Say $_ } } catch { }
Pop-Location
if ($env:SUNAK_NO_OLLAMA -ne "1" -and -not (Get-Command ollama -ErrorAction SilentlyContinue)) {
  if (Ask "Install Ollama to run AI models on this computer? (recommended)") {
    try { winget install -e --id Ollama.Ollama --accept-package-agreements --accept-source-agreements }
    catch { Write-Warning "Ollama install failed - get it from https://ollama.com/download" }
  }
}

# 5. Desktop app (optional, opt-in): "sunak desktop install" downloads the finished package from the newest
# GitHub release "desktop-v*" (no Rust). A failure is only a hint; the normal installation is complete.
if ($env:SUNAK_DESKTOP -eq "1" -or ($env:SUNAK_YES -ne "1" -and (Read-Host "Also install the desktop app (Sunak in its own window)? [y/N]") -match '^[yY]')) {
  Push-Location $AppDir
  & $cmd desktop install
  if ($LASTEXITCODE -ne 0) { Write-Warning "Desktop app not installed. Sunak itself is ready; try later: sunak desktop install" }
  Pop-Location
} else {
  # an installed app is renewed when a newer desktop release exists (nothing happens if it is not installed)
  Push-Location $AppDir
  try { & $cmd desktop update --auto } catch { }
  Pop-Location
}

Write-Host "`n  Done! Start Sunak with the desktop icon or by typing: sunak`n" -ForegroundColor Magenta
if ($env:SUNAK_NO_START -ne "1") { & $cmd }
