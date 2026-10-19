# Runs the unmodified prototype engine's 12 acceptance tests (SiloEngine.selfTests) in headless Microsoft Edge
# and prints the results. Exit code 0 only when every test passes.
# Usage:  powershell -NoProfile -ExecutionPolicy Bypass -File tools\run_prototype_selftests.ps1
$ErrorActionPreference = 'Stop'
$project = Split-Path $PSScriptRoot -Parent
$page = Join-Path $project 'reference\prototype_js\run_selftests.html'
$edge = @("${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe", "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe") |
  Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $edge) { Write-Output 'Microsoft Edge not found.'; exit 2 }
$profileDir = Join-Path $env:TEMP 'silo-selftest-edge-profile'
$url = 'file:///' + ($page -replace '\\', '/')
# Edge writes diagnostic lines to stderr; under 'Stop' Windows PowerShell 5.1 would treat them as failures.
$ErrorActionPreference = 'Continue'
$dom = & $edge --headless=new --disable-gpu --no-first-run --user-data-dir="$profileDir" --virtual-time-budget=60000 --dump-dom $url 2>$null | Out-String
$ErrorActionPreference = 'Stop'
$m = [regex]::Match($dom, '<pre id="a">(.*?)</pre>', 'Singleline')
if (-not $m.Success) { Write-Output 'Could not read test output from the page.'; exit 2 }
$text = [System.Net.WebUtility]::HtmlDecode($m.Groups[1].Value)
Write-Output $text
$hash = (Get-FileHash (Join-Path $project 'reference\prototype_js\silo_engine_v0.2.0.js') -Algorithm SHA256).Hash.ToLower()
Write-Output "engine file sha256: $hash"
if ($text -match '(\d+)/(\d+) passed' -and $Matches[1] -eq $Matches[2]) { exit 0 } else { exit 1 }
