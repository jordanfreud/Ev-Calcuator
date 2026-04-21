$ErrorActionPreference = "Stop"

$repo = "C:\Users\jorda\ev-betting-tool"
$scanScript = Join-Path $repo "run_scan_prod.ps1"
$collectorScript = Join-Path $repo "run_collector.ps1"
$botScript = Join-Path $repo "run_discord_bot.ps1"

$scanCmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$scanScript`""
$collectorCmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$collectorScript`""
$botCmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$botScript`""

# Remove legacy task names if present without failing the script.
$legacyTasks = @(
	"EVCollector",
	"EVCollectorDay",
	"EVScan0930",
	"EVScan1200",
	"EVScan1530",
	"EVScan1830",
	"EVCollectorHourly",
	"EVCollector0800",
	"EVCollector1200",
	"EVCollector1700",
	"EVDiscordBot",
	"EVScan1100",
	"EVScan1700"
)

$prevErrorPreference = $ErrorActionPreference
$ErrorActionPreference = "SilentlyContinue"
foreach ($taskName in $legacyTasks) {
	schtasks /Query /TN $taskName /FO LIST *> $null
	if ($LASTEXITCODE -eq 0) {
		schtasks /Delete /TN $taskName /F *> $null
	}
}
$ErrorActionPreference = $prevErrorPreference

# Discord bot at user logon so model predictions are ingested automatically.
schtasks /Create /TN "EVDiscordBot" /TR $botCmd /SC ONLOGON /RL LIMITED /F | Out-Null

# 3 daily collectors: morning open, midday, pre-game (replaces hourly - saves ~80% of credits)
schtasks /Create /TN "EVCollector0800" /TR $collectorCmd /SC DAILY /ST 08:00 /RL LIMITED /F | Out-Null
schtasks /Create /TN "EVCollector1200" /TR $collectorCmd /SC DAILY /ST 12:00 /RL LIMITED /F | Out-Null
schtasks /Create /TN "EVCollector1700" /TR $collectorCmd /SC DAILY /ST 17:00 /RL LIMITED /F | Out-Null

# 2 daily production scans
schtasks /Create /TN "EVScan1100" /TR $scanCmd /SC DAILY /ST 11:00 /RL LIMITED /F | Out-Null
schtasks /Create /TN "EVScan1700" /TR $scanCmd /SC DAILY /ST 17:30 /RL LIMITED /F | Out-Null

Write-Output "Created tasks: EVDiscordBot, EVCollector0800, EVCollector1200, EVCollector1700, EVScan1100, EVScan1700"
