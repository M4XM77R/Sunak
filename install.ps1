# Sunak installer for Windows 10/11.
#
#   irm https://raw.githubusercontent.com/M4XM77R/sunak/main/install.ps1 | iex
#
# Set $env:SUNAK_YES = "1" before running for an unattended install.
$ErrorActionPreference = "Stop"
$Repo = if ($env:SUNAK_REPO) { $env:SUNAK_REPO } else { "M4XM77R/sunak" }
$Branch = if ($env:SUNAK_BRANCH) { $env:SUNAK_BRANCH } else { "main" }
$HomeDir = Join-Path $env:LOCALAPPDATA "sunak"
$AppDir = Join-Path $HomeDir "app"

function Say($m) { Write-Host "⛵ $m" -ForegroundColor Magenta }
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

Write-Host "`n  Sunak – your private AI workspace`n" -ForegroundColor Magenta

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
Say "Python ✓"

# 2. App
New-Item -ItemType Directory -Force -Path $HomeDir | Out-Null
$local = if ($PSScriptRoot -and (Test-Path (Join-Path $PSScriptRoot "sunak\server.py"))) { $PSScriptRoot } else { $null }
$tmp = "$AppDir.new"
if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
if ($local) {
  Say "Installing from $local"
  New-Item -ItemType Directory -Force -Path $tmp | Out-Null
  Copy-Item -Recurse -Path (Join-Path $local "*") -Destination $tmp -Exclude ".git", "data"
} else {
  Say "Downloading Sunak…"
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
Say "App installed in $AppDir ✓"

# 3. Launcher + shortcuts
$pyCmd = $py
$cmd = Join-Path $HomeDir "sunak.cmd"
@"
@echo off
if /I "%~1"=="update" (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "`$env:SUNAK_YES='1'; `$env:SUNAK_NO_START='1'; irm https://raw.githubusercontent.com/$Repo/$Branch/install.ps1 | iex"
  exit /b
)
set "PYTHONPATH=$AppDir;%PYTHONPATH%"
$pyCmd -m sunak %*
"@ | Set-Content -Encoding ASCII $cmd

$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if (-not ($userPath -split ";" | Where-Object { $_ -eq $HomeDir })) {
  [Environment]::SetEnvironmentVariable("Path", "$userPath;$HomeDir", "User")
}
$ws = New-Object -ComObject WScript.Shell
foreach ($dir in @([Environment]::GetFolderPath("Desktop"), (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"))) {
  $lnk = $ws.CreateShortcut((Join-Path $dir "Sunak.lnk"))
  $lnk.TargetPath = $cmd
  $lnk.WorkingDirectory = $HomeDir
  $lnk.Save()
}
Say "Shortcuts on Desktop and Start Menu ✓"

# 4. Ollama
if ($env:SUNAK_NO_OLLAMA -ne "1" -and -not (Get-Command ollama -ErrorAction SilentlyContinue)) {
  if (Ask "Install Ollama to run AI models on this computer? (recommended)") {
    try { winget install -e --id Ollama.Ollama --accept-package-agreements --accept-source-agreements }
    catch { Write-Warning "Ollama install failed – get it from https://ollama.com/download" }
  }
}

Write-Host "`n  Done! Start Sunak with the desktop icon or by typing: sunak`n" -ForegroundColor Magenta
if ($env:SUNAK_NO_START -ne "1") { & $cmd }
