$ErrorActionPreference = "Stop"

$repo = "C:\Users\jorda\ev-betting-tool"
$python = "C:\Users\jorda\ev-betting-tool\venv\Scripts\python.exe"
$date = Get-Date -Format "yyyy-MM-dd"

Push-Location $repo
try {
    Write-Host "=== EV Health Check ===" -ForegroundColor Cyan
    Write-Host "Date: $date"

    $modelOut = & $python model_predictions_parser.py --show --date $date 2>&1 | Out-String
    $modelCount = 0
    if ($modelOut -match "Total:\s*(\d+)\s*games") {
        $modelCount = [int]$Matches[1]
    }

    $lineHistoryPath = Join-Path $repo "line_history.json"
    $lineFreshMins = $null
    if (Test-Path $lineHistoryPath) {
        $json = Get-Content $lineHistoryPath -Raw | ConvertFrom-Json
        $latest = $null
        foreach ($event in $json.PSObject.Properties.Value) {
            foreach ($bookHistory in $event.PSObject.Properties.Value) {
                foreach ($row in $bookHistory) {
                    $ts = [datetime]$row.timestamp
                    if ($null -eq $latest -or $ts -gt $latest) {
                        $latest = $ts
                    }
                }
            }
        }
        if ($latest) {
            $lineFreshMins = [math]::Round(((Get-Date).ToUniversalTime() - $latest.ToUniversalTime()).TotalMinutes, 1)
        }
    }

    $collectorTask = schtasks /Query /TN EVCollectorHourly /FO LIST 2>$null | Out-String
    $scan1Task = schtasks /Query /TN EVScan1100 /FO LIST 2>$null | Out-String
    $scan2Task = schtasks /Query /TN EVScan1700 /FO LIST 2>$null | Out-String

    $status = "GREEN"
    if ($modelCount -lt 1) { $status = "RED" }
    elseif ($lineFreshMins -ne $null -and $lineFreshMins -gt 120) { $status = "YELLOW" }

    Write-Host "Status: $status"
    Write-Host "Model rows today: $modelCount"
    if ($lineFreshMins -ne $null) {
        Write-Host "Line history freshness (minutes): $lineFreshMins"
    } else {
        Write-Host "Line history freshness (minutes): n/a"
    }

    Write-Host ""
    Write-Host "Tasks:"
    if ($collectorTask -match "Next Run Time:\s*(.+)") {
        Write-Host "- EVCollectorHourly next run: $($Matches[1])"
    } else {
        Write-Host "- EVCollectorHourly: missing"
    }
    if ($scan1Task -match "Next Run Time:\s*(.+)") {
        Write-Host "- EVScan1100 next run: $($Matches[1])"
    } else {
        Write-Host "- EVScan1100: missing"
    }
    if ($scan2Task -match "Next Run Time:\s*(.+)") {
        Write-Host "- EVScan1700 next run: $($Matches[1])"
    } else {
        Write-Host "- EVScan1700: missing"
    }

    Write-Host ""
    Write-Host "Strict readiness check:"
    if ($modelCount -lt 1) {
        Write-Host "- BLOCKED: no same-day model rows" -ForegroundColor Red
    } else {
        Write-Host "- OK: same-day model rows available" -ForegroundColor Green
    }
}
finally {
    Pop-Location
}
