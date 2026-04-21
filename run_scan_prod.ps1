$ErrorActionPreference = "Stop"

$repo = "C:\Users\jorda\ev-betting-tool"
$python = "C:\Users\jorda\ev-betting-tool\venv\Scripts\python.exe"
$logDir = Join-Path $repo "automation_logs"
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir | Out-Null
}

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logFile = Join-Path $logDir "scan_$stamp.log"

Push-Location $repo
try {
    & $python main.py --prod-profile --diagnostics --show-rejections --explain *> $logFile
}
finally {
    Pop-Location
}
