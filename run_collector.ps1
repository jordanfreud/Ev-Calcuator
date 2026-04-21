$ErrorActionPreference = "Stop"

$repo = "C:\Users\jorda\ev-betting-tool"
$python = "C:\Users\jorda\ev-betting-tool\venv\Scripts\python.exe"

Push-Location $repo
try {
    & $python collect_line_history.py --interval-seconds 3600 --iterations 1
}
finally {
    Pop-Location
}
